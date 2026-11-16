"""Transcription wrapper around faster-whisper.

Graceful-failure rule: if faster-whisper (or the model) is unavailable,
the job reports a clear error — it NEVER fakes a transcript.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TranscriptionUnavailableError(Exception):
    """faster-whisper / the model could not be loaded or run."""


def transcribe(wav_path: str, model_name: str = "tiny",
               device: str = "cpu", compute_type: str = "int8") -> dict:
    """Return {"language": str, "segments": [...], "full_text": str}.

    Segments: [{start, end, text, words: [{start, end, word}]}].
    Word timestamps come from faster-whisper (word_timestamps=True) with
    Silero VAD filtering. Note: Whisper word timestamps are interpolated
    and can drift ~0.2-0.7s at segment starts — WhisperX forced alignment
    is the later-phase upgrade for karaoke-accurate captions.
    """
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
