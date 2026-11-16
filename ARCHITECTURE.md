# MMSN Clipper — Architecture (Phase 1)

**Project:** AI-powered long-form → Shorts / Reels / TikTok clipper SaaS.
**Status:** Phase 1 scaffold — upload → transcribe → highlight → render pipeline working
locally. Not a finished SaaS: no real auth, no payments, no publishing, no cloud
deployment yet (see §7 "What Phase 1 is NOT").

Full component research (licences, alternatives, verdicts) lives in
[`research.md`](research.md). This file is the final stack decision.

## 1. System overview

```
User ──► Next.js frontend ──► FastAPI backend ──► in-process job queue
                                                        │
                              ┌─────────────────────────┼─────────────────────────┐
                              ▼                         ▼                         ▼
                        FFmpeg render            faster-whisper            SQLite (dev)
                        (cut/crop/captions)      (transcription)           PostgreSQL (prod)
```

A project is one source video. Processing a project runs one pipeline job:
audio extraction → transcription → highlight detection → scene snap → 9:16
reframe → caption burn-in → MP4 export. Clips are stored as files under
`media/` and served by the backend download endpoint.

## 2. Final stack

| Layer | Choice | Reason |
|---|---|---|
| Frontend | **Next.js 14 (App Router) + React 18 + TypeScript + Tailwind CSS 3**, dark theme | One deployable web app, server components where useful, typed API client; Tailwind for fast dark UI. No framework lock-in for the video work — the browser never renders video, the backend does. |
| Backend | **Python 3.12 + FastAPI + Uvicorn** | Typed, async-friendly, OpenAPI docs for free (`/docs`); Python is where the ML/video libs live. |
| Video render/cut/crop/encode | **FFmpeg 8.x directly via subprocess (LGPL build)** | Fastest option; native C, multithreaded. MoviePy was rejected as the render core (3–4× slower, documented memory leaks / zombie subprocesses on long batch jobs — see research §5). |
| Transcription | **faster-whisper** (`word_timestamps=True`, VAD on), model `tiny` locally / `small` or `large-v3-turbo` in prod | ~4× faster than reference Whisper at same accuracy, CPU-usable (int8). WhisperX is the optional upgrade for accurate word alignment. **stable-ts was evaluated 2026-11-16 and rejected for Phase 1**: it genuinely improves word timestamps, but pulls torch 2.15 + torchaudio + CUDA toolkit — gigabytes, incompatible with the light CPU-only build and free-tier hosting (see research §14). |
| Highlight scoring | **Transcript-based scoring (heuristic in Phase 1) + optional LLM** | The LLM only ever sees transcript text — video/audio are never sent to an LLM. Phase 1 ships a deterministic heuristic scorer (hook density, question/emphasis cues, energy proxy, position) so the pipeline works with zero API keys; an LLM scorer (OpenAI-compatible) plugs into the same interface when `OPENAI_API_KEY` is set. Virality score is 0–100 with reasons listed per clip. |
| Diarization | **Optional, off by default** — WhisperX + pyannote.audio | Only useful for multi-speaker content. Weights are Hugging Face-gated and CC-BY-4.0 (community-1); never bundle them. Not installed in Phase 1. |
| Scene detection | **PySceneDetect (headless)** — optional hook | Snaps clip boundaries to real cuts; resets face-tracking at cuts. Optional: the pipeline works without it and logs a warning. |
| 9:16 reframe | **Own module: OpenCV YuNet (MIT model) + smoothing + PySceneDetect cut resets** | Wired in Phase 1 (research §14): the YuNet ONNX model (~233 KB, pinned revision, SHA-256 verified on first download, never committed) samples faces ~2×/sec, largest face wins, EMA smoothing + max-step clamp, instant reset at scene cuts; each scene-cut segment renders with a static crop on its median face position, then segments concat. Falls back to centre crop with a warning whenever the model/detector/no-face is missing. MediaPipe BlazeFace remains the fallback detector. |
| Captions | **Own `.ass` generator + FFmpeg libass burn-in** | Word timestamps → short caption groups (≤4 words, break on punctuation / pauses >0.6 s) → ASS with per-word highlight → `ass` filter burn-in. No third-party auto-caption dependency. |
| Editor waveform | **wavesurfer.js 7.9.0 (BSD-3-Clause)** | Editor page waveform: decodes clip audio, tap-to-seek moves the video playhead, playhead follows playback. Chosen over forking a whole timeline-editor app (research §14). |
| Captions | **Own `.ass` generator + FFmpeg libass burn-in** | Word timestamps → short caption groups (≤4 words, break on punctuation / pauses >0.6 s) → ASS with per-word highlight → `ass` filter burn-in. No third-party auto-caption dependency. |
| Templated graphics | **FFmpeg `drawtext` / ASS first** | Remotion is NOT open source; an automated SaaS is its paid "Automators" tier ($0.01/render, $100/mo min) and only free while the team is ≤3. Deferred; revisit only if React templating is wanted. |
| Database | **SQLite (local dev) / PostgreSQL (production)** via SQLAlchemy 2.0 | Zero-setup local dev; Postgres is the production target. Same models, `DATABASE_URL` switch. |
| Background jobs | **In-process threaded queue (Phase 1)** | `ThreadPoolExecutor` + job rows in the DB. Honest limitation: jobs die with the process, no retries across restarts, no horizontal scaling. Path to Redis + Celery (or RQ/Arq) is documented in §5 — do NOT claim Celery/Redis are running; they are not. |
| Storage | **Local filesystem (`uploads/`, `media/`) in dev; S3-compatible object storage in prod** | Same path abstraction; presigned URLs later. |
| Auth | **Placeholder / dev user in Phase 1; fastapi-users (MIT) chosen for Phase 2** | Real auth (OAuth / email + sessions, per-user projects) is a later phase — fastapi-users 15.0.0 (JWT + OAuth2 + registration, fits our SQLAlchemy models) is the evaluated choice (research §14). Phase 1 runs single-user: every project belongs to a `dev` user row created on first run. Say so honestly — do not ship this to real users as multi-tenant. |

## 3. What needs API keys vs what is free / self-hosted

| Thing | Cost / key |
|---|---|
| FFmpeg, faster-whisper, PySceneDetect, OpenCV, SQLAlchemy, FastAPI, Next.js | Free, self-hosted (open-source licences — see `THIRD_PARTY_LICENSES.md`). |
| Whisper models (tiny → large-v3) | Free (MIT/Apache weights), downloaded from Hugging Face on first run. |
| **YouTube Data API v3** (link-paste metadata only) | Free, quota-capped: 10,000 units/day default; `videos.list` = 1 unit/call. Needs a Google Cloud API key (`YOUTUBE_API_KEY`). **Without the key the link path returns a clear "not configured — upload instead" response; it never fakes metadata.** Quota cannot be bought. |
| LLM highlight scoring (optional) | Paid, BYO key (`OPENAI_API_KEY`, OpenAI-compatible endpoint). Phase 1 works without it (heuristic scorer). |
| Diarization weights (optional, later) | Free but Hugging Face-gated: accept terms + HF token; CC-BY-4.0 attribution for community-1 weights. |
| Hosting / Postgres / S3 (production) | Paid cloud costs, TBD at deploy time. |
| Remotion (deferred) | Paid "Automators" tier if ever adopted. Not used in Phase 1. |

## 4. Ingestion rules (standing decisions — do not change without the user)

1. **User upload is the primary path.** Any video file the user has the right to process.
2. **Link paste = YouTube Data API metadata only.** Extract the video ID from the
   URL (standard, `youtu.be`, Shorts, embed, `/live/`); call `videos.list`
   (1 unit) for title/duration/thumbnail/channel. The API returns **no video
   bytes** — a pasted link alone can never produce a clip. The UI says so.
3. **yt-dlp is an optional, gated path ONLY** — for videos the user owns or has
   explicit permission to use, clearly labelled in the UI and README, with a
   plain-language warning: downloading YouTube videos breaks YouTube's Terms of
   Service, extractors break frequently, and it must never be used for other
   people's copyrighted videos or as the default for arbitrary YouTube links.
   It is **not wired into Phase 1** (no download code path exists yet); if it is
   added later it needs an ownership/permission confirmation step first.
4. **Testing rule:** never test with a real download of a video the user does
   not own — metadata listing only (`--simulate` / `--get-title`), or not at all.

## 5. Background jobs — Phase 1 vs the path forward

- **Phase 1:** `backend/app/jobs.py` — a module-level `ThreadPoolExecutor`
  (2 workers) plus a `jobs` table. `POST /api/projects/{id}/process` inserts a
  job row (`queued` → `running` → `done`/`failed`, with `error` text and
  `progress` 0–100) and submits the pipeline to the pool. `GET /api/jobs/{id}`
  polls it. If the server restarts, `running`/`queued` jobs are marked `failed`
  ("server restarted") on startup — they are never silently re-run.
- **Later:** replace the executor with Redis + Celery (or RQ/Arq): same job
  rows, same `runner.py` entrypoint, workers as separate processes, retries
  with backoff, a dead-letter path, and progress via Redis pub/sub or polling.
  The pipeline itself (`pipeline/runner.py`) is already a plain function of
  `(project_id, db_session_factory)` so it moves unchanged.

## 6. Data model

`users` (id, email, name, created_at) · `projects` (id, user_id, title,
source_type [`upload`|`youtube_link`], source_url, youtube_video_id,
source_path, duration_sec, status, created_at) · `jobs` (id, project_id,
kind, status, progress, error, created_at, finished_at) · `transcripts`
(id, project_id, language, full_text, segments_json, created_at) ·
`highlights` (id, project_id, start_sec, end_sec, score, reasons_json,
title, description, hashtags_json, created_at) · `clips` (id, project_id,
highlight_id, title, path, width, height, duration_sec, file_size_bytes,
status, created_at) · `exports` (id, clip_id, platform, path, status,
created_at). See `backend/app/models.py`.

## 7. What Phase 1 is NOT (honest gaps)

- No real auth / multi-user isolation (single dev user; fastapi-users chosen
  for Phase 2, not wired yet).
- No LLM scoring wired by default (heuristic scorer; LLM is an optional plug-in).
- No diarization, no WhisperX alignment (faster-whisper word timestamps only;
  stable-ts rejected for Phase 1 — torch/CUDA weight, research §14).
- No payments, no publishing to YouTube/TikTok, no scheduling.
- No Redis/Celery, no S3, no Postgres in dev, no Docker yet.
- No automated tests beyond the manual end-to-end run recorded in `TESTING.md`.
- Frontend editor is a skeleton wired to real clip data (trim range + caption
  toggle are "Coming soon" until implemented — they do not pretend to work).
  The wavesurfer.js waveform (tap-to-seek) is real and working.

## 8. Run it (summary — full instructions in `README.md`)

```bash
cp .env.example .env            # edit keys if you have them; works without any
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev   # http://localhost:3000
```
