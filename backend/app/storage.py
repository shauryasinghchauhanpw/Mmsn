"""Storage abstraction — local filesystem (default) + S3-compatible.

Phase 3 (production hardening). Two backends behind one interface,
selected ONLY by ``STORAGE_BACKEND`` (see ``config.py``):

* ``local`` (default) — files under ``UPLOAD_DIR`` / ``MEDIA_DIR``,
  exactly as in Phase 1/2. A *ref* is the filesystem path itself
  (e.g. ``./uploads/<uuid>.mp4``), so nothing stored in the DB changes
  and the local flow is byte-for-byte the old behaviour.
* ``s3`` — S3-compatible object storage via boto3. A *ref* is
  ``s3://<bucket>/<key>``. Downloads are served as presigned URLs
  (the browser fetches straight from the bucket); anything that needs
  a real file on disk (FFmpeg, ffprobe) gets one through
  ``local_path()``, which downloads the object once into a local
  cache directory and reuses it. Refs are content-addressed
  (uuid / versioned filenames), so a cached copy can never go stale.

Local dev needs nothing extra: S3 is off unless ``STORAGE_BACKEND=s3``,
and the S3 backend is only constructed when selected — boto3 is never
imported in local mode.

What is wired through this module (main.py): upload store, clip
download, thumbnail set/get. The pipeline itself (runner.py /
rerender.py) still reads ``project.source_path`` / ``clip.path``
directly — in S3 mode those refs are materialised to the local cache
before the job runs and published back afterwards by the job wrapper
(see ``jobs.execute_job``), so the pipeline code did not have to
change. That wrapper is the S3 seam for background jobs; if a new
code path reads a stored file, route it through ``local_path()``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil

from .config import settings

logger = logging.getLogger(__name__)

# Local cache for S3 objects that must exist as files (FFmpeg input,
# ffprobe, thumbnails). Under MEDIA_DIR so it lives next to the other
# media; hidden (dot-prefixed) so it is never served or listed.
S3_CACHE_DIRNAME = ".s3cache"


def is_s3_ref(ref: str | None) -> bool:
    """True when a stored ref points at an S3 object, not a local file."""
    return bool(ref) and ref.startswith("s3://")


def parse_s3_ref(ref: str) -> tuple[str, str]:
    """Split ``s3://bucket/key`` into (bucket, key)."""
    rest = ref[len("s3://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


def _ref_sidecar_path(cached_path: str) -> str:
    return cached_path + ".ref"


def original_ref_for_cached(cached_path: str) -> str | None:
    """The S3 ref a cached file was downloaded from, from its ``.ref``
    sidecar — or None when the file is not a cached S3 object. This is
    how a job interrupted by a worker kill can resolve a DB row that
    still points at a cache path back to its S3 ref (see jobs.py)."""
    try:
        with open(_ref_sidecar_path(cached_path), "r",
                  encoding="utf-8") as fh:
            ref = fh.read().strip()
        return ref if is_s3_ref(ref) else None
    except OSError:
        return None


class LocalStorage:
    """Local-filesystem backend — the Phase 1/2 behaviour, unchanged."""

    def make_ref(self, kind: str, name: str) -> str:
        """Destination path for a new file. ``kind`` is ``"upload"`` or
        ``"media"``; ``name`` may contain subdirectories
        (e.g. ``project_3/clip_5.mp4``)."""
        base = settings.upload_dir if kind == "upload" else settings.media_dir
        return os.path.join(base, name)

    def put_file(self, local_path: str, ref: str) -> str:
        """Store the file at ``local_path`` as ``ref``. Moves it when
        possible (same filesystem), copies otherwise. Returns the ref."""
        if os.path.abspath(local_path) == os.path.abspath(ref):
            return ref
        os.makedirs(os.path.dirname(ref) or ".", exist_ok=True)
        try:
            shutil.move(local_path, ref)
        except OSError:
            shutil.copyfile(local_path, ref)
            os.remove(local_path)
        return ref

    def exists(self, ref: str) -> bool:
        return os.path.exists(ref)

    def delete(self, ref: str) -> None:
        try:
            if os.path.exists(ref):
                os.remove(ref)
        except OSError:
            logger.warning("Could not delete local file %s", ref)

    def size(self, ref: str) -> int | None:
        try:
            return os.path.getsize(ref)
        except OSError:
            return None

    def local_path(self, ref: str) -> str:
        """A local file already is a local path."""
        return ref

    def download_url(self, ref: str, filename: str | None = None,
                     expires_in: int | None = None) -> str | None:
        """Local files are served by the backend itself (FileResponse),
        so there is no presigned URL — callers fall back to that."""
        return None


class S3Storage:
    """S3-compatible backend (boto3). Constructed only when
    ``STORAGE_BACKEND=s3``; boto3 is imported lazily so local mode
    never needs it installed."""

    def __init__(self) -> None:
        if not settings.s3_bucket:
            raise RuntimeError(
                "STORAGE_BACKEND=s3 but S3_BUCKET is not set. Set "
                "S3_BUCKET (and S3_ACCESS_KEY/S3_SECRET_KEY, or rely on "
                "the environment/IAM credential chain) — see .env.example.")
        try:
            import boto3  # noqa: PLC0415  (lazy: only needed in S3 mode)
        except ImportError as exc:
            raise RuntimeError(
                "STORAGE_BACKEND=s3 but boto3 is not installed. Run "
                "pip install -r backend/requirements.txt.") from exc
        session_kwargs: dict = {"region_name": settings.s3_region}
        if settings.s3_access_key:
            session_kwargs["aws_access_key_id"] = settings.s3_access_key
        if settings.s3_secret_key:
            session_kwargs["aws_secret_access_key"] = settings.s3_secret_key
        self._s3 = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint_url or None,
            **session_kwargs)
        self.bucket = settings.s3_bucket

    # -- refs ------------------------------------------------------------
    def make_ref(self, kind: str, name: str) -> str:
        prefix = "uploads" if kind == "upload" else "media"
        key = f"{prefix}/{name}".replace(os.sep, "/")
        return f"s3://{self.bucket}/{key}"

    # -- writes ----------------------------------------------------------
    def put_file(self, local_path: str, ref: str) -> str:
        """Upload the file at ``local_path`` to ``ref``. The local file
        is left in place — the caller owns temp-file cleanup."""
        _, key = parse_s3_ref(ref)
        self._s3.upload_file(local_path, self.bucket, key)
        return ref

    def delete(self, ref: str) -> None:
        _, key = parse_s3_ref(ref)
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            logger.warning("Could not delete S3 object %s", ref)

    # -- reads -----------------------------------------------------------
    def exists(self, ref: str) -> bool:
        from botocore.exceptions import ClientError  # lazy, S3-only
        _, key = parse_s3_ref(ref)
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get(
                    "HTTPStatusCode") == 404:
                return False
            raise

    def size(self, ref: str) -> int | None:
        from botocore.exceptions import ClientError  # lazy, S3-only
        _, key = parse_s3_ref(ref)
        try:
            return self._s3.head_object(Bucket=self.bucket, Key=key)[
                "ContentLength"]
        except ClientError:
            return None

    def local_path(self, ref: str) -> str:
        """Download the object once into the local cache and return the
        cached path. Refs are content-addressed (uuid/versioned names),
        so a cached copy is never stale; a re-upload under the same key
        would need the cache entry removed first (it never happens —
        re-renders write a new versioned filename)."""
        _, key = parse_s3_ref(ref)
        cache_dir = os.path.join(settings.media_dir, S3_CACHE_DIRNAME)
        os.makedirs(cache_dir, exist_ok=True)
        digest = hashlib.sha256(ref.encode()).hexdigest()[:16]
        cached = os.path.join(
            cache_dir, f"{digest}_{os.path.basename(key)}")
        if not os.path.exists(cached):
            self._s3.download_file(self.bucket, key, cached)
        # Sidecar recording which ref this cached file came from, so a
        # job interrupted mid-run can resolve the row back to S3 (see
        # jobs.py / original_ref_for_cached).
        try:
            with open(_ref_sidecar_path(cached), "w",
                      encoding="utf-8") as fh:
                fh.write(ref)
        except OSError:
            logger.warning("Could not write S3 cache sidecar for %s", ref)
        return cached

    def download_url(self, ref: str, filename: str | None = None,
                     expires_in: int | None = None) -> str | None:
        """Presigned GET URL; the browser downloads straight from the
        bucket. ``filename`` sets the download name via
        Content-Disposition."""
        _, key = parse_s3_ref(ref)
        params: dict = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{filename}"')
        return self._s3.generate_presigned_url(
            "get_object", Params=params,
            ExpiresIn=expires_in or settings.s3_presigned_expiry_seconds)


_storage: LocalStorage | S3Storage | None = None


def get_storage() -> LocalStorage | S3Storage:
    """The configured storage backend (singleton). Local by default;
    S3 only when ``STORAGE_BACKEND=s3``."""
    global _storage
    if _storage is None:
        _storage = S3Storage() if settings.use_s3 else LocalStorage()
    return _storage


def reset_storage() -> None:
    """Drop the cached backend (tests only — lets a changed env take
    effect without restarting the process)."""
    global _storage
    _storage = None
