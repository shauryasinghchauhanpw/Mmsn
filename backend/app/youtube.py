"""YouTube link handling — metadata ONLY, via the official YouTube Data
API v3. The API returns no video bytes and no download URL; a pasted link
alone can never produce a clip. Without YOUTUBE_API_KEY configured the
caller gets a clear error, never fake metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

ISO8601_RE = re.compile(
    r"^PT(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?$")


class YouTubeNotConfiguredError(Exception):
    """YOUTUBE_API_KEY is not set — tell the user to upload instead."""


class YouTubeApiError(Exception):
    pass


def extract_video_id(url: str) -> str | None:
    """Return the 11-char video ID from a YouTube URL, or None.

    Handles: youtube.com/watch?v=... (v first or later in the query),
    youtu.be/..., /shorts/..., /embed/..., /live/..., /v/...,
    music.youtube.com/watch, and a bare 11-char ID. Uses urllib parsing
    instead of regex so query-param order cannot break it.
    """
    if not url:
        return None
    url = url.strip()
    if YOUTUBE_ID_RE.match(url):
        return url  # bare video ID pasted directly
    from urllib.parse import parse_qs, urlparse

    try:
        parsed = urlparse(url if "://" in url else "https://" + url)
    except ValueError:
        return None
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = parsed.path or ""
    if host in ("youtube.com", "music.youtube.com", "m.youtube.com"):
        # /watch?v=ID (v may be first or later in the query string)
        if path == "/watch":
            v = parse_qs(parsed.query).get("v", [None])[0]
            if v and YOUTUBE_ID_RE.match(v):
                return v
        # /shorts/ID, /embed/ID, /live/ID, /v/ID
        for prefix in ("/shorts/", "/embed/", "/live/", "/v/"):
            if path.startswith(prefix):
                candidate = path[len(prefix):].split("/")[0].split("?")[0]
                if YOUTUBE_ID_RE.match(candidate):
                    return candidate
    elif host == "youtu.be":
        candidate = path.lstrip("/").split("/")[0].split("?")[0]
        if YOUTUBE_ID_RE.match(candidate):
            return candidate
    return None


def parse_iso8601_duration(value: str) -> float:
    m = ISO8601_RE.match(value or "")
    if not m:
        return 0.0
    h = int(m.group("h") or 0)
    mins = int(m.group("m") or 0)
    s = float(m.group("s") or 0)
    return h * 3600 + mins * 60 + s


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    channel_title: str
    description: str
    duration_sec: float
    thumbnail_url: str | None


def fetch_metadata(video_id: str, api_key: str) -> VideoMetadata:
    """One videos.list call (1 quota unit). Raises YouTubeApiError on failure."""
    if not api_key:
        raise YouTubeNotConfiguredError(
            "YouTube Data API is not configured on this server. "
            "Upload the video file instead — a link alone cannot be processed.")
    url = "https://www.googleapis.com/youtube/v3/videos"
    params = {"part": "snippet,contentDetails", "id": video_id, "key": api_key}
    try:
        resp = httpx.get(url, params=params, timeout=15)
    except httpx.HTTPError as exc:
        raise YouTubeApiError(f"Could not reach the YouTube API: {exc}") from exc
    if resp.status_code == 403:
        raise YouTubeApiError(
            "YouTube API returned 403 — the key may be invalid or the daily "
            "quota (10,000 units) may be exhausted.")
    if resp.status_code != 200:
        raise YouTubeApiError(
            f"YouTube API returned HTTP {resp.status_code}: {resp.text[:200]}")
    items = resp.json().get("items", [])
    if not items:
        raise YouTubeApiError(
            "No such video found (it may be private, deleted, or the ID is wrong).")
    item = items[0]
    snip = item.get("snippet", {})
    thumbs = snip.get("thumbnails", {})
    thumb = (thumbs.get("maxres") or thumbs.get("high")
             or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    return VideoMetadata(
        video_id=video_id,
        title=snip.get("title", ""),
        channel_title=snip.get("channelTitle", ""),
        description=snip.get("description", ""),
        duration_sec=parse_iso8601_duration(
            item.get("contentDetails", {}).get("duration", "PT0S")),
        thumbnail_url=thumb,
    )
