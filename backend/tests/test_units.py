"""Pure-function unit tests — no HTTP, no pipeline, no renders.

Covers: YouTube URL parsing (the 11 cases from TESTING.md Phase 1),
ISO-8601 durations, editor parameter merging/clamping, caption
re-timing and the group-boundary fix, ASS generation per style, and
the deterministic heuristic highlight scorer.
"""
import pytest

from backend.app.youtube import extract_video_id, parse_iso8601_duration
from backend.pipeline.captions import (
    CAPTION_STYLES, ass_header, caption_groups, group_words, words_to_ass)
from backend.pipeline.highlights import (
    detect_highlights, score_highlights_heuristic)
from backend.pipeline.rerender import (
    apply_caption_overrides, merge_edit_params, retime_text)
from backend.tests.conftest import make_segments, make_words

VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url,expected", [
    # watch, v first / v later in the query string
    (f"https://www.youtube.com/watch?v={VIDEO_ID}", VIDEO_ID),
    (f"https://www.youtube.com/watch?list=PLx&t=5s&v={VIDEO_ID}", VIDEO_ID),
    (f"https://youtube.com/watch?v={VIDEO_ID}&feature=share", VIDEO_ID),
    (f"https://music.youtube.com/watch?v={VIDEO_ID}", VIDEO_ID),
    (f"https://youtu.be/{VIDEO_ID}", VIDEO_ID),
    (f"https://youtu.be/{VIDEO_ID}?t=42", VIDEO_ID),
    (f"https://www.youtube.com/shorts/{VIDEO_ID}", VIDEO_ID),
    (f"https://www.youtube.com/embed/{VIDEO_ID}", VIDEO_ID),
    (f"https://www.youtube.com/live/{VIDEO_ID}", VIDEO_ID),
    (f"https://www.youtube.com/v/{VIDEO_ID}", VIDEO_ID),
    (VIDEO_ID, VIDEO_ID),  # bare 11-char ID pasted directly
])
def test_extract_video_id_valid(url, expected):
    assert extract_video_id(url) == expected


@pytest.mark.parametrize("url", [
    "",
    "https://example.com/not-a-video",
    f"https://www.youtube.com/watch?v=short",       # v too short
    f"https://www.youtube.com/watch?list=PLx",       # no v param
    f"https://www.youtube.com/channel/UC12345678901",
    "dQw4w9WgXc",                                    # 10 chars, not 11
])
def test_extract_video_id_invalid(url):
    assert extract_video_id(url) is None


@pytest.mark.parametrize("value,expected", [
    ("PT1H2M3S", 3723.0),
    ("PT5M30S", 330.0),
    ("PT45S", 45.0),
    ("PT1M0.5S", 60.5),
    ("PT0S", 0.0),
    ("", 0.0),
    ("garbage", 0.0),
    ("PT2H", 7200.0),
])
def test_parse_iso8601_duration(value, expected):
    assert parse_iso8601_duration(value) == expected


# ── merge_edit_params ────────────────────────────────────────────────────

def test_merge_edit_params_defaults():
    params = merge_edit_params({}, 28.62, None)
    assert params["trim_start"] == 0.0
    assert params["trim_end"] == 28.62
    assert params["style"] == "karaoke"
    assert params["framing_offset"] == 0.0
    assert params["volume"] == 1.0
    assert params["caption_overrides"] == []


def test_merge_edit_params_clamps_and_drops_unknowns():
    params = merge_edit_params(
        {"framing_offset": 5.0, "volume": 9.0, "bogus_key": 1,
         "style": "nope", "trim_start": -3.0, "trim_end": 999.0},
        28.62, None)
    assert params["framing_offset"] == 1.0
    assert params["volume"] == 2.0
    assert params["style"] == "karaoke"  # unknown style -> default
    assert params["trim_start"] == 0.0
    assert params["trim_end"] == 28.62
    assert "bogus_key" not in params


def test_merge_edit_params_update_wins_over_stored():
    params = merge_edit_params(
        {"style": "bold", "volume": 0.5}, 28.62, {"volume": 1.5})
    assert params["style"] == "bold"   # stored kept
    assert params["volume"] == 1.5     # update wins
    params = merge_edit_params({"volume": 0.1}, 28.62, None)
    assert params["volume"] == 0.25    # clamped to minimum


# ── Caption re-timing / overrides ────────────────────────────────────────

def test_retime_text_spreads_words_evenly():
    words = retime_text("HELLO EDITED WORDS", 0.0, 3.0)
    assert [w["word"] for w in words] == ["HELLO", " EDITED", " WORDS"]
    assert words[0]["start"] == 0.0 and words[0]["end"] == 1.0
    assert words[1]["start"] == 1.0 and words[1]["end"] == 2.0
    assert words[2]["start"] == 2.0 and words[2]["end"] == 3.0
    assert retime_text("", 0.0, 3.0) == []
    assert retime_text("   ", 0.0, 3.0) == []


def test_apply_caption_overrides_keeps_group_boundaries():
    """Regression test for the Phase 2 bug: editing group 0 used to
    absorb the next group's first word ("HELLO EDITED WORDS welcome").
    The _new_group boundary flag must keep the groups exact."""
    text = ("Hello everyone, welcome back to the channel. Today we share "
            "a secret about short videos.")
    words = make_words(text, 0.0, 20.0)
    edited = apply_caption_overrides(
        words, 0.0, 20.0, [{"group_index": 0, "text": "HELLO EDITED WORDS"}])
    groups = ["".join(w["word"] for w in g) for g in group_words(edited)]
    assert groups[0] == "HELLO EDITED WORDS"
    assert groups[1].strip().startswith("welcome"), groups[1]


def test_apply_caption_overrides_empty_text_drops_group():
    words = make_words("one two three four five six seven eight", 0.0, 8.0)
    edited = apply_caption_overrides(
        words, 0.0, 8.0, [{"group_index": 0, "text": ""}])
    groups = ["".join(w["word"] for w in g) for g in group_words(edited)]
    assert groups[0].strip().startswith("five"), groups
    assert not any("one" in g for g in groups)


def test_apply_caption_overrides_unknown_group_ignored():
    words = make_words("one two three four five six", 0.0, 6.0)
    edited = apply_caption_overrides(
        words, 0.0, 6.0, [{"group_index": 99, "text": "NOPE"}])
    assert [w["word"] for w in edited] == [w["word"] for w in words]


def test_group_words_new_group_flag_forces_split():
    words = make_words("alpha beta gamma delta epsilon", 0.0, 5.0)
    words[2]["_new_group"] = True
    groups = group_words(words)
    assert len(groups) == 2
    assert "".join(w["word"] for w in groups[0]) == "alpha beta"
    assert "".join(w["word"] for w in groups[1]).strip().startswith("gamma")


def test_caption_groups_are_clip_relative():
    words = make_words("one two three four five six seven eight", 0.0, 8.0)
    groups = caption_groups(words, 2.0, 6.0)
    assert groups
    assert groups[0]["start_sec"] >= 0.0
    assert all(g["end_sec"] <= 4.0 + 1e-9 for g in groups)
    assert all(g["text"] for g in groups)


# ── ASS generation ───────────────────────────────────────────────────────

def test_ass_styles_differ():
    karaoke = [l for l in ass_header("karaoke").splitlines()
               if l.startswith("Style:")][0]
    bold = [l for l in ass_header("bold").splitlines()
            if l.startswith("Style:")][0]
    assert karaoke != bold
    assert set(CAPTION_STYLES) == {"karaoke", "minimal", "bold",
                                   "highlighted"}


def test_words_to_ass_karaoke_is_per_word():
    words = make_words("Hello world today", 0.0, 3.0)
    ass = words_to_ass(words, start_offset=0.0, style="karaoke")
    # Karaoke emits one Dialogue event per word (the current word is
    # highlighted); the words never appear as one contiguous string.
    assert ass.count("Dialogue:") == 3
    for w in ("Hello", "world", "today"):
        assert w in ass


def test_words_to_ass_minimal_is_per_group():
    words = make_words("Hello world today", 0.0, 3.0)
    ass = words_to_ass(words, start_offset=0.0, style="minimal")
    assert ass.count("Dialogue:") == 1
    assert "Hello world today" in ass


def test_words_to_ass_unknown_style_falls_back_to_default():
    words = make_words("Hello world", 0.0, 2.0)
    assert words_to_ass(words, style="nope") == words_to_ass(words)


# ── Heuristic highlight scorer ───────────────────────────────────────────

def _scorer_segments():
    text = ("Hello everyone, welcome back to the channel. Today I am going "
            "to share a secret about how to make your first short video go "
            "viral in 2026. Most creators make the same mistake: they start "
            "with a boring introduction and lose the viewer in the first "
            "three seconds. Here is the truth. The first three seconds "
            "decide everything. If you hook the viewer fast, they stay. If "
            "you do not, they scroll away forever. So here are five proven "
            "tricks that actually work. First, start with a question. Ask "
            "the viewer something they already care about. Second, show the "
            "result before you explain the process. People love a payoff.")
    return make_segments(text, 0.0, 65.0, n_segments=3)


def test_heuristic_scorer_is_deterministic():
    segments = _scorer_segments()
    first, scorer = detect_highlights(segments, count=2, llm_config=None)
    second, scorer2 = detect_highlights(segments, count=2, llm_config=None)
    assert scorer == scorer2 == "heuristic"
    assert first == second
    assert 1 <= len(first) <= 2
    for h in first:
        assert 0 <= h["score"] <= 100
        assert 15 <= h["end_sec"] - h["start_sec"] <= 60
        assert h["reasons"] and h["title"] and h["hashtags"]


def test_heuristic_scorer_picks_non_overlapping():
    segments = _scorer_segments()
    picked, _ = detect_highlights(segments, count=3, llm_config=None)
    for i, a in enumerate(picked):
        for b in picked[i + 1:]:
            assert a["end_sec"] <= b["start_sec"] \
                or b["end_sec"] <= a["start_sec"]


def test_heuristic_scorer_empty_transcript():
    assert score_highlights_heuristic([], count=3) == []
    highlights, scorer = detect_highlights([], count=3, llm_config=None)
    assert highlights == [] and scorer == "heuristic"
