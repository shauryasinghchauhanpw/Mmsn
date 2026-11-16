"""Groq transcription provider tests — no real Groq key, no real API call.

A tiny http.server in this process implements POST
/openai/v1/audio/transcriptions and returns canned verbose_json with
segment + word timestamps. Checks:
  1. Success -> our segment shape, word timestamps, language, full_text.
  2. Chunking -> an 11-minute WAV is split into 2 requests and the
     second chunk's words come back shifted by the 600 s offset.
  3. 401 / 429 / 500 / empty transcript / missing key -> clear
     TranscriptionUnavailableError (never a fake transcript).
  4. Provider routing -> transcribe(provider="groq") uses Groq,
     transcribe(provider="nope") errors, local default untouched.
The mock counts requests, so the tests also prove Groq is actually
called (not silently skipped) when selected.
"""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.pipeline.groq_transcribe import transcribe_groq
from backend.pipeline.transcribe import (
    TranscriptionUnavailableError, transcribe)


def _make_wav(path: str, seconds: int, freq: int = 440) -> str:
    r = subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={seconds}",
        "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", path],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return path


@pytest.fixture()
def mock_groq():
    """Local mock Groq server. Yields (base_url, state) where state
    has 'fail' (None | '401' | '429' | '500' | 'empty'), 'bodies'
    (raw request bodies) and 'count' (requests seen). Each request
    gets words labelled with its own chunk index so chunking tests
    can tell the chunks apart."""
    state = {"fail": None, "bodies": [], "count": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            state["bodies"].append(self.rfile.read(n))
            state["count"] += 1
            if self.path != "/openai/v1/audio/transcriptions":
                self.send_response(404)
                self.end_headers()
                return
            fail = state["fail"]
            if fail == "401":
                self._send(401, {"error": {
                    "message": "Incorrect API key provided."}})
                return
            if fail == "429":
                self._send(429, {"error": {
                    "message": "Rate limit reached for model."}})
                return
            if fail == "500":
                self._send(500, {"error": {
                    "message": "mock server error"}})
                return
            if fail == "empty":
                self._send(200, {"language": "en", "segments": [],
                                 "words": []})
                return
            idx = state["count"] - 1
            payload = {
                "language": "en",
                "duration": 1.5,
                "segments": [{"id": 0, "start": 0.0, "end": 1.5,
                              "text": f"chunk{idx} hello world"}],
                "words": [
                    {"word": f"chunk{idx}", "start": 0.0, "end": 0.5},
                    {"word": "hello", "start": 0.5, "end": 1.0},
                    {"word": "world", "start": 1.0, "end": 1.5},
                ],
            }
            self._send(200, payload)

        def _send(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, state
    server.shutdown()
    server.server_close()


def test_groq_success_word_timestamps(mock_groq, tmp_path):
    base, state = mock_groq
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    result = transcribe_groq(wav, api_key="dummy-key-not-real",
                             base_url=f"{base}/openai/v1")
    assert result["language"] == "en"
    assert len(result["segments"]) == 1
    seg = result["segments"][0]
    assert seg["text"] == "chunk0 hello world"
    assert [w["word"] for w in seg["words"]] == [
        "chunk0", "hello", "world"]
    assert seg["words"][1]["start"] == pytest.approx(0.5)
    assert seg["words"][2]["end"] == pytest.approx(1.5)
    assert result["full_text"] == "chunk0 hello world"
    # The mock was actually called, once, asking for verbose_json +
    # word timestamps with the turbo model.
    assert state["count"] == 1
    body = state["bodies"][0]
    assert b"whisper-large-v3-turbo" in body
    assert b"verbose_json" in body
    assert b"timestamp_granularities" in body


def test_groq_chunking_offsets(mock_groq, tmp_path):
    base, state = mock_groq
    wav = _make_wav(str(tmp_path / "long.wav"), 660)  # 11 min
    result = transcribe_groq(wav, api_key="dummy-key-not-real",
                             base_url=f"{base}/openai/v1")
    # 660 s at 600 s/chunk -> exactly 2 Groq requests.
    assert state["count"] == 2
    assert len(result["segments"]) == 2
    first, second = result["segments"]
    assert first["words"][0]["word"] == "chunk0"
    assert first["words"][0]["start"] == pytest.approx(0.0)
    # Second chunk's words are shifted by the 600 s chunk offset.
    assert second["words"][0]["word"] == "chunk1"
    assert second["words"][0]["start"] == pytest.approx(600.0)
    assert second["words"][2]["end"] == pytest.approx(601.5)
    assert second["start"] == pytest.approx(600.0)
    assert "chunk0 hello world" in result["full_text"]
    assert "chunk1 hello world" in result["full_text"]


def test_groq_401_bad_key(mock_groq, tmp_path):
    base, state = mock_groq
    state["fail"] = "401"
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe_groq(wav, api_key="bad-key", base_url=f"{base}/openai/v1")
    assert "401" in str(exc.value)
    assert "GROQ_API_KEY" in str(exc.value)


def test_groq_429_rate_limit(mock_groq, tmp_path):
    base, state = mock_groq
    state["fail"] = "429"
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe_groq(wav, api_key="dummy-key-not-real", base_url=f"{base}/openai/v1")
    assert "rate limit" in str(exc.value).lower()


def test_groq_500_error(mock_groq, tmp_path):
    base, state = mock_groq
    state["fail"] = "500"
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe_groq(wav, api_key="dummy-key-not-real", base_url=f"{base}/openai/v1")
    assert "500" in str(exc.value)


def test_groq_empty_transcript(mock_groq, tmp_path):
    base, state = mock_groq
    state["fail"] = "empty"
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe_groq(wav, api_key="dummy-key-not-real", base_url=f"{base}/openai/v1")
    assert "no speech" in str(exc.value).lower()


def test_groq_missing_key(tmp_path):
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe_groq(wav, api_key="")
    assert "GROQ_API_KEY" in str(exc.value)


def test_provider_routing_groq(mock_groq, tmp_path):
    base, state = mock_groq
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    result = transcribe(wav, provider="groq", groq_api_key="dummy-key",
                        groq_base_url=f"{base}/openai/v1")
    assert state["count"] == 1
    assert result["segments"][0]["text"] == "chunk0 hello world"


def test_provider_routing_groq_missing_key(tmp_path):
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe(wav, provider="groq", groq_api_key="")
    assert "GROQ_API_KEY" in str(exc.value)


def test_provider_unknown(tmp_path):
    wav = _make_wav(str(tmp_path / "short.wav"), 5)
    with pytest.raises(TranscriptionUnavailableError) as exc:
        transcribe(wav, provider="nope")
    assert "TRANSCRIPTION_PROVIDER" in str(exc.value)
