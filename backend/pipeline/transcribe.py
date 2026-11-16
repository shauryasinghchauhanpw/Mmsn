"""Transcription — two providers behind one shape.

- ``local`` (default): faster-whisper on this machine (see
  :func:`_transcribe_local`). Needs ~1 GB of RAM for the ``tiny``
  model — fine on a VM, impossible on a 512 MB free host.
- ``groq``: Groq's hosted Whisper ``large-v3-turbo`` API (see
  ``backend/pipeline/groq_transcribe.py``). Free plan, no card, with
  word-level timestamps — the provider that makes the no-card Render
  free deploy work. Audio is sent to Groq's API (see that module's
  privacy note).

Selected by ``TRANSCRIPTION_PROVIDER`` (``local`` | ``groq``).
Graceful-failure rule: if the provider is unavailable, the job
reports a clear error — it NEVER fakes a transcript, and there is no
silent fallback between providers (on a 512 MB host a fallback to
local Whisper would just OOM instead of failing clearly).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


class TranscriptionUnavailableError(Exception):
    """The transcription provider could not be loaded or run."""


def transcribe(wav_path: str, model_name: str = "tiny",
               device: str = "cpu", compute_type: str = "int8",
               provider: str | None = None,
               groq_api_key: str | None = None,
               groq_model: str | None = None,
               groq_base_url: str | None = None,
               groq_max_chunk_seconds: int = 600) -> dict:
    """Return {"language": str, "segments": [...], "full_text": str}.

    Segments: [{start, end, text, words: [{start, end, word}]}].
    Word timestamps come from faster-whisper (word_timestamps=True) with
    Silero VAD filtering, or from Groq's verbose_json word timestamps.
    Note: Whisper word timestamps are interpolated and can drift
    ~0.2-0.7s at segment starts — WhisperX forced alignment is the
    later-phase upgrade for karaoke-accurate captions.
    """
    prov = (provider
            or os.environ.get("TRANSCRIPTION_PROVIDER", "local")
            ).strip().lower()
    if prov == "groq":
        from .groq_transcribe import (
            GROQ_DEFAULT_BASE_URL, GROQ_DEFAULT_MODEL, transcribe_groq)
        return transcribe_groq(
            wav_path,
            api_key=groq_api_key
            if groq_api_key is not None
            else os.environ.get("GROQ_API_KEY", ""),
            model=groq_model
            or os.environ.get("GROQ_MODEL", GROQ_DEFAULT_MODEL),
            base_url=groq_base_url
            or os.environ.get("GROQ_BASE_URL", GROQ_DEFAULT_BASE_URL),
            max_chunk_seconds=groq_max_chunk_seconds)
    if prov == "local":
        return _transcribe_local(wav_path, model_name, device, compute_type)
    raise TranscriptionUnavailableError(
        f"Unknown TRANSCRIPTION_PROVIDER '{prov}' — use 'local' "
        "(faster-whisper on this machine) or 'groq' (Groq's hosted "
        "Whisper API, free tier, no card).")


def _transcribe_local(wav_path: str, model_name: str = "tiny",
                      device: str = "cpu", compute_type: str = "int8") -> dict:
    """faster-whisper transcription (the original implementation)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionUnavailableError(
            "faster-whisper is not installed in this environment "
            "(pip install faster-whisper). Transcription cannot run, so the "
            "job stops here instead of producing a fake transcript."
        ) from exc

    try:
        model = WhisperModel(model_name, device=device,
                             compute_type=compute_type)
        segments_iter, info = model.transcribe(
            wav_path, word_timestamps=True, vad_filter=True)
        segments = []
        texts = []
        for seg in segments_iter:
            words = [{"start": float(w.start), "end": float(w.end),
                      "word": w.word} for w in (seg.words or [])]
            segments.append({"start": float(seg.start), "end": float(seg.end),
                             "text": seg.text.strip(), "words": words})
            texts.append(seg.text.strip())
    except Exception as exc:
        raise TranscriptionUnavailableError(
            f"Transcription failed (model '{model_name}', device '{device}'): "
            f"{exc}. Check the model downloaded correctly from Hugging Face "
            "and that the machine has enough memory."
        ) from exc

    if not segments:
        raise TranscriptionUnavailableError(
            "Transcription returned no speech — the audio may be silent or "
            "in an unsupported language. No transcript was fabricated.")

    return {"language": info.language, "segments": segments,
            "full_text": " ".join(texts)}
