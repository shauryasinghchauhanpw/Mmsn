"""9:16 reframing — face-tracked crop to 1080x1920.

Real implementation, built on OpenCV YuNet (MIT model, OpenCV Zoo):
sample face position ~2x/sec -> pick the largest face -> smooth the path
(EMA + max-displacement clamp) -> reset instantly at scene cuts -> crop
window follows the face. Falls back to centre crop whenever no face is
found or the detector/model is unavailable. Face detection finds boxes;
it never identifies people.

The YuNet model (~233 KB ONNX) is NOT committed to the repo: it downloads
on first use from a pinned OpenCV Zoo revision and its SHA-256 is verified
before use. `models/` is gitignored.
"""
from __future__ import annotations

import hashlib
import logging
import os
import statistics
import urllib.request

logger = logging.getLogger(__name__)

# Pinned OpenCV Zoo revision + published SHA-256 (verified 2026-11-16:
# file is 232,589 bytes; SHA matches the hash published by TransLearn/
# OpenCV Zoo guides for this revision).
MODEL_URL = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    "47534e27c9851bb1128ccc0102f1145e27f23f98/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_PATH = os.path.join(os.path.dirname(__file__), "models",
                          "face_detection_yunet_2023mar.onnx")

_detector = None


def ensure_model() -> str | None:
    """Return the local YuNet model path, downloading + SHA-verifying it
    on first use. Returns None (with a warning) on any failure — the
    caller falls back to centre crop."""
    if os.path.exists(MODEL_PATH):
        return MODEL_PATH
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    tmp_path = MODEL_PATH + ".tmp"
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=120) as resp:
            data = resp.read()
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            logger.warning("YuNet model SHA-256 mismatch — refusing to use it.")
            return None
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, MODEL_PATH)
        logger.info("Downloaded YuNet model (%d bytes)", len(data))
        return MODEL_PATH
    except Exception as exc:  # noqa: BLE001 — model is optional
        logger.warning("Could not download YuNet model (%s); using centre crop", exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return None


def _get_detector():
    global _detector
    if _detector is not None:
        return _detector
    model = ensure_model()
    if model is None:
        return None
    try:
        import cv2
        _detector = cv2.FaceDetectorYN.create(model, "", (320, 320))
        return _detector
    except Exception as exc:  # noqa: BLE001 — detector is optional
        logger.warning("Could not create YuNet detector (%s); using centre crop", exc)
        return None


def sample_face_centers(video_path: str, start: float, end: float,
                        sample_fps: float = 2.0):
    """Sample the video every 1/sample_fps seconds; return a list of
    (t, center_x) with center_x in 0..1 of frame width, or None for
    samples with no face. Empty list if the detector/video is unusable."""
    detector = _get_detector()
    if detector is None:
        return []
    try:
        import cv2
    except ImportError:
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0
    if width <= 0:
        cap.release()
        return []
    samples = []
    t = start
    step = 1.0 / sample_fps
    while t <= end:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            samples.append((t, None))
            t += step
            continue
        h, w = frame.shape[:2]
        detector.setInputSize((w, h))
        try:
            _, faces = detector.detect(frame)
        except Exception:  # noqa: BLE001 — one bad frame must not kill the job
            faces = None
        center = None
        if faces is not None and len(faces) > 0:
            # Largest face wins (closest speaker); columns are
            # x, y, w, h, ... per the YuNet output format.
            biggest = max(faces, key=lambda f: f[2] * f[3])
            center = float((biggest[0] + biggest[2] / 2.0) / w)
        samples.append((t, center))
        t += step
    cap.release()
    return samples


def smooth_track(samples, scenes, alpha: float = 0.35,
                 max_step: float = 0.08):
    """EMA smoothing with a max-displacement clamp per sample; the track
    resets instantly to the raw value at scene cuts (a cut means a new
    shot, so the old position is meaningless). Samples with no face keep
    the last known position; leading no-face samples become 0.5 (centre).
    Returns a list of (t, center_x)."""
    if not samples:
        return []
    cut_times = [s for s, _ in scenes] if scenes else []
    track = []
    current = None
    prev_t = None
    for t, raw in samples:
        if raw is not None:
            if current is None:
                current = raw
            elif prev_t is not None and any(prev_t < c <= t for c in cut_times):
                current = raw  # scene cut: snap, do not smooth across it
            else:
                target = current + alpha * (raw - current)
                delta = max(-max_step, min(max_step, target - current))
                current = current + delta
        track.append((t, current if current is not None else 0.5))
        prev_t = t
    return track


def face_track_for_clip(video_path: str, start: float, end: float,
                        scenes=None):
    """Full face track for one clip window, or [] when face tracking is
    unavailable / no face was found (caller uses centre crop)."""
    samples = sample_face_centers(video_path, start, end)
    if not samples or all(c is None for _, c in samples):
        return []
    return smooth_track(samples, scenes or [])


def vertical_filter(center_x: float | None = None,
                    target_w: int = 1080, target_h: int = 1920) -> str:
    """FFmpeg crop+scale filter for one render segment.

    centre crop when center_x is None; otherwise the 9:16 window is
    centred on center_x (0..1 of frame width), clamped to the frame.
    Crop width is ih*9/16; x is expressed with FFmpeg variables so the
    filter works for any input size.
    """
    if center_x is None:
        crop_x = "(iw-ih*9/16)/2"
    else:
        # x = clamp(center_x*iw - crop_w/2, 0, iw - crop_w)
        crop_x = (
            f"min(max({center_x:.4f}*iw-ih*9/32,0),iw-ih*9/16)"
        )
    return f"crop=ih*9/16:ih:{crop_x}:0,scale={target_w}:{target_h}"
