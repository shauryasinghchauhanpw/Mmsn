"""Caption generation — own .ass generator from faster-whisper word
timestamps, burned in with FFmpeg's libass `ass` filter.

Words are grouped into short captions (<=4 words, break on punctuation or
a pause >0.6s). Each style below is a real ASS preset:

  karaoke     (default, the Phase 1 style): per-word events, the word being
              spoken is highlighted yellow, the rest white, large bold.
  minimal     clean white text, smaller, thin outline, one event per group
              (no per-word highlight) — for a quiet, unobtrusive look.
  bold        creator-style: very large bold white text, current word
              highlighted yellow (same karaoke trick, bigger + bolder).
  highlighted keywords highlighted: one event per group; "keyword" words
              (content words: >= 5 letters after stripping punctuation, or
              in the EMPHASIS set) are yellow, the rest white. This is a
              deterministic rule, not semantic analysis — a word is a
              keyword because it is long / emphatic, nothing smarter.

PlayRes matches the 1080x1920 output.
"""
from __future__ import annotations

# ASS style fields, in V4+ Styles Format order:
# Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,
# BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing,
# Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR,
# MarginV, Encoding
_STYLE_FIELDS = (
    "Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding"
)

# Per-word karaoke highlight (current word yellow) or one event per group.
CAPTION_STYLES = {
    "karaoke": {
        "label": "Karaoke",
        "per_word": True,
        "fontname": "Arial", "fontsize": 72,
        "primary": "&H00FFFFFF", "secondary": "&H0000FFFF",
        "outline_colour": "&H00000000", "back": "&H80000000",
        "bold": -1, "outline": 4, "shadow": 0, "margin_v": 220,
    },
    "minimal": {
        "label": "Minimal",
        "per_word": False,
        "fontname": "Arial", "fontsize": 56,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_colour": "&H00000000", "back": "&H00000000",
        "bold": 0, "outline": 2, "shadow": 0, "margin_v": 260,
    },
    "bold": {
        "label": "Bold creator",
        "per_word": True,
        "fontname": "Arial", "fontsize": 88,
        "primary": "&H00FFFFFF", "secondary": "&H0000FFFF",
        "outline_colour": "&H00000000", "back": "&H80000000",
        "bold": -1, "outline": 5, "shadow": 2, "margin_v": 200,
    },
    "highlighted": {
        "label": "Highlighted keywords",
        "per_word": False,
        "fontname": "Arial", "fontsize": 72,
        "primary": "&H00FFFFFF", "secondary": "&H0000FFFF",
        "outline_colour": "&H00000000", "back": "&H80000000",
        "bold": -1, "outline": 4, "shadow": 0, "margin_v": 220,
    },
}

DEFAULT_STYLE = "karaoke"

# Words that count as "keywords" for the highlighted style even when short.
EMPHASIS_WORDS = {
    "free", "best", "new", "secret", "how", "why", "stop", "never",
    "always", "first", "top", "win", "big", "easy", "fast",
}

HIGHLIGHT_ON = r"{\c&H00FFFF&}"   # yellow (ASS BGR: 00FFFF = yellow)
HIGHLIGHT_OFF = r"{\c&HFFFFFF&}"  # back to white


def _style_line(name: str, spec: dict) -> str:
    return (
        f"Style: {name},{spec['fontname']},{spec['fontsize']},"
        f"{spec['primary']},{spec['secondary']},{spec['outline_colour']},"
        f"{spec['back']},{spec['bold']},0,0,0,100,100,0,0,1,"
        f"{spec['outline']},{spec['shadow']},2,80,80,{spec['margin_v']},1\n"
    )


def ass_header(style: str = DEFAULT_STYLE) -> str:
    """The .ass header for one style preset. Unknown style -> default."""
    spec = CAPTION_STYLES.get(style, CAPTION_STYLES[DEFAULT_STYLE])
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: {_STYLE_FIELDS}
{_style_line("Clip", spec)}
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def group_words(words, max_words: int = 4, max_gap: float = 0.6):
    """Group a flat word list into caption groups. A new group starts when
    the group is full, when there is a pause > max_gap, right after a
    word ending in sentence punctuation, or when a word carries the
    ``_new_group`` flag — set by the editor's caption overrides so an
    edited group keeps its own boundary instead of being re-absorbed
    into a neighbour when the flat list is regrouped (see rerender.py)."""
    groups, current = [], []
    prev_end = None
    prev_word = None
    for w in words:
        gap = (w["start"] - prev_end) if prev_end is not None else 0.0
        if current and (len(current) >= max_words or gap > max_gap
                        or w.get("_new_group")
                        or (prev_word is not None and prev_word.strip().endswith((".", "!", "?", ",")))):
            groups.append(current)
            current = []
        current.append(w)
        prev_end = w["end"]
        prev_word = w["word"]
    if current:
        groups.append(current)
    return groups


def caption_groups(words, start: float, end: float):
    """Caption groups for the words inside [start, end], as plain dicts
    with clip-relative times — the shape the editor API returns.

    Each group: {index, start_sec, end_sec, text}. Times are relative to
    `start` (the clip window start), text is the words joined as spoken
    (words carry their own leading spaces, as faster-whisper emits them).
    """
    clip_words = [w for w in words if w["end"] > start and w["start"] < end]
    out = []
    for i, group in enumerate(group_words(clip_words)):
        out.append({
            "index": i,
            "start_sec": max(0.0, group[0]["start"] - start),
            "end_sec": max(0.0, group[-1]["end"] - start),
            "text": "".join(w["word"] for w in group),
        })
    return out


def _is_keyword(word: str) -> bool:
    """Deterministic keyword rule for the `highlighted` style: a word is
    a keyword if it has >= 5 letters (content word) or is in the small
    emphasis set. Honest limitation: this is a length heuristic, not
    semantic keyword extraction."""
    clean = word.strip().strip(".,!?;:\"'()[]").lower()
    return len(clean) >= 5 or clean in EMPHASIS_WORDS


def _clean(word: str) -> str:
    return word.replace("{", "").replace("}", "")


def words_to_ass(words, start_offset: float = 0.0,
                 style: str = DEFAULT_STYLE) -> str:
    """Build the full .ass text for one clip. `words` are absolute-time
    word dicts; start_offset shifts them to clip-relative time.
    `style` picks one of CAPTION_STYLES (unknown -> default)."""
    spec = CAPTION_STYLES.get(style, CAPTION_STYLES[DEFAULT_STYLE])
    lines = [ass_header(style)]
    for group in group_words(words):
        group_start = _ass_time(group[0]["start"] - start_offset)
        group_end = _ass_time(group[-1]["end"] - start_offset + 0.08)
        if spec["per_word"]:
            # Karaoke trick: one event per word, whole group shown, the
            # current word highlighted yellow.
            for i, w in enumerate(group):
                parts = []
                for j, gw in enumerate(group):
                    word = _clean(gw["word"])
                    if j == i:
                        parts.append(HIGHLIGHT_ON + word + HIGHLIGHT_OFF)
                    else:
                        parts.append(word)
                lines.append(
                    "Dialogue: 0,{},{},Clip,,0,0,0,,{}\n".format(
                        _ass_time(w["start"] - start_offset),
                        _ass_time(w["end"] - start_offset + 0.08),
                        "".join(parts)))
        elif style == "highlighted":
            # One event per group; keyword words yellow, the rest white.
            parts = []
            for gw in group:
                word = _clean(gw["word"])
                if _is_keyword(word):
                    parts.append(HIGHLIGHT_ON + word + HIGHLIGHT_OFF)
                else:
                    parts.append(word)
            lines.append(
                "Dialogue: 0,{},{},Clip,,0,0,0,,{}\n".format(
                    group_start, group_end, "".join(parts)))
        else:
            # Minimal: one plain event per group, no highlighting.
            text = "".join(_clean(gw["word"]) for gw in group)
            lines.append(
                "Dialogue: 0,{},{},Clip,,0,0,0,,{}\n".format(
                    group_start, group_end, text))
    return "".join(lines)


def write_ass(words, start: float, end: float, out_path: str,
              style: str = DEFAULT_STYLE) -> str:
    """Write the .ass file for words inside [start, end]. Returns path."""
    clip_words = [w for w in words if w["end"] > start and w["start"] < end]
    content = words_to_ass(clip_words, start_offset=start, style=style)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path
