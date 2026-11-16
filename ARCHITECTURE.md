# MMSN Clipper — Architecture (Phase 1)

**Project:** AI-powered long-form → Shorts / Reels / TikTok clipper SaaS.
**Status:** Phase 1 scaffold — upload → transcribe → highlight → render pipeline working
locally — plus Phase 2 complete (2026-11-16): real auth (step 1), working
video editor (step 2), and LLM scoring wired with the scorer recorded per
highlight and shown in the UI (step 3) — plus Phase 3 complete
(2026-11-16): automated pytest suite in the repo (100 tests), Postgres +
S3-compatible storage + Redis/Celery workers (config-driven, dev
fallbacks intact), and deploy fixes (Render `PORT`, DB/uploads on the
persistent disk) — plus the free-tier reconfiguration (2026-11-16):
the default deployment is $0 (Oracle Always Free VM + Vercel Hobby;
Render free is demo-only — see `FREE_TIER.md` and `DEPLOYMENT.md`).
Not a finished SaaS: no payments, no publishing, no live cloud
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
| Highlight scoring | **Transcript-based scoring: heuristic by default, optional LLM** | The LLM only ever sees transcript text — video/audio are never sent to an LLM. The deterministic heuristic scorer (hook density, question/emphasis cues, energy proxy, position) runs with zero API keys; when `OPENAI_API_KEY` is set, `score_highlights_llm()` (OpenAI-compatible `/chat/completions`) runs instead and falls back to the heuristic on any failure, saying so in the reasons. `detect_highlights()` returns `(highlights, scorer)` and `runner.py` stores `scorer` (`"llm"` \| `"heuristic"`) on each `Highlight` — the UI shows exactly that value, so it can never claim LLM scoring when the heuristic ran. Verified with a local mock server only (see §10); no real OpenAI key has been tested. Virality score is 0–100 with reasons listed per clip. |
| Diarization | **Optional, off by default** — WhisperX + pyannote.audio | Only useful for multi-speaker content. Weights are Hugging Face-gated and CC-BY-4.0 (community-1); never bundle them. Not installed in Phase 1. |
| Scene detection | **PySceneDetect (headless)** — optional hook | Snaps clip boundaries to real cuts; resets face-tracking at cuts. Optional: the pipeline works without it and logs a warning. |
| 9:16 reframe | **Own module: OpenCV YuNet (MIT model) + smoothing + PySceneDetect cut resets** | Wired in Phase 1 (research §14): the YuNet ONNX model (~233 KB, pinned revision, SHA-256 verified on first download, never committed) samples faces ~2×/sec, largest face wins, EMA smoothing + max-step clamp, instant reset at scene cuts; each scene-cut segment renders with a static crop on its median face position, then segments concat. Falls back to centre crop with a warning whenever the model/detector/no-face is missing. MediaPipe BlazeFace remains the fallback detector. |
| Captions | **Own `.ass` generator + FFmpeg libass burn-in** | Word timestamps → short caption groups (≤4 words, break on punctuation / pauses >0.6 s) → ASS with per-word highlight → `ass` filter burn-in. No third-party auto-caption dependency. Phase 2, step 2 added 4 real style presets (`karaoke` default, `minimal`, `bold`, `highlighted`) — see §9. |
| Editor waveform | **wavesurfer.js 7.9.0 (BSD-3-Clause)** | Editor page waveform: decodes clip audio, tap-to-seek moves the video playhead, playhead follows playback. Chosen over forking a whole timeline-editor app (research §14). Phase 2, step 2 added the bundled **Regions plugin** for the draggable trim region (no new dependency — it ships inside wavesurfer.js 7.9.0). |
| Editor re-render | **Background job reusing the jobs table (`kind="rerender"`) + `pipeline/rerender.py`** | The editor POSTs edit parameters; a worker re-renders the clip from the source video with the same `render_clip()` used for first-time renders, versioned output (`clip_{id}_v{n}.mp4`), clip row switched only on success. See §9. |
| Captions | **Own `.ass` generator + FFmpeg libass burn-in** | Word timestamps → short caption groups (≤4 words, break on punctuation / pauses >0.6 s) → ASS with per-word highlight → `ass` filter burn-in. No third-party auto-caption dependency. |
| Templated graphics | **FFmpeg `drawtext` / ASS first** | Remotion is NOT open source; an automated SaaS is its paid "Automators" tier ($0.01/render, $100/mo min) and only free while the team is ≤3. Deferred; revisit only if React templating is wanted. |
| Database | **SQLite (local dev) / PostgreSQL (production)** via SQLAlchemy 2.0 | Zero-setup local dev; Postgres is the production target. Same models, `DATABASE_URL` switch (Phase 3: `postgresql+psycopg://`, bare `postgres://` normalised; see §5b). |
| Background jobs | **In-process threaded queue (default) / Celery + Redis (Phase 3, opt-in)** | `ThreadPoolExecutor` + job rows in the DB. Honest limitation in-process: jobs die with the process, no retries across restarts, no horizontal scaling. With `CELERY_BROKER_URL` set, the same job rows and the same `runner.py` entrypoint run on Celery workers instead, with startup recovery (see §5). Do NOT claim Celery/Redis are running unless the broker URL is set — they are off by default. |
| Storage | **Local filesystem (`uploads/`, `media/`) in dev; S3-compatible object storage in prod** | `backend/app/storage.py` (Phase 3): one interface, `STORAGE_BACKEND` switch; S3 mode serves presigned download URLs and caches objects locally for FFmpeg (see §5b). |
| Auth | **fastapi-users 15.0.0, JWT bearer (Phase 2, step 1 — DONE 2026-11-16)** | Sign-up `POST /auth/register`, sign-in `POST /auth/jwt/login` (JWT, HS256, 7-day lifetime, secret from `SECRET_KEY`), `GET /users/me`, logout = client-side token discard. Every `/api/*` route requires a valid token and is scoped to the signed-in user's own projects — another user's project/job/clip returns 404, never leaking existence. Passwords: Argon2/bcrypt via fastapi-users' password helper, min 8 chars. The Phase 1 placeholder dev user is gone; no request path auto-creates a user. Optional `SEED_EMAIL`/`SEED_PASSWORD` startup seed (dev only). Because fastapi-users 15 ships an async-only SQLAlchemy adapter and this app is sync, `backend/app/auth.py` has a thin sync adapter over the existing session (documented there). |

## 3. What needs API keys vs what is free / self-hosted

| Thing | Cost / key |
|---|---|
| FFmpeg, faster-whisper, PySceneDetect, OpenCV, SQLAlchemy, FastAPI, Next.js | Free, self-hosted (open-source licences — see `THIRD_PARTY_LICENSES.md`). |
| Whisper models (tiny → large-v3) | Free (MIT/Apache weights), downloaded from Hugging Face on first run. |
| **YouTube Data API v3** (link-paste metadata only) | Free, quota-capped: 10,000 units/day default; `videos.list` = 1 unit/call. Needs a Google Cloud API key (`YOUTUBE_API_KEY`). **Without the key the link path returns a clear "not configured — upload instead" response; it never fakes metadata.** Quota cannot be bought. |
| LLM highlight scoring (optional) | Paid, BYO key (`OPENAI_API_KEY`, OpenAI-compatible endpoint). Phase 1 works without it (heuristic scorer). |
| Diarization weights (optional, later) | Free but Hugging Face-gated: accept terms + HF token; CC-BY-4.0 attribution for community-1 weights. |
| Hosting / Postgres / S3 (production) | **$0 default** (see `FREE_TIER.md` / `DEPLOYMENT.md`): backend + Postgres + files on one Oracle Cloud Always Free VM (`docker-compose.yml`), frontend free on Vercel Hobby. Render free is demo-only (512 MB RAM cannot run Whisper). Paid upgrades are optional, never the default: Render Standard backend + disk ~$25/mo + ~$2.50/mo, bigger VPS from ~$5/mo, R2/S3 storage, OpenAI key (LLM scoring only). |
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

## 5. Background jobs — Phase 1 vs Phase 3 (Celery)

- **Phase 1/2:** `backend/app/jobs.py` — a module-level `ThreadPoolExecutor`
  (2 workers) plus a `jobs` table. `POST /api/projects/{id}/process` inserts a
  job row (`queued` → `running` → `done`/`failed`, with `error` text and
  `progress` 0–100) and submits the pipeline to the pool. `GET /api/jobs/{id}`
  polls it. If the server restarts, `running`/`queued` jobs are marked `failed`
  ("server restarted") on startup — they are never silently re-run.
- **Phase 3 (DONE 2026-11-16): Celery + Redis, opt-in via `CELERY_BROKER_URL`
  (or `REDIS_URL` as an alias).** When the broker URL is unset, the
  in-process queue above is still the behaviour — nothing changes for
  local dev. When it is set, `jobs.submit_job()` sends the job to a
  Celery worker (`backend/app/celery_app.py`, tasks `mmsn.run_pipeline`
  / `mmsn.run_rerender`) instead of the pool; the pipeline entrypoints
  (`pipeline/runner.py`, `pipeline/rerender.py`) are unchanged — both
  dispatch modes call the same `jobs.execute_job()` wrapper, which
  claims the job row, runs the function, and records a crash as
  `failed`. Run a worker from the repo root with
  `celery -A backend.app.celery_app worker --loglevel=info --concurrency=1`
  (concurrency 1: one job saturates the CPU with Whisper + FFmpeg;
  scale with more worker processes, not threads). The worker needs
  the same environment as the backend (`DATABASE_URL`, storage vars,
  Whisper model, FFmpeg on PATH); `SECRET_KEY` is not needed by the
  worker. `CELERY_RESULT_BACKEND` defaults to the broker URL and is
  optional — job state lives in the DB, polled via `GET /api/jobs/{id}`,
  not in Celery results. No task time limit is set on purpose: a long
  video must not be killed by a default.
- **Recovery (Celery mode) — job rows are the source of truth.** The
  API process holds no job state, so a backend restart does not touch
  running jobs: workers are separate processes and keep going. On
  startup the backend re-queues every job row still `queued`/`running`
  (`jobs.recover_interrupted_jobs()`) in case the broker lost the
  message (e.g. a Redis restart without persistence). Tasks use
  `acks_late=True` + `reject_on_worker_lost=True`, so a worker killed
  mid-task has its task redelivered; the task skips itself if the row
  is already `done`/`failed`, so a redelivery re-runs the pipeline
  from scratch. That re-run is **not idempotent**: a crashed attempt
  may have left partial highlight/clip rows behind (duplicate clips
  from the crashed run stay in the DB; re-processing creates a fresh
  set). There is no automatic retry on a *failed* job — an exception
  marks the row `failed`, and re-processing is a deliberate user
  action. In-process mode keeps the old behaviour (stale jobs marked
  `failed` on startup) — the two modes never mix.
- **Verification status (honest, 2026-11-16, this VM):** Postgres —
  verified against a real local PostgreSQL server (`pgserver`):
  `postgres://` normalisation, `create_all`, CRUD on all 7 tables,
  and the ALTER TABLE migration path (dropped columns re-added, rows
  kept). Redis/Celery — verified end-to-end against a real
  `redis-server`: register → login → upload → process dispatched to a
  Celery worker → job `done`, 2 clips, byte-identical downloads; and
  startup recovery re-queued a job stuck in `queued` after a backend
  restart, which the worker then completed. S3 — verified end-to-end
  against a moto mock S3 server (NOT real AWS S3): upload → process
  (materialise/publish wrapper) → presigned downloads → thumbnail,
  plus a re-render publishing a new versioned object and deleting the
  old one. Real AWS S3 / R2 / MinIO, a live Oracle VM / Vercel deploy, a
  live Render deploy, and Docker builds are still unverified — the first
  real deploy is the test for those. (Free-tier decision, 2026-11-16:
  the default deploy is the Oracle Always Free VM + Vercel, both $0 —
  see `FREE_TIER.md` and `DEPLOYMENT.md`. Render free is demo-only.)

## 5b. Storage — local files (dev) vs S3-compatible (Phase 3)

- **Local (default):** `uploads/` + `media/` on disk, refs are the
  file paths, exactly as in Phase 1/2. Nothing in the DB changes.
- **S3 (`STORAGE_BACKEND=s3`):** `backend/app/storage.py` —
  `LocalStorage` / `S3Storage` behind one interface. Refs become
  `s3://<bucket>/<key>` (`uploads/<uuid>.<ext>`,
  `media/project_<id>/clip_<id>.mp4`). Uploads go through
  `storage.put_file()`; clip/thumbnail downloads are 302 redirects
  to presigned GET URLs (valid `S3_PRESIGNED_EXPIRY_SECONDS`, default
  3600 s); anything needing a real file (FFmpeg, ffprobe) uses
  `storage.local_path()`, which downloads the object once into
  `media/.s3cache/` and reuses it (refs are content-addressed, so a
  cached copy cannot go stale). Credentials come from
  `S3_ACCESS_KEY`/`S3_SECRET_KEY`, or boto3's default chain (env,
  `~/.aws`, IAM role) when those are blank; `S3_ENDPOINT_URL` blank
  means AWS S3 itself, set it for MinIO/R2/etc.
- **The pipeline seam:** `runner.py` / `rerender.py` still read
  `project.source_path` / `clip.path` from the DB. In S3 mode the job
  wrapper (`jobs.execute_job`) materialises those refs to the local
  cache before the run and publishes newly rendered clips back to S3
  afterwards, restoring the `s3://` refs on the rows. The original ref
  is recorded in a `.ref` sidecar next to each cached file, so a
  worker killed mid-job leaves rows pointing at cache paths that the
  next attempt resolves back to S3 instead of failing. Local mode
  skips all of this. If a new code path reads a stored file, route it
  through `storage.local_path()` — do not assume a DB path is local.
- **Postgres (Phase 3):** same models on SQLite and Postgres via
  `DATABASE_URL` (`postgresql+psycopg://…`; a bare `postgres://` URL
  is normalised to that form in `database.py` — psycopg v3 is the
  driver, psycopg2 is not a dependency). The models use only portable
  types (no SQLite pragmas, JSON in Text columns) and the migration
  DDL is valid on both dialects. Engine: `pool_pre_ping=True` on
  Postgres so idle-timeout connections recycle instead of failing a
  request. In production the Postgres URL comes from the deployment:
  `docker-compose.yml` wires the `db` container into the backend
  (Option A, Oracle VM), or a free Neon Postgres URL is pasted in
  (Option B). The old `render.yaml` managed Postgres service
  (`mmsn-db`) was removed in the free-tier change (2026-11-16) —
  Render's free Postgres expires after 30 days. Deleting the Postgres
  wiring falls back to SQLite (the code default).

## 6. Data model

`users` (id, email, name, hashed_password, is_active, is_superuser,
is_verified, created_at) · `projects` (id, user_id, title,
source_type [`upload`|`youtube_link`], source_url, youtube_video_id,
source_path, duration_sec, status, created_at) · `jobs` (id, project_id,
kind, status, progress, error, created_at, finished_at) · `transcripts`
(id, project_id, language, full_text, segments_json, created_at) ·
`highlights` (id, project_id, start_sec, end_sec, score, scorer,
reasons_json, title, description, hashtags_json, created_at) —
`scorer` is `"llm"` only when an LLM response actually produced the
highlight, otherwise `"heuristic"` (Phase 2, step 3; added by the
migration in `backend/app/database.py`, existing rows default to
`"heuristic"`) · `clips` (id, project_id,
highlight_id, title, path, width, height, duration_sec, file_size_bytes,
status, created_at, edit_params_json, version, thumbnail_path) —
`edit_params_json` is the clip's current editor parameters (trim, style,
framing_offset, volume, caption_overrides), `version` counts renders
(starts at 1, +1 per re-render), `thumbnail_path` is the picked JPEG
frame or NULL · `jobs` (id, project_id, clip_id, kind, status, progress,
error, created_at, finished_at) — `clip_id` is set only for
kind="rerender" jobs · `exports` (id, clip_id, platform, path, status,
created_at). See `backend/app/models.py`. The Phase 2, step 2 columns
are added to existing dev databases by the migration in
`backend/app/database.py` (`_TABLE_COLUMNS`, ALTER TABLE, add-only).

## 7. What Phase 1 is NOT (honest gaps)

- ~~No real auth / multi-user isolation (single dev user; fastapi-users chosen
  for Phase 2, not wired yet).~~ **DONE in Phase 2, step 1 (2026-11-16)** —
  fastapi-users 15.0.0 JWT auth, per-user project isolation, verified live
  (see `TESTING.md`). Still missing within auth: password reset, email
  verification (`is_verified` exists but nothing sets it), OAuth
  (Google/GitHub), refresh tokens, and token revocation — logout is
  client-side token discard, so a discarded token stays valid until it
  expires (max 7 days).
- ~~No LLM scoring wired by default (heuristic scorer; LLM is an optional plug-in).~~ **DONE in Phase 2, step 3 (2026-11-16)** —
  the LLM scorer is wired (`score_highlights_llm()` via
  `detect_highlights()`, transcript text only), the scorer that
  actually ran is recorded per highlight and shown in the UI, and the
  heuristic fallback is labelled honestly. Verified against a local
  mock `/chat/completions` server (see `TESTING.md`); **a real OpenAI
  key has never been tested** — the first real-key run is still
  unverified, and there is no per-model/per-prompt configuration UI.
- No diarization, no WhisperX alignment (faster-whisper word timestamps only;
  stable-ts rejected for Phase 1 — torch/CUDA weight, research §14).
- No payments, no publishing to YouTube/TikTok, no scheduling.
- ~~No Redis/Celery, no S3, no Postgres in dev, no Docker yet.~~
  **DONE in Phase 3 (2026-11-16, config-gated — all off by default):**
  Postgres via `DATABASE_URL` (same models, psycopg v3 driver — in
  production from the `db` container in `docker-compose.yml`, or a
  free Neon URL; the old managed `mmsn-db` service in `render.yaml`
  was removed in the free-tier change because Render's free Postgres
  expires after 30 days); S3-compatible storage via
  `STORAGE_BACKEND=s3` (`backend/app/storage.py`, presigned downloads,
  local cache for FFmpeg); Celery + Redis workers via
  `CELERY_BROKER_URL` (`backend/app/celery_app.py`, DB rows are the
  source of truth, startup recovery re-queues stuck jobs). See §5/§5b
  for the wiring and the verification status — Postgres and
  Redis/Celery ran against real local servers, S3 against a moto mock
  (not real AWS S3); a real cloud deploy is still unverified.
  Still missing around them: no Docker yet (the Dockerfiles are
  untested — the worker image needs FFmpeg + the same env as the
  backend, and `render.yaml` has no Celery worker service yet, so
  `REDIS_URL` there is deliberately unwired), no dead-letter queue,
  no per-job retry with backoff (a failed job is re-run by the user),
  no S3 lifecycle/cleanup for superseded clip versions or the
  `.s3cache` directory, and pipeline re-runs after a worker crash are
  not idempotent (duplicate clips from the crashed attempt stay).
- No automated tests beyond the manual end-to-end runs recorded in `TESTING.md` (Phase 1 + Phase 2 steps 1–3; the test scripts live in `/tmp`, not in the repo).
- ~~Frontend editor is a skeleton wired to real clip data (trim range + caption
  toggle are "Coming soon" until implemented — they do not pretend to work).
  The wavesurfer.js waveform (tap-to-seek) is real and working.~~ **DONE in
  Phase 2, step 2 (2026-11-16)** — trim (draggable region + inputs), caption
  editing, 4 subtitle styles, framing nudge, volume, thumbnail picking and
  regenerate are all wired to real FFmpeg re-renders and verified live
  (see `TESTING.md`). Still missing in the editor: no live preview of the
  framing crop (it only moves in the re-rendered file), no per-word timing
  re-alignment after a caption edit (edited words are spread evenly across
  their group's span), and no undo/history of past versions (old version
  files are deleted once a re-render succeeds).

## 8. Run it (summary — full instructions in `README.md`)

```bash
cp .env.example .env            # edit keys if you have them; works without any
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm install && npm run dev   # http://localhost:3000
```

## 9. Editor + re-render (Phase 2, step 2)

### Edit parameters — one source of truth

A clip's current edits live in `clips.edit_params_json`:

```json
{"trim_start": 0.0, "trim_end": 28.62, "caption_overrides": [],
 "style": "karaoke", "framing_offset": 0.0, "volume": 1.0}
```

- `trim_start` / `trim_end` are **seconds into the highlight window**
  (`highlight.end - highlight.start`), not into the rendered clip. That
  keeps trims stable across re-renders: the rendered clip is always
  `highlight.start + trim_start .. highlight.start + trim_end`.
- `caption_overrides` are `{group_index, text}` against the caption
  groups of the **current (trimmed) window**, in order. Indexes shift if
  the trim changes — the frontend always fetches fresh groups before
  editing, and overrides are re-applied against the current window's
  grouping at render time.
- `POST /api/clips/{id}/re-render` merges the request body over the
  stored parameters (omitted fields keep their stored value;
  `caption_overrides`, when present, replaces the stored list entirely),
  validates (0 ≤ start < end ≤ window, ≥ 2 s, style known, volume
  0.25–2.0, framing −1..1), stores the merged parameters, and starts the
  job. `POST /api/clips/{id}/regenerate` starts the same job with the
  stored parameters unchanged.

### The re-render job (`pipeline/rerender.py`)

1. Load clip + project + highlight + transcript; compute the absolute
   window from the stored trim.
2. Apply caption overrides: each overridden group's words are replaced
   by the edited text split into words, **re-timed proportionally**
   (equal slices across the group's span). Honest approximation: the
   edited words are not re-transcribed, so their timing is evenly
   spread, not speech-aligned. A re-transcription after an edit would
   be accurate but much slower; empty override text drops the group.
3. Re-detect scenes + face track for the new window (best-effort, same
   modules as the first render), then call the same `render_clip()` with
   `volume` (FFmpeg `volume` filter, omitted entirely at 1.0), `style`
   (one of the 4 ASS presets in `pipeline/captions.py`) and
   `framing_offset` (added to the per-segment face-track median centre,
   clamped 0..1; with no face track it nudges the centre crop).
4. Write `clip_{id}_v{version+1}.mp4`. Only on success does the Clip row
   switch to it (path/duration/file_size/version/status="ready") and the
   old version file get deleted. On failure the Clip row keeps the last
   good file (status back to "ready") and the job row carries the error.
5. One re-render job per clip at a time: a second request while one is
   queued/running returns the existing job (202) instead of starting a
   second render on the same file. Jobs are `kind="rerender"` rows in
   the same `jobs` table, linked to the clip via `jobs.clip_id`.

### Subtitle styles (`pipeline/captions.py`)

`CAPTION_STYLES` maps a style name to ASS attributes + a rendering mode:
`karaoke` and `bold` emit one Dialogue event per word (current word
yellow); `minimal` and `highlighted` emit one event per group.
`highlighted` colours "keyword" words yellow by a deterministic rule:
≥ 5 letters after stripping punctuation, or in a small emphasis set
(`free`, `best`, `secret`, …) — a length heuristic, not semantic
keyword extraction. `render_clip()` keeps its Phase 1 signature
backwards-compatible: `volume`, `style`, `framing_offset` are optional
with defaults, so `pipeline/runner.py` is unchanged for first renders.

### Thumbnails

`POST /api/clips/{id}/thumbnail?t=<seconds>` extracts one JPEG frame at
`t` seconds into the **rendered** clip (`ffmpeg -ss t -i clip
-frames:v 1`) and stores it as `clip_{id}_thumb.jpg` next to the clip
(`clips.thumbnail_path`). `GET /api/clips/{id}/thumbnail` serves it.
Every editor endpoint requires the caller's JWT and is ownership-checked
like all other clip endpoints (other users' clips return 404).

### Bugs found by the editor work (both fixed, 2026-11-16)

1. **Face-tracked crop filter was broken since Phase 1** — `vertical_filter()`
   built `crop=…:min(max(0.5*iw-…,0),iw-…)` with unescaped commas, which
   FFmpeg rejects (`No such filter: '0)'`). It never fired in Phase 1
   because no test video ever had a detected face, so `center_x` was
   always `None`. The editor's framing nudge exercised it for the first
   time. Fixed by escaping the commas (`\,`) in `pipeline/reframe.py`;
   verified with a direct FFmpeg crop and with synthetic face tracks
   through `render_clip()` (see `TESTING.md`).
2. **Caption edit absorbed a neighbouring word** — after replacing a
   group's words, `words_to_ass()` re-grouped the flat word list and the
   edited group swallowed the next word ("HELLO EDITED WORDS" rendered
   as "HELLO EDITED WORDS welcome"). Fixed with a `_new_group` boundary
   flag set by `apply_caption_overrides()` on the first word of an
   edited group and of the group after it, honoured by
   `group_words()` in `pipeline/captions.py`.

## 10. LLM highlight scoring + the scorer label (Phase 2, step 3)

### How it works

`runner.py` builds `llm_config = (OPENAI_API_KEY, OPENAI_BASE_URL,
OPENAI_MODEL)` only when a key is set, and passes it to
`detect_highlights()`. `score_highlights_llm()` sends **transcript
text only** (timestamped segments, truncated to 12,000 chars) to
`POST {base_url}/chat/completions` with the configured model and
`temperature 0.3`, parses the JSON array out of the reply, and returns
`(highlights, "llm")`. On **any** failure — HTTP error, bad JSON, empty
result — it logs a warning, runs the heuristic scorer, prefixes every
fallback highlight's reasons with `"LLM scoring unavailable —
heuristic score"`, and returns `(fallback, "heuristic")`. The
heuristic path (no key configured) returns `(highlights,
"heuristic")`. `runner.py` stores the returned scorer on every
`Highlight` row, `HighlightOut` exposes it, and the frontend prints it
verbatim as "Scored by: LLM" / "Scored by: Heuristic" on the project
page (per clip) and in the editor's Clip info. There is no code path
that can show "LLM" for a heuristic highlight: the label comes from
the stored column, not from whether a key is configured.

### Verification status

Verified 2026-11-16 against a **local mock** `/chat/completions`
server with a dummy key (see `TESTING.md`, 14/14 checks): the LLM path
is used when the mock answers (its distinct picks/scores come back),
and the labelled heuristic fallback runs when the mock returns 500.
**Not verified with a real OpenAI key** — no real call has ever been
made, so real-key behaviour (model output quality, malformed replies,
rate limits, cost) is unknown. Also note: in this dev VM, `httpx`
honours `HTTP(S)_PROXY`/`NO_PROXY` env vars, and the VM's `NO_PROXY`
value breaks httpx localhost calls — a localhost `OPENAI_BASE_URL`
here would fail into the heuristic fallback; that is an environment
quirk, not a product bug, and does not affect Render/Railway deploys.
