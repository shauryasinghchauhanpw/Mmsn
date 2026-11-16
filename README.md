# MMSN Clipper — AI long-form → Shorts / Reels / TikTok

Paste a YouTube link for metadata, or **upload your own video** — the pipeline
transcribes it, finds the best moments, and renders vertical 1080×1920 clips
with burned-in word captions.

> **Phase 1 status:** working local scaffold. Upload → transcribe → highlight →
> render works end-to-end on this machine (see `TESTING.md`). No real auth yet
> (single dev user), no payments, no publishing. Be honest about that — see
> `ARCHITECTURE.md` §7 for the full gap list.

## Quick start

### Prerequisites

- Python 3.11+ (3.12 tested), Node.js 20+, **FFmpeg 8.x on PATH**
  (check: `ffmpeg -version`; the `ass` subtitle filter with libass must be
  present — check: `ffmpeg -h filter=ass`).
- ~2 GB free disk for the Python venv + the Whisper `tiny` model (~75 MB;
  `small` is ~490 MB, `large-v3` ~3 GB).

### Backend

```bash
cp .env.example .env        # optional: add YOUTUBE_API_KEY / OPENAI_API_KEY
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs   Health: http://localhost:8000/health
```

### Frontend

```bash
cd frontend
npm install
npm run dev                 # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`
if the backend runs elsewhere.

## How it works

1. **Upload** a video (`POST /api/projects/upload`, max 2 GB, mp4/mov/mkv/webm)
   or **paste a YouTube link** (`POST /api/projects/youtube`) — the link path
   returns title/duration/thumbnail/channel via the YouTube Data API and
   *cannot* fetch video bytes.
2. **Process** (`POST /api/projects/{id}/process`): FFmpeg extracts 16 kHz mono
   audio → faster-whisper transcribes with word timestamps → the highlight
   scorer ranks moments 0–100 with reasons → top clips are cut, centre-cropped
   to 1080×1920, captioned (ASS burn-in) and exported as H.264/AAC MP4, 30 fps.
3. **Download** clips from the dashboard or `GET /api/clips/{id}/download`.

## API keys needed (and costs)

| Key | Needed for | Cost |
|---|---|---|
| None | Upload → transcribe → clips (heuristic scoring) | $0 — everything local & open source |
| `YOUTUBE_API_KEY` | Pasting a YouTube link and getting its metadata | Free, quota-capped (10,000 units/day; `videos.list` = 1 unit). Quota cannot be bought. |
| `OPENAI_API_KEY` (optional) | LLM highlight scoring instead of the built-in heuristic | Pay-per-use, your OpenAI bill. Without it the heuristic scorer runs. |
| `HF_TOKEN` (optional, later) | Speaker diarization weights (gated on Hugging Face) | Free, but you must accept the terms on HF. Not used in Phase 1. |

### How to get a YouTube Data API key

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a
   project → **APIs & Services → Library** → enable **YouTube Data API v3**.
2. **APIs & Services → Credentials → Create Credentials → API key**.
3. Restrict the key (API restrictions → YouTube Data API v3; application
   restrictions → IP addresses of your server).
4. Put it in `.env` as `YOUTUBE_API_KEY=...`. Without it, the link endpoint
   returns HTTP 501 `youtube_api_not_configured` with the message
   "upload the video instead" — it never fakes metadata.

## Ingestion rules — read this before pasting links

- **Upload is the primary path.** Upload videos you have the right to process.
- **A pasted YouTube link only fetches metadata** (title, duration, thumbnail,
  channel) via the official YouTube Data API. It does **not** download the
  video, and a link alone can never produce a clip.
- **yt-dlp (downloading YouTube videos) is NOT wired into Phase 1.**
  If it is ever added, it will be an optional, clearly-labelled path **only for
  videos you own or have explicit permission to use**, with an
  ownership/permission confirmation first. Plain-language warning:
  **downloading YouTube videos breaks YouTube's Terms of Service**, the
  downloaders break frequently when YouTube changes things, and it must never
  be used for other people's copyrighted videos or as the default for
  arbitrary YouTube links. Using it on someone else's video can also be
  copyright infringement. Upload stays the primary path.

## Configuration

See `.env.example` — every variable is documented there. No real secrets
belong in the repo: `.env` is gitignored and `.env.example` contains only
placeholders.

| Variable | Default | What it does |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./mmsn.db` | SQLAlchemy URL (Postgres in prod) |
| `UPLOAD_DIR` / `MEDIA_DIR` | `./uploads` / `./media` | Local file storage |
| `MAX_UPLOAD_MB` | `2048` | Upload size cap |
| `MAX_VIDEO_SECONDS` | `14400` | 4 h source cap |
| `WHISPER_MODEL` | `tiny` | faster-whisper model (`tiny`/`base`/`small`/`large-v3-turbo`) |
| `CLIPS_PER_PROJECT` | `3` | Max clips rendered per run |
| `CLIP_MIN_SECONDS` / `CLIP_MAX_SECONDS` | `15` / `60` | Clip length window |
| `YOUTUBE_API_KEY` | — | YouTube Data API v3 key (optional) |
| `OPENAI_API_KEY` | — | LLM scoring key (optional) |

## Project layout

```
backend/app/        FastAPI app: routes, config, DB, jobs
backend/pipeline/   audio, transcribe, highlights, scenes, reframe, captions, render, runner
backend/requirements.txt
frontend/           Next.js 14 + TypeScript + Tailwind (dark)
ARCHITECTURE.md     Final stack + decisions
research.md         Component research (licences, alternatives)
THIRD_PARTY_LICENSES.md
TESTING.md           What was actually tested, pass/fail
```

## Testing

Manual end-to-end run is recorded in `TESTING.md` (test video generated
locally with FFmpeg — no YouTube downloads). There is no automated test suite
yet (Phase 2).

## Deploy

Phase 1 is local-dev only. Production path (not done): Postgres, S3-compatible
storage, Redis + Celery workers, FFmpeg LGPL build on the worker image,
`YOUTUBE_API_KEY` as a server secret, real auth. See `ARCHITECTURE.md` §5/§7.

## Licence

This project's own code is MIT (see `LICENSE`, added at first release).
Third-party components keep their own licences — see
`THIRD_PARTY_LICENSES.md`. Nothing in this file is legal advice.
