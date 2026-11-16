# MMSN Clipper — AI long-form → Shorts / Reels / TikTok

Paste a YouTube link for metadata, or **upload your own video** — the pipeline
transcribes it, finds the best moments, and renders vertical 1080×1920 clips
with burned-in word captions.

> **Phase 2 status (2026-11-16): COMPLETE** — real auth (sign-up /
> sign-in, per-user projects), the editor WORKS (trim, caption editing,
> subtitle styles, framing nudge, volume, thumbnails, regenerate — all
> wired to real FFmpeg re-renders, see "Editing a clip" below), and LLM
> highlight scoring is wired with the scorer recorded per highlight
> ("Scored by: LLM / Heuristic", see "Highlight scoring" below). Still
> missing: no payments, no publishing, no cloud deploy yet. Be honest
> about that — see `ARCHITECTURE.md` §7 for the full gap list.

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
# REQUIRED for auth: put a long random SECRET_KEY in .env, e.g.:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs   Health: http://localhost:8000/health
```

### Accounts — sign up / sign in

Every project belongs to the account that created it. There is no shared
or guest account any more (the Phase 1 `dev@localhost` placeholder is
gone — see `TESTING.md` for what happened to its test data).

- **In the browser:** open http://localhost:3000 → you are sent to
  **/login**; tap "Create one" to register (email + password, at least
  8 characters, name optional). You are signed straight in. The header
  shows your email and a **Sign out** button.
- **With the API:** `POST /auth/register` with
  `{"email", "password", "name"?}` → 201; then `POST /auth/jwt/login`
  as an OAuth2 form (`username=<email>&password=<password>`) → 200 with
  `{"access_token", "token_type": "bearer"}`. Send
  `Authorization: Bearer <token>` on every `/api/*` and `/users/*` call.
  `GET /users/me` returns the signed-in user. A wrong password is
  rejected (`LOGIN_BAD_CREDENTIALS`); a missing/invalid token gets 401.
- **Token lifetime:** 7 days by default (`AUTH_TOKEN_LIFETIME_SECONDS`).
  Sign-out discards the token in the browser — the server keeps no token
  list, so a discarded token stays technically valid until it expires.
- **Seed/dev account (local dev only):** if `SEED_EMAIL` and
  `SEED_PASSWORD` are both set, that user is created on startup if
  missing. Otherwise no user is auto-created. Never set these in
  production.

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
4. **Edit** a clip on its editor page (`/clips/{id}`) — see "Editing a clip".

## Editing a clip

Open a clip from the project page. Everything on the editor page changes
the exported MP4 for real — there are no placeholder controls:

- **Trim** — drag the orange region on the waveform (wavesurfer.js Regions
  plugin) or type start/end seconds. Times are seconds into the highlight
  window the clip was cut from; the page shows the new duration before you
  apply. Minimum trimmed length is 2 s.
- **Captions** — every caption group in the current window is listed with
  an editable text field (empty text removes that group's captions).
  Edited words are re-timed proportionally across their group's span —
  an approximation, not a re-transcription (see `ARCHITECTURE.md` §2).
- **Subtitle style** — Karaoke (default, current word highlighted),
  Minimal (small clean white), Bold creator (very large bold), Highlighted
  keywords (long/emphatic words in yellow — a length heuristic, not
  semantic keyword extraction).
- **Framing** — a slider (-1..1) nudges the 9:16 crop window sideways from
  the face-track centre (or from centre when no face is found). There is
  no live preview; the crop moves only in the re-rendered file.
- **Volume** — 0.25×–2×, applied with FFmpeg's `volume` filter.
- **Apply & re-render** — `POST /api/clips/{id}/re-render` starts a
  background job (kind `rerender`, same job table/polling as processing);
  the page polls it and reloads the new version when it finishes. Each
  re-render writes `clip_{id}_v{n}.mp4` — the clip row switches to the new
  file only after the render succeeds, and the old version file is then
  deleted, so a failed re-render never leaves you without a clip.
- **Regenerate** — `POST /api/clips/{id}/regenerate` re-renders the same
  window fresh with the clip's current stored edits (e.g. after a failed
  render, or to pick up pipeline fixes).
- **Thumbnail** — pause the video on the frame you want and tap "Set
  thumbnail from current frame"; `POST /api/clips/{id}/thumbnail?t=…`
  extracts that frame as a JPEG (`GET /api/clips/{id}/thumbnail` serves
  it). All editor endpoints require your JWT and return 404 for anyone
  else's clip.

## Highlight scoring — heuristic by default, LLM optional

Each highlight gets a virality score (0–100) with reasons, and the app
records **which scorer actually produced it** (`scorer: "llm"` or
`"heuristic"`, stored on the highlight and returned by
`GET /api/projects/{id}/highlights`). The project page and the editor's
Clip info show **"Scored by: LLM"** or **"Scored by: Heuristic"** —
the UI never claims an LLM score when the heuristic ran.

- **Without a key (default):** the built-in deterministic heuristic
  scorer runs — hook words, questions, numbers, emphasis, speaking
  pace, position. No API call, $0.
- **With `OPENAI_API_KEY` set:** the pipeline sends **transcript text
  only** (never video or audio) to an OpenAI-compatible
  `/chat/completions` endpoint (`OPENAI_BASE_URL`, default
  `https://api.openai.com/v1`; `OPENAI_MODEL`, default `gpt-4o-mini`)
  and uses the model's picks. If the LLM call fails for any reason
  (bad key, no network, bad response), the pipeline **falls back to the
  heuristic scorer** and the highlight's first reason says
  "LLM scoring unavailable — heuristic score" — so a failed LLM never
  blocks clip creation and never pretends to be an LLM score.
- **Verified with a local mock only** (see `TESTING.md`, Phase 2 step 3):
  a mock `/chat/completions` server proved the LLM path is used when it
  answers and the fallback runs when it errors. **No real OpenAI key
  has been tested** — the first real-key run is still unverified.

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
| `SECRET_KEY` | — (required) | JWT signing secret, ≥ 32 random chars. Server refuses to start without it. `AUTH_SECRET` is accepted as an alias. Never commit a real value. |
| `AUTH_TOKEN_LIFETIME_SECONDS` | `604800` (7 days) | JWT lifetime |
| `SEED_EMAIL` / `SEED_PASSWORD` | — | Dev-only seed account, created on startup only if both are set. Never set in production. |
| `UPLOAD_DIR` / `MEDIA_DIR` | `./uploads` / `./media` | Local file storage |
| `MAX_UPLOAD_MB` | `2048` | Upload size cap |
| `MAX_VIDEO_SECONDS` | `14400` | 4 h source cap |
| `WHISPER_MODEL` | `tiny` | faster-whisper model (`tiny`/`base`/`small`/`large-v3-turbo`) |
| `CLIPS_PER_PROJECT` | `3` | Max clips rendered per run |
| `CLIP_MIN_SECONDS` / `CLIP_MAX_SECONDS` | `15` / `60` | Clip length window |
| `YOUTUBE_API_KEY` | — | YouTube Data API v3 key (optional) |
| `OPENAI_API_KEY` | — | LLM scoring key (optional; see "Highlight scoring") |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint for LLM scoring |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model name sent to the LLM scoring endpoint |

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

Manual end-to-end runs are recorded in `TESTING.md` — Phase 1, Phase 2
step 1 (auth), step 2 (editor), and step 3 (LLM mock scoring + full
re-test, 2026-11-16). Test videos are generated locally with FFmpeg —
no YouTube downloads. There is still no automated test suite in the
repo (the Phase 2 test scripts live in `/tmp`, not in git); that is a
Phase 3 item.

## Deploy

Phase 1 is local-dev only. Production path (not done): Postgres, S3-compatible
storage, Redis + Celery workers, FFmpeg LGPL build on the worker image,
`YOUTUBE_API_KEY` as a server secret, real auth. See `ARCHITECTURE.md` §5/§7.
Auth itself is done (Phase 2, step 1): the only deploy-time auth requirement
is a `SECRET_KEY` — `render.yaml` auto-generates one for the backend
(`generateValue: true`); on Railway set it by hand. Rotating it signs
everyone out. The editor (step 2) and LLM scoring (step 3) need no
extra deploy-time setup beyond the optional `OPENAI_API_KEY` — see
`DEPLOYMENT.md`.

## Licence

This project's own code is MIT (see `LICENSE`, added at first release).
Third-party components keep their own licences — see
`THIRD_PARTY_LICENSES.md`. Nothing in this file is legal advice.
