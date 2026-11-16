# MMSN Clipper — backend (FastAPI + FFmpeg + faster-whisper)
# CPU-only. Whisper models download from Hugging Face on first use
# (WHISPER_MODEL=tiny is ~75 MB; small ~490 MB; large-v3 ~3 GB).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# FFmpeg (+ libass for caption burn-in) and fonts for the subtitles.
# libgl1 + libglib2.0-0: scenedetect pulls in non-headless opencv-python,
# which needs libGL at import time. Without them the server still boots
# (cv2/scenedetect imports are lazy and caught), but face tracking and
# scene detection silently degrade to centre-crop / no scene snapping.
# fonts-liberation is metrically compatible with the "Arial" the ASS
# caption styles ask for (Debian has no Arial); DejaVu alone would render
# the captions at different sizes than designed.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY backend ./backend
COPY .env.example ./.env.example

# Writable at runtime (uploads, rendered clips, SQLite DB).
RUN mkdir -p uploads media
ENV DATABASE_URL=sqlite:///./mmsn.db \
    UPLOAD_DIR=./uploads \
    MEDIA_DIR=./media \
    WHISPER_MODEL=tiny \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8

EXPOSE 8000

# NOTE: for a commercial product, use an LGPL FFmpeg build instead of the
# distro one (see THIRD_PARTY_LICENSES.md). The Debian ffmpeg package is
# fine for development / personal use.
# PORT: Render (and Railway) inject a PORT env var (Render default 10000)
# and route traffic + health checks to it. A hardcoded --port 8000 would
# leave the service unreachable ("no open ports detected"). ${PORT:-8000}
# listens on Render's port in prod and on 8000 locally.
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
