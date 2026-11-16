# MMSN Clipper — backend (FastAPI + FFmpeg + faster-whisper)
# CPU-only. Whisper models download from Hugging Face on first use
# (WHISPER_MODEL=tiny is ~75 MB; small ~490 MB; large-v3 ~3 GB).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# FFmpeg (+ libass for caption burn-in) and a font for the subtitles.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
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
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
