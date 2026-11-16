"""LLM highlight-scoring tests — converted from /tmp/test_llm_mock.py
(Phase 2, step 3).

No real OpenAI key, no real API call. A tiny http.server in this
process implements POST /chat/completions and returns a canned
highlight array; detect_highlights() is pointed at it with a dummy
key. Checks:
  1. Mock success  -> scorer == "llm", the mock's picks/scores.
  2. Mock returns 500 -> scorer == "heuristic", fallback reasons say
     "LLM scoring unavailable".
  3. No llm_config -> scorer == "heuristic".
Also verifies the mock actually received transcript text in its
request. Transcript segments here are synthetic (built by the
conftest helper); the scorer only ever sees text.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.pipeline.highlights import detect_highlights
from backend.tests.conftest import TEST_SCRIPT, make_segments

CANNED = [{
    "start_sec": 28.62, "end_sec": 57.76, "score": 95,
    "reasons": ["Mock LLM pick: strongest hook"],
    "title": "MOCK LLM TITLE ONE",
    "description": "Mock description one.",
    "hashtags": ["#mock", "#shorts"],
}, {
    "start_sec": 0.0, "end_sec": 28.62, "score": 88,
    "reasons": ["Mock LLM pick: second moment"],
    "title": "MOCK LLM TITLE TWO",
    "description": "Mock description two.",
    "hashtags": ["#mock2", "#shorts"],
}]


@pytest.fixture()
def mock_llm():
    """Local mock OpenAI-compatible server. Yields (base_url, state)
    where state has 'fail' (bool) and 'bodies' (request bodies seen)."""
    state = {"fail": False, "bodies": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            state["bodies"].append(self.rfile.read(n).decode())
            if self.path != "/chat/completions":
                self.send_response(404)
                self.end_headers()
                return
            if state["fail"]:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    b'{"error": {"message": "mock server error"}}')
                return
            data = json.dumps(
                {"choices": [{"message": {"content": json.dumps(CANNED)}}]}
            ).encode()
            self.send_response(200)
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


@pytest.fixture()
def segments():
    return make_segments(TEST_SCRIPT, 0.0, 65.0, n_segments=3)


def _llm_config(mock_llm):
    base, _state = mock_llm
    return ("dummy-key-not-real", base, "mock-model")


def test_mock_success_uses_llm(mock_llm, segments):
    base, state = mock_llm
    state["fail"] = False
    state["bodies"] = []
    highlights, scorer = detect_highlights(
        segments, count=2, llm_config=_llm_config(mock_llm))

    assert scorer == "llm"
    assert len(highlights) == 2
    assert highlights[0]["title"] == "MOCK LLM TITLE ONE"
    assert highlights[0]["score"] == 95  # the mock's score, not heuristic
    assert abs(highlights[0]["start_sec"] - 28.62) < 0.01
    assert abs(highlights[0]["end_sec"] - 57.76) < 0.01
    assert highlights[1]["title"] == "MOCK LLM TITLE TWO"
    assert highlights[1]["score"] == 88

    # The mock received exactly one request carrying transcript text.
    assert len(state["bodies"]) == 1
    assert "Hello everyone" in state["bodies"][0]
    assert "TRANSCRIPT" in state["bodies"][0]
    req = json.loads(state["bodies"][0])
    assert req["model"] == "mock-model"


def test_mock_500_falls_back_to_heuristic(mock_llm, segments):
    base, state = mock_llm
    state["fail"] = True
    highlights, scorer = detect_highlights(
        segments, count=2, llm_config=_llm_config(mock_llm))

    assert scorer == "heuristic"
    assert len(highlights) == 2
    assert highlights[0]["reasons"][0].startswith(
        "LLM scoring unavailable")
    # Fallback picks are the heuristic's, not the mock's.
    assert highlights[0]["title"] != "MOCK LLM TITLE ONE"


def test_mock_500_fallback_matches_no_config(mock_llm, segments):
    base, state = mock_llm
    state["fail"] = True
    fallback, _ = detect_highlights(
        segments, count=2, llm_config=_llm_config(mock_llm))
    plain, scorer = detect_highlights(segments, count=2, llm_config=None)
    assert scorer == "heuristic"
    assert [h["score"] for h in plain] == [h["score"] for h in fallback]
    assert [h["start_sec"] for h in plain] == \
        [h["start_sec"] for h in fallback]


def test_no_config_uses_heuristic(segments):
    highlights, scorer = detect_highlights(segments, count=2,
                                           llm_config=None)
    assert scorer == "heuristic"
    assert len(highlights) >= 1
    assert all(0 <= h["score"] <= 100 for h in highlights)


def test_empty_api_key_uses_heuristic(mock_llm, segments):
    """An llm_config with an empty key is treated as 'no LLM' — the
    scorer must never attempt a call or claim an LLM score."""
    base, state = mock_llm
    state["bodies"] = []
    highlights, scorer = detect_highlights(
        segments, count=2, llm_config=("", base, "mock-model"))
    assert scorer == "heuristic"
    assert state["bodies"] == []
