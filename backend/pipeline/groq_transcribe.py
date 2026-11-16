"""Groq-hosted Whisper transcription (free tier, no card).

Why this exists: local faster-whisper needs ~1 GB of RAM while the
``tiny`` model transcribes, which no permanent no-card free host offers
(Render free is 512 MB; Koyeb free is 512 MB and wants a card; Oracle
free is big enough but needs a Visa/Mastercard for verification and
this user only has RuPay). Groq's free plan serves Whisper
``large-v3-turbo`` with **word-level timestamps** at no cost and no
card — 20 requests/min, 2,000 requests/day, 7,200 audio seconds/hour,
28,800 audio seconds/day (8 hours of audio a day), 25 MB max per file
— so the backend only needs RAM for FastAPI + FFmpeg + OpenCV, which
fits in 512 MB. Transcription quality is *better* than local ``tiny``
(large-v3-turbo vs tiny), not worse.

Privacy note: with this provider the audio leaves the machine and is
sent to Groq's API (their free plan has zero data retention as a
self-serve setting — see FREE_TIER.md). Local transcription keeps
audio on the server; Groq sends it to a third party. The provider is
opt-in (``TRANSCRIPTION_PROVIDER=groq``) and the default stays local.

Failure rule (same as local): any Groq problem — missing key, bad key,
rate limit, network error, empty transcript — raises
``TranscriptionUnavailableError`` with a clear message. The job stops;
nothing is ever faked, and there is NO silent fallback to local
Whisper (on a 512 MB host local Whisper would just OOM instead).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

import httpx

from .audio import FFmpegError, probe_duration, run as _ffmpeg_run
from .transcribe import TranscriptionUnavailableError

logger = logging.getLogger(__name__)

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "whisper-large-v3-turbo"
# Groq caps one upload at 25 MB. 16 kHz mono 16-bit WAV is 32,000
# bytes/second, so a 600 s chunk is ~19.2 MB — comfortably under the
# cap with margin. Longer audio is split into chunks (see below).
GROQ_MAX_FILE_BYTES = 25 * 1024 * 1024
_GROQ_SAFE_CHUNK_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_CHUNK_SECONDS = 600


def _chunk_wav(wav_path: str, max_chunk_seconds: int,
               work_dir: str) -> list[tuple[str, float]]:
    """Split `wav_path` into chunks of at most `max_chunk_seconds`
    (and at most ~20 MB each, under Groq's 25 MB cap).

    Returns [(chunk_path, offset_seconds), ...]. A short file is
    returned as-is, one chunk, offset 0. Raises
    TranscriptionUnavailableError if the audio cannot be read or split.
    """
    try:
        duration = probe_duration(wav_path)
        size = os.path.getsize(wav_path)
    except (OSError, FFmpegError) as exc:
        raise TranscriptionUnavailableError(
            f"Groq transcription: cannot read audio file {wav_path}: {exc}"
        ) from exc
    if duration <= 0:
        # ffprobe could not read a duration — send the file as one
        # chunk and let Groq answer (its error, if any, is reported).
        return [(wav_path, 0.0)]
    bytes_per_sec = max(1.0, size / duration)
    # Keep every chunk under the safe byte cap as well as the time cap.
    chunk_seconds = min(
        max_chunk_seconds,
        max(60, int(_GROQ_SAFE_CHUNK_BYTES / bytes_per_sec)),
    )
    if duration <= chunk_seconds:
        return [(wav_path, 0.0)]
    chunks: list[tuple[str, float]] = []
    start = 0.0
    idx = 0
    while start < duration:
        length = min(chunk_seconds, duration - start)
        chunk_path = os.path.join(work_dir, f"groq_chunk_{idx:03d}.wav")
        result = _ffmpeg_run([
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
            "-i", wav_path, "-c:a", "pcm_s16le", chunk_path])
        if result.returncode != 0 or not os.path.exists(chunk_path):
            raise TranscriptionUnavailableError(
                "Groq transcription: could not split audio into chunks "
                f"for upload: {result.stderr.strip()[:300]}")
        chunks.append((chunk_path, start))
        start += length
        idx += 1
    return chunks


def _words_into_segments(payload: dict, offset: float) -> list[dict]:
    """Map one Groq verbose_json response onto our segment shape.

    Groq returns top-level ``words`` [{word, start, end}] and
    ``segments`` [{start, end, text}]. Words are attached to the
    segment whose [start, end) contains the word's start; stray words
    (before the first / after the last segment) go to the nearest
    segment. If Groq returns words but no segments, one segment is
    built spanning the words. All times are shifted by `offset`
    (the chunk's start in the full audio).
    """
    raw_segments = payload.get("segments") or []
    raw_words = payload.get("words") or []
    segments: list[dict] = []
    for seg in raw_segments:
        try:
            segments.append({
                "start": float(seg["start"]) + offset,
                "end": float(seg["end"]) + offset,
                "text": str(seg.get("text", "")).strip(),
                "words": [],
            })
        except (KeyError, TypeError, ValueError):
            continue
    words: list[dict] = []
    for w in raw_words:
        try:
            words.append({
                "start": float(w["start"]) + offset,
                "end": float(w["end"]) + offset,
                "word": str(w.get("word", "")),
            })
        except (KeyError, TypeError, ValueError):
            continue
    words = [w for w in words if w["word"]]
    if not segments and words:
        segments.append({
            "start": words[0]["start"],
            "end": words[-1]["end"],
            "text": "".join(w["word"] for w in words).strip(),
            "words": [],
        })
    for w in words:
        target = None
        for seg in segments:
            if seg["start"] <= w["start"] < seg["end"]:
                target = seg
                break
        if target is None and segments:
            target = min(segments,
                         key=lambda s: abs(s["start"] - w["start"]))
        if target is not None:
            target["words"].append(w)
    for seg in segments:
        seg["words"].sort(key=lambda w: w["start"])
    return segments


def _transcribe_chunk(client: httpx.Client, base_url: str, api_key: str,
                      model: str, chunk_path: str,
                      timeout: float) -> dict:
    """One Groq /audio/transcriptions call. Returns the parsed
    verbose_json payload. Raises TranscriptionUnavailableError on any
    failure (bad key, rate limit, network error, bad response)."""
    url = base_url.rstrip("/") + "/audio/transcriptions"
    try:
        with open(chunk_path, "rb") as f:
            files = {"file": (os.path.basename(chunk_path), f, "audio/wav")}
            data = {
                "model": model,
                "response_format": "verbose_json",
                "temperature": "0",
                "timestamp_granularities[]": ["word", "segment"],
            }
            response = client.post(url, files=files, data=data,
                                   headers={"Authorization":
                                            f"Bearer {api_key}"},
                                   timeout=timeout)
    except httpx.TimeoutException as exc:
        raise TranscriptionUnavailableError(
            "Groq transcription timed out — the Groq API did not answer "
            f"in time: {exc}. Retry the job later."
        ) from exc
    except httpx.RequestError as exc:
        raise TranscriptionUnavailableError(
            "Groq transcription: could not reach the Groq API "
            f"({exc}). Check the server's network connection and retry."
        ) from exc
    if response.status_code == 401:
        raise TranscriptionUnavailableError(
            "Groq transcription: the GROQ_API_KEY was rejected (401). "
            "Create a fresh key at console.groq.com → API Keys and "
            "paste it into GROQ_API_KEY — never commit the key itself.")
    if response.status_code == 429:
        raise TranscriptionUnavailableError(
            "Groq transcription: rate limit hit (429). The free plan "
            "allows 20 requests/min and 8 hours of audio/day — wait a "
            "few minutes and retry the job. If this keeps happening, "
            "the account's daily quota is spent; try again tomorrow.")
    if response.status_code != 200:
        raise TranscriptionUnavailableError(
            "Groq transcription failed "
            f"(HTTP {response.status_code}): "
            f"{response.text[:300]}")
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise TranscriptionUnavailableError(
            "Groq transcription: the API answered with something that "
            f"is not JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise TranscriptionUnavailableError(
            "Groq transcription: unexpected API response shape "
            f"(not an object): {str(payload)[:200]}")
    return payload


def transcribe_groq(wav_path: str, api_key: str,
                    model: str = GROQ_DEFAULT_MODEL,
                    base_url: str = GROQ_DEFAULT_BASE_URL,
                    max_chunk_seconds: int = DEFAULT_MAX_CHUNK_SECONDS,
                    timeout: float = 600.0,
                    http_client: httpx.Client | None = None) -> dict:
    """Transcribe `wav_path` via Groq's Whisper API.

    Returns the same shape as the local transcriber:
    {"language": str, "segments": [{start, end, text, words}],
    "full_text": str}. Audio longer than `max_chunk_seconds` (or
    ~20 MB) is split into chunks and the timestamps merged with
    offsets, so long videos work inside Groq's 25 MB/file cap.
    """
    if not api_key:
        raise TranscriptionUnavailableError(
            "Groq transcription is selected (TRANSCRIPTION_PROVIDER="
            "groq) but GROQ_API_KEY is not set. Create a free key at "
            "console.groq.com → API Keys (no card needed) and set "
            "GROQ_API_KEY — or switch TRANSCRIPTION_PROVIDER back to "
            "'local' to use faster-whisper on this machine instead.")
    own_client = http_client is None
    client = http_client or httpx.Client()
    try:
        with tempfile.TemporaryDirectory(prefix="groq-chunks-") as tmp:
            chunks = _chunk_wav(wav_path, max_chunk_seconds, tmp)
            all_segments: list[dict] = []
            language = "en"
            for chunk_path, offset in chunks:
                payload = _transcribe_chunk(client, base_url, api_key,
                                            model, chunk_path, timeout)
                language = str(payload.get("language") or language)
                all_segments.extend(
                    _words_into_segments(payload, offset))
    finally:
        if own_client:
            client.close()
    all_segments.sort(key=lambda s: s["start"])
    texts = [s["text"] for s in all_segments if s["text"]]
    if not all_segments or not texts:
        raise TranscriptionUnavailableError(
            "Groq transcription returned no speech — the audio may be "
            "silent or in an unsupported language. No transcript was "
            "fabricated.")
    return {"language": language, "segments": all_segments,
            "full_text": " ".join(texts)}
