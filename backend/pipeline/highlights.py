"""Transcript-based highlight detection + virality scoring (0-100).

Phase 1 ships a deterministic heuristic scorer so the pipeline works with
zero API keys. The LLM scorer (OpenAI-compatible) plugs into the same
interface when OPENAI_API_KEY is set — and it only ever receives transcript
TEXT, never video or audio.

A "highlight" is a self-contained window of speech, 15-60s, scored on:
hook words (questions, numbers, superlatives, "secret"/"never"/"mistake"...),
emphasis (exclamations, caps), speech density, and position.
Each clip ships with reasons, a suggested title, description and hashtags.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

HOOK_WORDS = {
    "how", "why", "what", "secret", "never", "always", "mistake", "truth",
    "amazing", "insane", "crazy", "best", "worst", "first", "finally",
    "stop", "start", "free", "easy", "hack", "trick", "nobody", "everyone",
    "actually", "exactly", "believe", "imagine", "remember", "warning",
    "shocking", "incredible", "unbelievable", "proven", "guaranteed",
}
QUESTION_WORDS = {"how", "why", "what", "when", "where", "who", "which"}
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent|million|billion|thousand|k)?\b")
CAPS_RE = re.compile(r"\b[A-Z]{3,}\b")

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "it", "this", "that", "you", "your",
    "we", "they", "he", "she", "i", "me", "my", "so", "just", "like", "get",
    "got", "really", "very", "much", "more", "then", "than", "when", "what",
    "how", "why", "not", "no", "yes", "can", "could", "will", "would",
}


def _window_text(segments, start, end):
    return " ".join(s["text"] for s in segments
                    if s["end"] > start and s["start"] < end)


def _score_window(text: str, start: float, duration: float,
                  word_count: int) -> tuple[int, list[str]]:
    reasons = []
    score = 40  # base: coherent speech
    lower = text.lower()
    words = re.findall(r"[a-z']+", lower)

    hooks = sorted({w for w in words if w in HOOK_WORDS})
    if hooks:
        score += min(18, 6 * len(hooks))
        reasons.append(f"Hook words: {', '.join(hooks[:4])}")
    if any(w in QUESTION_WORDS for w in words[:6]):
        score += 8
        reasons.append("Opens with a question — strong Shorts hook")
    if NUMBER_RE.search(text):
        score += 6
        reasons.append("Contains a concrete number/stat")
    if "!" in text or "?" in text:
        score += 5
        reasons.append("Emphatic delivery (!/?)")
    if CAPS_RE.search(text):
        score += 3
        reasons.append("Emphasised words in transcript")
    # Speech density: 2-3.5 words/sec is natural, engaging pace.
    wps = word_count / max(duration, 1)
    if 2.0 <= wps <= 3.5:
        score += 7
        reasons.append(f"Natural speaking pace ({wps:.1f} words/sec)")
    elif wps > 4.5:
        score += 2
        reasons.append("Fast-paced delivery")
    # Early moments hook scrollers; very late moments are less likely to
    # be the clip people share first.
    if start < 60:
        score += 5
        reasons.append("Early in the video — good hook position")
    if not reasons:
        reasons.append("Coherent, self-contained speech")
    return min(100, max(0, score)), reasons


def _candidate_windows(segments, min_s, max_s):
    """Sliding windows over segment boundaries, 15-60s each."""
    if not segments:
        return []
    starts = sorted({s["start"] for s in segments})
    ends = sorted({s["end"] for s in segments})
    windows = []
    for start in starts:
        for end in ends:
            dur = end - start
            if min_s <= dur <= max_s:
                text = _window_text(segments, start, end)
                wc = len(text.split())
                if wc >= 20:  # need enough speech to be a clip
                    windows.append((start, end, text, wc))
    return windows


def _make_title(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    first = first.strip().strip('"').strip()
    if len(first) > 80:
        first = first[:77].rsplit(" ", 1)[0] + "..."
    return first or "Untitled clip"


def _hashtags(text: str, title: str) -> list[str]:
    words = re.findall(r"[a-z]{4,}", (title + " " + text).lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    top = sorted(freq, key=freq.get, reverse=True)[:4]
    tags = ["#shorts", "#viral"]
    tags += [f"#{w}" for w in top]
    return tags[:6]


def score_highlights_heuristic(segments, count=3, min_s=15, max_s=60):
    """Deterministic scorer — no API key needed."""
    windows = _candidate_windows(segments, min_s, max_s)
    scored = []
    for start, end, text, wc in windows:
        score, reasons = _score_window(text, start, end - start, wc)
        scored.append({"start_sec": round(start, 2), "end_sec": round(end, 2),
                       "score": score, "reasons": reasons,
                       "title": _make_title(text),
                       "description": text[:500],
                       "hashtags": _hashtags(text, _make_title(text))})
    scored.sort(key=lambda h: (-h["score"], h["start_sec"]))
    # Greedy non-overlapping pick (clips must not overlap).
    picked = []
    for h in scored:
        if len(picked) >= count:
            break
        if all(h["end_sec"] <= p["start_sec"] or h["start_sec"] >= p["end_sec"]
               for p in picked):
            picked.append(h)
    picked.sort(key=lambda h: h["start_sec"])
    return picked


def score_highlights_llm(segments, api_key, base_url, model, count=3,
                         min_s=15, max_s=60):
    """LLM scorer — transcript text ONLY is sent. Falls back to the
    heuristic scorer on any failure, and says so in the reasons."""
    import httpx

    text = "\n".join(
        f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}"
        for s in segments)
    prompt = (
        "You are a Shorts editor. Below is a video transcript with timestamps "
        "(seconds). Pick the %d most viral, self-contained moments, each "
        "%d-%d seconds long, that work as standalone vertical Shorts. "
        "Return ONLY a JSON array: "
        '[{"start_sec": float, "end_sec": float, "score": 0-100, '
        '"reasons": ["..."], "title": "...", "description": "...", '
        '"hashtags": ["#..."]}]' % (count, min_s, max_s)
        + "\n\nTRANSCRIPT:\n" + text[:12000])
    try:
        resp = httpx.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model,
                  "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.3},
            timeout=120)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content[content.index("["):content.rindex("]") + 1])
        out = []
        for h in data[:count]:
            out.append({
                "start_sec": float(h["start_sec"]),
                "end_sec": float(h["end_sec"]),
                "score": int(max(0, min(100, h.get("score", 50)))),
                "reasons": list(h.get("reasons", ["LLM-selected moment"])),
                "title": h.get("title", "Untitled clip")[:200],
                "description": h.get("description", "")[:500],
                "hashtags": list(h.get("hashtags", ["#shorts"]))[:6],
            })
        if out:
            return out
    except Exception as exc:  # noqa: BLE001 — any LLM failure = heuristic
        logger.warning("LLM scoring failed (%s); using heuristic scorer", exc)
    fallback = score_highlights_heuristic(segments, count, min_s, max_s)
    for h in fallback:
        h["reasons"] = ["LLM scoring unavailable — heuristic score"] + h["reasons"]
    return fallback


def detect_highlights(segments, count=3, min_s=15, max_s=60,
                      llm_config=None):
    """llm_config = (api_key, base_url, model) or None for heuristic."""
    if llm_config and llm_config[0]:
        return score_highlights_llm(segments, *llm_config, count=count,
                                    min_s=min_s, max_s=max_s)
    return score_highlights_heuristic(segments, count, min_s, max_s)
