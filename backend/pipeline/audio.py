"""Audio extraction — FFmpeg: 16 kHz mono WAV, the format faster-whisper
wants. Also ffprobe helpers for duration."""
from __future__ import annotations

import json
import subprocess


class FFmpegError(Exception):
    pass


def run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"FFmpeg timed out after {timeout}s: {' '.join(cmd)}") from exc
    except FileNotFoundError as exc:
        raise FFmpegError(
            "ffmpeg/ffprobe not found on PATH — install FFmpeg 8.x first.") from exc


def probe_duration(path: str) -> float:
    """Duration in seconds via ffprobe, or 0.0 if it cannot be read."""
    result = run(["ffprobe", "-v", "quiet", "-print_format", "json",
                  "-show_format", path], timeout=60)
    if result.returncode != 0:
        return 0.0
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def extract_audio(video_path: str, wav_path: str) -> str:
    """Extract 16 kHz mono WAV. Raises FFmpegError on failure."""
    result = run(["ffmpeg", "-y", "-v", "error", "-i", video_path,
                  "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                  wav_path])
    if result.returncode != 0:
        raise FFmpegError(
            f"Audio extraction failed: {result.stderr.strip()[:500]}")
    return wav_path
