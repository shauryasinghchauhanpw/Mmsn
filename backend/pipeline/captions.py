"""Caption generation — own .ass generator from faster-whisper word
timestamps, burned in with FFmpeg's libass `ass` filter.

Words are grouped into short captions (<=4 words, break on punctuation or
a pause >0.6s). Each word gets its own Dialogue event spanning that word's
time, showing the whole group with the current word highlighted yellow —
the standard karaoke trick. PlayRes matches the 1080x1920 output.
"""
from __future__ import annotations

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,Arial,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,80,80,220,1

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
    the group is full, when there is a pause > max_gap, or right after a
    word ending in sentence punctuation."""
    groups, current = [], []
    prev_end = None
    prev_word = None
    for w in words:
        gap = (w["start"] - prev_end) if prev_end is not None else 0.0
        if current and (len(current) >= max_words or gap > max_gap
                        or (prev_word is not None and prev_word.strip().endswith((".", "!", "?", ",")))):
            groups.append(current)
            current = []
        current.append(w)
        prev_end = w["end"]
        prev_word = w["word"]
    if current:
        groups.append(current)
    return groups


def words_to_ass(words, start_offset: float = 0.0) -> str:
    """Build the full .ass text for one clip. `words` are absolute-time
    word dicts; start_offset shifts them to clip-relative time."""
    lines = [ASS_HEADER]
    for group in group_words(words):
        group_text = "".join(w["word"] for w in group)
        for i, w in enumerate(group):
            parts = []
            for j, gw in enumerate(group):
                word = gw["word"].replace("{", "").replace("}", "")
                if j == i:
                    parts.append(r"{\c&H00FFFF&}" + word + r"{\c&HFFFFFF&}")
                else:
                    parts.append(word)
            text = "".join(parts)
            lines.append(
                "Dialogue: 0,{},{},Clip,,0,0,0,,{}\n".format(
                    _ass_time(w["start"] - start_offset),
                    _ass_time(w["end"] - start_offset + 0.08),
                    text))
    return "".join(lines)


def write_ass(words, start: float, end: float, out_path: str) -> str:
    """Write the .ass file for words inside [start, end]. Returns path."""
    clip_words = [w for w in words if w["end"] > start and w["start"] < end]
    content = words_to_ass(clip_words, start_offset=start)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return out_path
