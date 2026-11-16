"""Scene detection hook — PySceneDetect (headless), optional.

If scenedetect is not installed the pipeline logs a warning and continues
with no scene list; clip boundaries are not snapped. Never a hard failure.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def detect_scenes(video_path: str, threshold: float = 27.0):
    """Return a list of (start_sec, end_sec) scene spans, or [] if the
    detector is unavailable / detection fails."""
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector
    except ImportError:
        logger.warning(
            "scenedetect not installed — skipping scene detection "
            "(clip boundaries will not be snapped to cuts).")
        return []
    try:
        video = open_video(video_path)
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=threshold))
        manager.detect_scenes(video, show_progress=False)
        scenes = manager.get_scene_list()
        return [(s[0].get_seconds(), s[1].get_seconds()) for s in scenes]
    except Exception as exc:  # noqa: BLE001 — scene detection is best-effort
        logger.warning("Scene detection failed (%s); continuing without it", exc)
        return []


def snap_to_scene(start: float, end: float, scenes, max_shift: float = 1.5):
    """Snap a clip window to the nearest scene cut within max_shift seconds.
    No scenes -> window unchanged."""
    if not scenes:
        return start, end
    new_start, new_end = start, end
    for s_start, _ in scenes:
        if abs(s_start - start) <= max_shift:
            new_start = s_start
            break
    for _, s_end in scenes:
        if abs(s_end - end) <= max_shift:
            new_end = s_end
            break
    if new_end - new_start < 5:
        return start, end
    return new_start, new_end
