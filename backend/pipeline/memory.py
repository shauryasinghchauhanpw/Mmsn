"""Best-effort memory trimming for the job runner.

Face tracking + scene detection decode video frames in-process and
leave the backend holding ~150-200 MB of heap that the render step
does not need. On a small host (Render free, 512 MB) that held memory
is the difference between a job fitting or being OOM-killed while
FFmpeg renders next to it. Calling ``gc.collect()`` + glibc
``malloc_trim`` after the heavy in-process steps hands ~50 MB back to
the OS (measured 2026-11-16: 221 MB -> 172 MB current RSS).

This is strictly best-effort: it never raises, never changes results,
and silently does nothing where it cannot work (non-glibc platforms,
missing ctypes). It is not a substitute for having enough RAM — only
a way to give the render child more room on a tight host.
"""
from __future__ import annotations

import ctypes
import gc
import logging

logger = logging.getLogger(__name__)


def trim_memory() -> None:
    """Release freed heap pages back to the OS. Never raises."""
    try:
        gc.collect()
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception as exc:  # noqa: BLE001 — best-effort by design
        logger.debug("trim_memory skipped: %s", exc)
