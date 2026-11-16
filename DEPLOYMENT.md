# Deploying MMSN Clipper — written for a phone-only user

You have no computer. You do **not** need one for this. The code lives on
GitHub, a cloud host runs it, and you open it in your phone browser like any
website. Everything below is taps in apps/websites — no terminal, no laptop.

## The flow (one line)

**GitHub repo → Render (or Railway) → live link → open it on your phone.**

## Before you start

- The latest code must be on GitHub first. If Muse just finished work and
  has not pushed yet, wait for the push — Render reads the code from the
  `Mmsn` repo, so anything not pushed yet will not be in your deploy.
- You will need a payment card for Render. The backend in `render.yaml`
  is on a **paid plan on purpose** (see "Free vs paid" below) — Render
  shows you the monthly price on the confirmation screen before you pay
  anything. Read that price before you tap Apply.

## Accounts you need

1. **GitHub** — you already have it (`shauryasinghchauhanpw`). The code is
   in the `Mmsn` repo.
2. **Render** (recommended first try) — sign up at
   [render.com](https://render.com) with your GitHub account (tap
   "Sign up with GitHub"). Or **Railway** at
   [railway.app](https://railway.app) — also "Sign up with GitHub".
3. **Google Cloud** — only if you want the YouTube-link metadata feature.
   Optional; the app works without it (upload path). See step 5.

## Deploy on Render (step by step, phone)

1. Open [render.com](https://render.com) in your phone browser and sign in
   with GitHub.
2. Tap **New +** → **Blueprint**.
3. Pick the **`Mmsn`** repository. If it is not listed, tap
   "Configure account" and make sure the Muse GitHub App / Render's GitHub
   App can see the `Mmsn` repo.
4. Render reads `render.yaml` from the repo and shows two services:
   `mmsn-backend` and `mmsn-frontend`. It also asks for two optional
   values — `YOUTUBE_API_KEY` and `OPENAI_API_KEY`. **Leave both blank
   for now** unless you already have those keys (see steps 5–6 and the
   env-var table below). Tap **Apply**.
5. Render shows the price before it starts: the backend is a paid
   Standard plan (about $25/month at the time of writing) plus a 10 GB
   disk (about $2.50/month), and the frontend is free. **Check the price
   on that screen** — if it is different from what you expect, stop and
   ask Muse before confirming. Render may ask for a payment card here.
6. While it builds (a few minutes — the backend install is the slow part,
   it downloads Python packages and the Whisper setup), you can watch the
   progress: tap each service → **Logs**. Do not tap anything else yet.
7. Wait for **both** services to show a green **Live** badge. The backend
   usually takes longer than the frontend.
8. Tap the **frontend** service → copy its URL (something like
   `https://mmsn-frontend.onrender.com`).
9. **Open that link on your phone.** That is the app. Bookmark it / add it
   to your home screen (browser menu → "Add to Home screen") so it feels
   like an app.

### What "Live" looks like — how to know it worked

- Both services show a green **Live** badge in the Render dashboard
  (not "Deploying", "Build failed", or "Suspended").
- Opening the frontend URL shows the MMSN sign-in page (not a Render
  error page, not a blank page, not "Application failed to respond").
- Quick backend check (optional, same phone browser): open
  `https://mmsn-backend.onrender.com/health` — you should see a small
  page of text starting with `{"status":"ok",...}`. If you see that,
  the backend is up. If the browser shows an error, the backend is not
  up yet — check its Logs.
- First real test: create an account (tap "Create one"), then upload a
  **short** video (under 1 minute) and tap Process. If a clip comes back,
  the whole thing works end to end.

### After the first deploy — one check

`CORS_ORIGINS` on the backend is already set in `render.yaml` to
`https://mmsn-frontend.onrender.com`, which matches the frontend service
name. **You only need to touch it if Render gave your frontend a
different URL** (for example if the name was taken and Render added a
suffix). If uploads fail with a network/CORS error, compare the two:
tap the frontend service, copy its exact URL, then tap the backend
service → **Environment** → check `CORS_ORIGINS` is exactly that URL
(no trailing `/`). If you change it, tap **Manual Deploy → Deploy
latest commit** on the backend so it restarts with the new value.

## Environment variables — the full table

These live in the backend service → **Environment** (and one on the
frontend). `render.yaml` already sets the ones marked "in blueprint" —
you only need to add the optional keys if you want those features.

| Variable | Where | Required? | What happens if you leave it out |
|---|---|---|---|
| `SECRET_KEY` | backend | **Yes — but auto-set** | Render generates a random one from `render.yaml` (`generateValue`). Never type one in by hand, never share it. If you ever reset it, everyone gets signed out and must sign in again. |
| `DATABASE_URL` | backend | No (blueprint default) | **Phase 3: the blueprint wires a managed Postgres database** (`mmsn-db`, free plan — note: Render's free Postgres expires after 90 days, upgrade the plan before then). The app normalises the connection string and uses Postgres. To go back to SQLite, delete the `databases:` block in `render.yaml` and set this to `sqlite:////app/media/mmsn.db` (SQLite lives ON the 10 GB disk, so it survives restarts). |
| `UPLOAD_DIR` / `MEDIA_DIR` | backend | No (blueprint default) | Both point inside the disk (`/app/media/uploads`, `/app/media`), so uploaded videos and clips survive restarts. Do not change them. |
| `WHISPER_MODEL` / `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | backend | No (blueprint default) | `tiny` / `cpu` / `int8` — the lightest model, for the small server. Leave alone. |
| `CLIPS_PER_PROJECT` | backend | No (blueprint default) | `3` — max clips rendered per video. Leave alone. |
| `YOUTUBE_API_KEY` | backend | Optional | Leave blank and the "paste a YouTube link" box shows "not configured — upload instead". Everything else still works. See "Getting a YouTube Data API key" below. |
| `OPENAI_API_KEY` | backend | Optional | Leave blank and clips are picked by the built-in heuristic scorer (app says "Scored by: Heuristic", $0). Add a key and the LLM scorer runs instead (see "LLM scoring" below). `OPENAI_MODEL` defaults to `gpt-4o-mini`; leave `OPENAI_BASE_URL` alone unless you use a different OpenAI-compatible provider. |
| `CORS_ORIGINS` | backend | No (blueprint default) | Default is the frontend URL above. Only change it if your real frontend URL is different. |
| `NEXT_PUBLIC_API_URL` | **frontend** | No (blueprint default) | `https://mmsn-backend.onrender.com`. This is baked into the frontend's files **at build time** — changing it needs a rebuild (Render does that automatically when you change it and redeploy). Do not set it to `localhost` — that only works on a dev computer. |
| `REDIS_URL` / `CELERY_BROKER_URL` | backend | **Do not set on Render yet** | Phase 3 background jobs (Redis + Celery) are **implemented and verified locally with a real Redis server** — when a broker is set, jobs run on a Celery worker and survive a backend restart. But the Render blueprint does **not** wire it yet: there is no Celery worker service in `render.yaml`, so setting this on Render would queue jobs no worker ever runs. The `mmsn-redis` key-value service exists in the blueprint for when a worker is added (Phase 4). Until then, leave it unset — jobs run in-process in the backend and are marked failed (not silently re-run) if the backend restarts. |
| `STORAGE_BACKEND` / `S3_BUCKET` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_ENDPOINT_URL` / `S3_REGION` | backend | Optional | Phase 3 cloud file storage is **implemented** (`STORAGE_BACKEND=s3` + bucket/keys; blank endpoint = AWS S3, set it for MinIO/R2). Verified against a moto mock S3 server only — **not yet against real AWS S3/R2**. Default `local` keeps files on the 10 GB Render disk. Only set these if you have a bucket ready; wrong values will break uploads/downloads. |
| `PORT` | both | **Do NOT set** | Render injects this itself (default 10000) and routes traffic to it. Setting it by hand makes the service unreachable. The Dockerfiles already read it correctly. |

> **Rule of thumb:** leave `REDIS_URL` / `CELERY_BROKER_URL` alone on
> Render until a Celery worker service exists — setting it without a
> worker strands every job. `STORAGE_BACKEND=s3` only works with a real
> bucket and keys; the default `local` is the safe choice.

## Deploy on Railway (alternative)

1. Open [railway.app](https://railway.app), sign in with GitHub.
2. **New Project → Deploy from GitHub repo** → pick `Mmsn`.
3. Railway uses `railway.json` and deploys the backend (health check on
   `/health`). Add a second service for the frontend from the same repo
   (root directory `frontend`, Dockerfile `frontend/Dockerfile`).
4. Set the same optional env vars as above, plus
   `NEXT_PUBLIC_API_URL` on the frontend service to the backend's public URL.
   Railway also injects `PORT` itself — do not set it by hand; the
   Dockerfiles already read it.
5. Open the frontend's public domain on your phone.

## LLM scoring (optional — how it works on the deployed app)

Without a key, every clip is picked by the built-in heuristic scorer
and the app says **"Scored by: Heuristic"** next to each clip. If you
add `OPENAI_API_KEY` in the backend's Environment settings (Render
step 5 above), the pipeline sends **only the transcript text** to
OpenAI and uses the model's picks instead, and the app says
**"Scored by: LLM"**. The label always shows which scorer actually
ran — it can never claim LLM when the heuristic ran.

- **Getting a key (phone):** open
  [platform.openai.com](https://platform.openai.com) in your phone
  browser → sign in → **API keys → Create new secret key** → copy it
  into Render as `OPENAI_API_KEY`. You need a payment method on the
  OpenAI account (pay-per-use: a few paise/cents per video with
  `gpt-4o-mini`, billed by OpenAI, not by us). Keep the key secret —
  anyone with it can spend on your OpenAI account.
- **If the LLM call fails** (bad key, no credit, OpenAI down), the app
  does **not** fail the job — it falls back to the heuristic scorer
  and the clip's reasons say "LLM scoring unavailable". Processing
  still produces clips.
- **Not yet tested with a real key:** the LLM path was verified
  against a local mock server only (see `TESTING.md`). The first
  real-key run on the deployed app is still unverified — if clips
  come back labelled "Heuristic" after you add a key, check the
  backend logs for the "LLM scoring failed" warning.

## Getting a YouTube Data API key (optional, phone-friendly)

Only needed for the "paste a YouTube link → see its title/duration" box.
Without it that box shows "not configured — upload instead", and everything
else still works.

1. Open [console.cloud.google.com](https://console.cloud.google.com) in
   your phone browser, sign in with Google.
2. Create a project (any name, e.g. `mmsn-clipper`).
3. Left menu → **APIs & Services → Library** → search
   **YouTube Data API v3** → tap **Enable**.
4. **APIs & Services → Credentials → Create Credentials → API key**.
5. Copy the key and paste it into Render as `YOUTUBE_API_KEY`.
   (Restrict it: API restrictions → YouTube Data API v3.)

## Free vs paid — please read this

Video processing is **heavy**. Transcription (Whisper) and video rendering
(FFmpeg) need real CPU and RAM. Be honest about what to expect:

| Tier | What happens |
|---|---|
| **Render free (frontend only, in this blueprint)** | The free frontend **sleeps after ~15 minutes with no visitors** and takes about 1 minute to wake up on the next visit. Free instances have ~512 MB RAM. The frontend is just web pages, so that is fine — the first visit after a nap is slow, then it is normal. |
| **Render Standard backend (~$25/month + ~$2.50/month for the 10 GB disk, at the time of writing — check Render's price screen)** | The realistic minimum for actual use. No sleeping, more RAM/CPU, and the 10 GB disk keeps your uploads, clips, and user accounts when the service restarts or redeploys. Even then, very long videos (1h+) are slow on CPU — GPU or a bigger instance is a later-phase upgrade. |
| **Render free backend (NOT what the blueprint uses — do not switch to it)** | It would boot and serve the dashboard, but processing a video longer than a minute or two will be very slow or run out of memory (Whisper `tiny` alone wants ~1 GB while running), it sleeps after 15 idle minutes, and **free instances have no persistent disk at all** — uploads, clips, and the whole user database would disappear on every restart. |
| **Railway trial/paid usage** | Same idea as Render: the trial credits run out, then you pay for what you use. No persistent disk unless you add a volume. |

**We have not tested any hosting tier with real videos** — the local test in
`TESTING.md` ran on a dev VM (1.5 shared CPUs, ~650 MB free RAM at test
time). Do not expect smooth free-tier performance; if clips fail on a
small/cheap instance, it is almost certainly the memory limit, not a bug
in the app. Start with short test videos (under 1 minute) on the deployed
app before trying anything long.

## Using the app from your phone

- **First visit:** tap "Create one" on the sign-in page and make an
  account (email + password, 8+ characters). Your projects belong to that
  account — nobody else can see them. Signing out is in the header.
- **Upload a video:** tap "Choose video file" → pick a video from your
  phone's gallery/files. Uploads from a phone work, but a big video on
  mobile data will be slow — use Wi-Fi for anything over a few minutes.
- **Paste a YouTube link:** only gives you the title/duration/thumbnail.
  It does **not** download the video and can never make clips by itself.
  To make clips, upload the video file.
- **Downloading clips:** tap "Download MP4" on a clip — it saves to your
  phone like any downloaded video, then share it to Shorts/Reels/TikTok.
- **Editing a clip:** tap "Open in editor" on a clip. Drag the orange
  region on the waveform (or type the times) to trim; tap a caption
  group to reword it; pick a subtitle style (Karaoke / Minimal / Bold /
  Highlighted); use the Framing slider to nudge the 9:16 crop sideways
  and the Volume slider for loudness; then tap "Apply & re-render" and
  wait for the new version. Pause the video on the frame you want and
  tap "Set thumbnail from current frame" to pick a thumbnail. There is
  no live preview of the framing crop — it only moves in the re-rendered
  file. Each clip also shows "Scored by: LLM / Heuristic" so you know
  how its moment was picked.
- **Costs to you:** the app itself is free/open source. You pay the host
  (Render/Railway) if you go beyond their free tier, and optionally OpenAI
  if you add an LLM key. The YouTube Data API is free within its quota.

## If something goes wrong

- **"Service unavailable / waking up"** — free Render instance (the
  frontend) was asleep; wait ~1 minute and refresh.
- **Build failed** — tap the service → **Logs** and read the last red
  lines; that is the real error. Common causes:
  - *Frontend build error about `NEXT_PUBLIC_API_URL` / "Failed to
    compile"* — the build arg did not arrive; check the frontend
    service's Environment has `NEXT_PUBLIC_API_URL` set, then
    **Manual Deploy → Deploy latest commit**.
  - *Backend build error in `pip install`* — a package failed to
    download (network blip) or ran out of memory; tap **Manual Deploy →
    Deploy latest commit** to retry once. If it fails the same way twice,
    copy the error from Logs and ask Muse.
  - *"No open ports detected" / deploy times out but the build passed*
    — the app is not listening where Render expects. This was fixed in
    the Dockerfiles (they now read Render's `PORT`); if you still see
    it, make sure you deployed the latest pushed code and did not set
    `PORT` by hand in Environment.
  - *Blueprint errors when you tap Apply* (e.g. "invalid render.yaml")
    — the blueprint file itself is the problem; ask Muse and paste the
    exact error.
- **Service is Live but the page is blank / "Application failed to
  respond"** — tap the frontend service → **Logs**; if the frontend is
  fine, open the backend `/health` URL (see "What Live looks like") to
  see which half is down.
- **Processing fails on a long video** — almost certainly out of memory
  on a small instance; try a shorter video or upgrade the plan.
- **Upload fails with a network error** — check `CORS_ORIGINS` on the
  backend matches the frontend URL exactly (see "After the first
  deploy" above).
- **"YouTube API not configured"** — expected without a key; upload instead.
- **Sign-in works but your old projects are gone after a redeploy** —
  that means the database was not on the disk. Check the backend
  Environment: `DATABASE_URL` must be
  `sqlite:////app/media/mmsn.db` (four slashes, `/app/media/...`) and
  the service must have the `mmsn-media` disk. If either is wrong, fix
  it and redeploy — note that projects created before the fix cannot be
  recovered, because they were stored outside the disk.

## Deploy readiness checklist

Checked in this session (2026-11-16). "Verified" means actually checked
here; "not verified" means nobody has checked it yet — it is not a
promise.

### Verified ✅

- `render.yaml` parses as YAML and matches the Render Blueprint spec:
  two `web` services, `docker` env, `dockerfilePath` values that exist in
  the repo, valid `plan` names (`standard` backend, `free` frontend),
  `SECRET_KEY` with `generateValue: true`, `sync: false` on the two
  optional keys, `healthCheckPath: /health` (the endpoint exists and is
  public), and a 10 GB disk on the paid backend service.
- URLs are consistent: frontend `NEXT_PUBLIC_API_URL` =
  `https://mmsn-backend.onrender.com` matches the backend service name,
  and backend `CORS_ORIGINS` =
  `https://mmsn-frontend.onrender.com` matches the frontend service name.
- Both Dockerfiles reviewed line by line (hadolint is not installed in
  this VM, so this was a structured manual review against the repo and
  Render's docs, not a lint pass): base images (`python:3.12-slim`,
  `node:20-alpine`), every `COPY` source path exists, the frontend's
  `output: "standalone"` in `next.config.js` matches the standalone
  runner stage, and the backend image has FFmpeg + libass + fonts.
  Four real issues were found and fixed — see below.
- Render docs checked (2026-11-16): Render passes service env vars as
  Docker build args (so `NEXT_PUBLIC_API_URL` is baked into the frontend
  at build time), and a web service must listen on Render's injected
  `PORT` (default 10000).
- Frontend still builds: `npm run build` passes — 6 routes (`/`,
  `/login`, `/register`, `/projects/[id]`, `/clips/[id]`, `/_not-found`),
  First Load JS ~97–100 kB.
- No real secrets in the repo: `SECRET_KEY` is generated by Render,
  `.env` is gitignored, `.env.example` holds placeholders only.
- **Phase 3 hardening verified (see `TESTING.md`):** Postgres works
  against a real Postgres server (URL normalisation, all 7 tables,
  migration path); Redis/Celery works end-to-end against a real
  `redis-server` (register → upload → process on a worker, job `done`,
  backend-restart recovery re-queues a stuck job); S3 works against a
  moto mock S3 server (upload → process → presigned download →
  thumbnail, re-render publishes a new version). The Render blueprint
  wires Postgres but **not** Redis (no worker service yet) and leaves
  S3 opt-in — see the env-var table above.

### Fixes made in this session

1. **Backend listened on a hardcoded port 8000** — Render routes to its
   injected `PORT` (default 10000), so the service would have been
   unreachable ("no open ports detected"). `backend/Dockerfile` now
   starts uvicorn on `${PORT:-8000}`.
2. **SQLite database and uploads were not on the persistent disk** — the
   disk only covers `/app/media`, but the DB lived at `/app/mmsn.db` and
   uploads at `/app/uploads`, so every restart/redeploy would have
   wiped all users and projects. The fix was first `DATABASE_URL` at
   `sqlite:////app/media/mmsn.db` with `UPLOAD_DIR=/app/media/uploads`
   (and `MEDIA_DIR=/app/media` explicitly) — **superseded in Phase 3
   by managed Postgres**: `render.yaml` now wires `DATABASE_URL` from
   the `mmsn-db` database service instead; the SQLite-on-disk values
   remain the documented fallback if the `databases:` block is removed.
3. **Frontend Docker build would have failed: `frontend/public` did not
   exist** — the runner stage copies `/app/public`, and Docker COPY
   fails when the source path is missing. Added `frontend/public/
   .gitkeep` so the folder exists (still empty).
4. **OpenCV system libraries missing from the backend image** —
   `scenedetect` pulls non-headless `opencv-python`, which needs
   `libGL` at import. The code catches the failure, so the server would
   still boot — but face tracking and scene detection would silently
   stop working. `backend/Dockerfile` now installs `libgl1` and
   `libglib2.0-0`, plus `fonts-liberation` (metrically compatible with
   the "Arial" the caption styles ask for). Also added a root
   `.dockerignore` so local junk (`node_modules`, `.next`, dev DB,
   uploads) is never shipped into a build.

### NOT yet verified ⚠️

- **Docker image builds — not run.** There is no Docker daemon in this
  environment (`docker: command not found`), so neither image has ever
  actually been built. The first real `docker build` (or the first
  Render build) is the test.
- **Live deploy on Render — not run.** No Render account or credentials
  exist in this environment, and no account was created. The first
  Blueprint apply is the test.
- **Live deploy on Railway — not run** (same reason; `railway.json`
  exists and was not changed).
- **Real OpenAI key / real YouTube API key** — only the mock / not-
  configured paths have ever run (see `TESTING.md`).
- **Postgres / Redis / S3 on Render** — Postgres is wired in the
  blueprint (managed `mmsn-db`); Redis/Celery and S3 are implemented in
  the code but the blueprint has no Celery worker service yet and S3 is
  opt-in via dashboard vars. Real AWS S3/R2 and a live Render
  Postgres/Redis deploy are not verified.
- **Phone-browser flow** (sign-up → upload → process → download) —
  verified at API/build level only; no live browser check exists in
  this environment.
