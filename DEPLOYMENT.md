# Deploying MMSN Clipper — written for a phone-only user

You have no computer. You do **not** need one for this. The code lives on
GitHub, a cloud host runs it, and you open it in your phone browser like any
website. Everything below is taps in apps/websites — no terminal, no laptop
(except one optional script you paste into Oracle's browser-based Cloud
Shell, which also runs on your phone — and only if you ever use the
Oracle appendix path).

**The default deployment is $0 and needs NO card.** Not Oracle (it
rejected this user's RuPay card), not a paid plan, not a paid key:
the backend runs on Render free, transcription runs on Groq's free
Whisper API (free key, no card), and the frontend runs on Render free
too. See `FREE_TIER.md` for the research behind every claim below,
and the honest limits of each free tier.

> **⚠️ If your only card is a RuPay debit card, Oracle is OUT.**
> RuPay works only in India; Oracle is a US company and its
> verification runs on international card rails. Turning on
> "international transactions" in your bank app does **not** fix a
> RuPay card — the block is the card network, not a setting. This
> user also cannot get a Visa/Mastercard, so the Oracle path
> (Appendix D) is closed entirely. That is why the default below
> uses Render + Groq instead — no card anywhere in the path. The
> only key you need is a free Groq API key (console.groq.com, no
> card). Full reasoning in `FREE_TIER.md`, "No card? The RuPay
> problem".

## The flow (one line)

**GitHub repo → Render free (backend + frontend, Groq transcription)
→ live link → open it on your phone.**

## Option A (recommended, $0, no card) — Render free + Groq

The default. No card, no Oracle, no server to manage: Render runs the
backend and the frontend from the `Mmsn` repo (`render.yaml`), and
transcription runs on Groq's free Whisper API. It works because the
code was slimmed to fit 512 MB: transcription is offloaded to Groq
(`TRANSCRIPTION_PROVIDER=groq`), the render uses the `ultrafast`
preset, and face tracking is off (centre crop). Measured 2026-11-16:
a full job (66 s test video → 3 clips, 1080x1920) peaks at **388 MB**
total — inside the 512 MB limit, with ~124 MB of headroom. The
trade-offs, stated plainly: clips render with the `ultrafast` preset
(faster, slightly lower quality per bit than `veryfast`), the 9:16
crop is centred instead of following the speaker's face, audio is
sent to Groq's API (their free plan has zero data retention as a
self-serve setting), and Render free sleeps after 15 idle minutes
with no persistent disk (accounts/clips are lost on restart unless
you add a free Neon Postgres URL — see the env table).

### A1. Get a free Groq API key (phone browser, no card)

1. Open [console.groq.com](https://console.groq.com) in your phone
   browser and sign up (email, Google or GitHub — **no card asked**).
2. Tap **API Keys → Create API Key**. Give it any name, tap Create.
3. **Copy the key** (it starts with `gsk_...`). You will only see it
   once — keep it somewhere safe. Never paste it anywhere public, and
   never commit it to the repo.
4. Free-plan limits (Groq's published free tier, checked 2026-11-16):
   20 requests/min, 2,000 requests/day, 8 hours of audio/day. A
   personal project will not come close; if the daily quota is ever
   spent, jobs fail with a clear "Groq rate limit" message and work
   again the next day. Nothing is faked.

### A2. Deploy the Render Blueprint

1. Open [render.com](https://render.com), sign in with GitHub.
2. Tap **New +** → **Blueprint** → pick the **`Mmsn`** repo.
3. Render reads `render.yaml` (backend + frontend, both on the
   **free** plan). It asks for the optional values — leave
   `YOUTUBE_API_KEY` and `OPENAI_API_KEY` blank, and paste your Groq
   key into **`GROQ_API_KEY`**. Tap **Apply**. **No card is needed.**
4. Wait for both services to show green **Live**, then open the
   frontend URL (something like `https://mmsn-frontend.onrender.com`).

### A3. Check it worked

- Open `https://mmsn-backend.onrender.com/health` — you should see
  text starting with `{"status":"ok",…}`. (First load can take ~1
  minute if the free service was asleep.)
- Open the frontend URL — you should see the MMSN sign-in page.
- First real test: create an account (tap "Create one"), then upload
  a **short** video (under 1 minute) and tap Process. If a clip comes
  back, the whole thing works end to end. Start short: the blueprint
  caps uploads at 256 MB / 5-minute videos, and a long video on a
  512 MB instance is the most likely thing to run out of memory.

### Option A limits (honest)

- **512 MB is tight by design.** The job fits (388 MB measured), but
  there is only ~124 MB of headroom. Longer videos (near the 5-minute
  cap), many clips, or a busy moment can still push it over — if a
  job fails with an out-of-memory error, try a shorter video.
- **Sleeps after 15 idle minutes** (~1 min wake on the next visit).
- **No persistent disk.** Accounts, projects and clips live in
  SQLite inside the container and are **lost on every restart/sleep/
  redeploy**. Paste a free **Neon** Postgres URL into `DATABASE_URL`
  (0.5 GB, 100 CU-hours/mo, no card, no expiry) if you want accounts
  to survive — video/clip files are still lost on restart either way.
  Never use Render's free Postgres: it expires after 30 days and is
  then deleted.
- **Groq is a third party.** Audio is sent to Groq's API for
  transcription (free plan, zero data retention as a self-serve
  setting). If Groq's free tier changes or goes away, jobs fail with
  a clear message — the local-Whisper path (`TRANSCRIPTION_PROVIDER=
  local`) needs ~1 GB and cannot run here.
- **Lower render quality + no face-following.** `ultrafast` preset
  and centre crop (see above) — the price of fitting in 512 MB.
- **Vercel alternative for the frontend:** the blueprint already
  includes the frontend on Render free. If you prefer Vercel Hobby
  (also $0, no sleep for static serving), deploy the `frontend/`
  folder there with `NEXT_PUBLIC_API_URL` set to your backend URL,
  and set the backend's `CORS_ORIGINS` to your Vercel URL.

## Option B — Railway (30-day trial, no card — if trial deploys are open)


The **no-card route that runs the full pipeline locally** (local Whisper, `veryfast`, face tracking on) — but only
for 30 days, and its availability is uncertain right now. A new Railway
account gets a one-time **$5 trial credit for 30 days, no credit card**,
and during the trial each service can use **2 vCPU / 1 GB RAM** — enough
for Whisper tiny, so real clips are possible. After 30 days (or when the
$5 is spent) the account drops to the Free plan: $1/month of credit and
**0.5 GB RAM per service**, which cannot run the pipeline — the app
stops working for free.

**⚠️ Status warning (2026-11-16):** Railway had a major security
incident on Oct 21, 2026 (attacker decrypted some customers' environment
variables). New signups reopened Nov 2 — but at reopening "new customers
must subscribe to a paid plan (Hobby or Pro) before they can deploy, and
free trial deployments remain temporarily unavailable." Railway's pricing
page still advertises the trial with no card (checked Nov 16), so it may
be back. **Try it, and if the dashboard asks you to subscribe to Hobby
before deploying, the trial is still closed — stop there and do not pay.**
Also note: trial volumes are deleted 30 days after the trial ends unless
you upgrade, so anything you make here is temporary. `railway.json`
deploys the backend (health check on `/health`); add the frontend as a
second service (root directory `frontend`). Do not rely on it as the free
path — it is a 30-day test window. Full steps are in "Deploy on Railway"
below. (Why not Hugging Face Spaces instead? Its own docs say creating a
Docker Space needs PRO $9/mo — checked 2026-11-16. See `FREE_TIER.md`.)

## Option C (demo only, $0) — Render free without a Groq key
Use this only to **try the site**, not to process real videos.
It is Option A with the Groq key left out.

1. Open [render.com](https://render.com), sign in with GitHub.
2. Tap **New +** → **Blueprint** → pick the **`Mmsn`** repo.
3. Render reads `render.yaml` (both services on the **free** plan) and
   asks for the optional values — leave `YOUTUBE_API_KEY`,
   `OPENAI_API_KEY` **and `GROQ_API_KEY`** blank. Tap **Apply**.
   **No card is needed.**
4. Wait for both services to show green **Live**, then open the frontend
   URL (something like `https://mmsn-frontend.onrender.com`).

**What will and will not work on Option C:**

- The site boots, you can sign up, and the dashboard works.
- **Video processing will fail with a clear message**: without a
  Groq key the job stops at transcription ("GROQ_API_KEY is not
  set"). The local-Whisper fallback is not attempted here because it
  needs ~1 GB and this instance has 512 MB — it would just run out
  of memory instead. Add a Groq key (Option A, step A1) and the same
  deploy processes videos.
- **All data is lost on every restart/sleep/redeploy** — free Render has
  no persistent disk, and services sleep after 15 idle minutes (~1 min
  wake). Accounts, projects and clips disappear.
- **Do not paste a Neon/database URL you care about into a demo you do
  not need** — but if you want accounts to survive a restart on Option C,
  paste a free **Neon** Postgres URL into `DATABASE_URL` (see the env
  table below). Never use Render's free Postgres: it expires after 30
  days and is then deleted.

## Before you start (all options)


- The latest code must be on GitHub first. If Muse just finished work and
  has not pushed yet, wait for the push — every host reads the code from
  the `Mmsn` repo.
- No card is needed for the default (Option A: Render free + Groq) —
  only a free Groq API key (console.groq.com, no card). Render
  Option C needs no card either (demo only). Vercel Hobby needs no
  card. Railway trial needs no card **if** trial deploys are open
  for new customers (uncertain since the Oct 2026 incident — see
  Option B). Only Appendix D (Oracle) needs a card, and it must be
  **Visa/Mastercard, not RuPay** (see the box at the top) — this
  user does not have one, so Appendix D is closed to him.

## Accounts you need


1. **GitHub** — you already have it (`shauryasinghchauhanpw`). The code is
   in the `Mmsn` repo.
2. **Groq** — for Option A (console.groq.com, free API key, no card).
3. **Oracle Cloud** — only for Appendix D (not available to this user).
4. **Vercel** — only for the frontend in Appendix D (sign up with GitHub).
5. **Google Cloud** — only if you want the YouTube-link metadata feature.
   Optional; the app works without it (upload path). See step 5.

### After the first deploy — one check (Option A only)

On Render, `CORS_ORIGINS` is already set in `render.yaml` to
`https://mmsn-frontend.onrender.com`, which matches the frontend service
name. **You only need to touch it if Render gave your frontend a
different URL** (for example if the name was taken and Render added a
suffix). If uploads fail with a network/CORS error, compare the two:
tap the frontend service, copy its exact URL, then tap the backend
service → **Environment** → check `CORS_ORIGINS` is exactly that URL
(no trailing `/`). If you change it, tap **Manual Deploy → Deploy
latest commit** on the backend so it restarts with the new value.

On Appendix D, `CORS_ORIGINS` must be your **Vercel** URL — see D4 above.

## Environment variables — the full table


These live in the backend's environment — on the Oracle VM that means the
`.env` file in `~/mmsn` (created by `scripts/oracle-setup.sh`); on Render
they live in the backend service → **Environment**. `render.yaml` already
sets the ones marked "in blueprint" — you only need to add the optional
keys if you want those features. `docker-compose.yml` sets the database
and storage paths for Option A — you do not set those by hand there.

| Variable | Where | Required? | What happens if you leave it out |
|---|---|---|---|
| `SECRET_KEY` | backend | **Yes — but auto-set** | Render generates a random one from `render.yaml` (`generateValue`); the Oracle setup script generates one into `.env`. Never type one in by hand, never share it. If you ever reset it, everyone gets signed out and must sign in again. |
| `DATABASE_URL` | backend | No (defaults) | **Appendix D (Oracle VM):** set by `docker-compose.yml` to the Postgres container — do not set it yourself. **Option A / C (Render free):** leave blank and the app uses SQLite in the container, which is **lost on every restart/sleep** — or paste a free **Neon** Postgres URL (0.5 GB, 100 CU-hours/mo, no card, no expiry) to keep accounts and projects. **Never use Render's free Postgres** — it expires after 30 days and is then deleted. The app normalises `postgres://` to `postgresql+psycopg://`. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Oracle VM only | Yes for Appendix D | The setup script generates `POSTGRES_PASSWORD` for you. Needed by `docker-compose.yml` for the Postgres container. |
| `DOMAIN` | Oracle VM only | Yes for Appendix D | Your backend's public hostname (e.g. `clipper.example.com`). Caddy uses it for automatic HTTPS. |
| `UPLOAD_DIR` / `MEDIA_DIR` | backend | No (defaults) | Appendix D: `/app/media/uploads` and `/app/media` inside the VM's 200 GB disk (set by compose) — uploads and clips survive restarts. Option A / C: defaults inside the container (lost on restart — free Render has no disk). Do not change them unless you know why. |
| `TRANSCRIPTION_PROVIDER` | backend | **Yes for Option A** | `groq` (set in `render.yaml`) — transcription runs on Groq's free Whisper API. `local` uses faster-whisper on the machine instead — needs ~1 GB RAM, so it **cannot run on Render free** (512 MB); only use it on a bigger host (Appendix D, Railway trial). Leave it as `groq` on Render. |
| `GROQ_API_KEY` | backend | **Yes for Option A** | Free Groq API key (console.groq.com → API Keys, no card). Without it, jobs fail at transcription with a clear "GROQ_API_KEY is not set" message — that is Option C (demo). Never commit a real key; paste it in Render → backend → Environment. |
| `GROQ_MODEL` | backend | No (blueprint default) | `whisper-large-v3-turbo` — Groq's hosted Whisper model with word-level timestamps. Leave alone unless Groq renames it. |
| `GROQ_BASE_URL` | backend | No (default) | `https://api.groq.com/openai/v1` — only change it to point at a different OpenAI-compatible transcription endpoint. |
| `WHISPER_MODEL` / `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | backend | No (blueprint default) | `tiny` / `cpu` / `int8` — the lightest local model. **Ignored while `TRANSCRIPTION_PROVIDER=groq`** (Option A). Only matters on a host that runs local transcription (Appendix D, Railway trial). Leave alone. |
| `RENDER_PRESET` | backend | No (blueprint default) | x264 preset for clip renders. `veryfast` (default) is the quality/speed balance — but its render child peaks at ~418 MB at 1080x1920. `render.yaml` sets `ultrafast` (~210 MB) so the job fits in Render free's 512 MB. Unknown values fall back to `veryfast`. |
| `FACE_TRACKING` | backend | No (blueprint default) | `1` (on, default): the 9:16 crop follows the speaker's face (YuNet, ~180 MB peak RAM in-process). `0` (off): centre crop instead. `render.yaml` sets `0` so the job fits in Render free's 512 MB. |
| `CLIPS_PER_PROJECT` | backend | No (blueprint default) | `3` — max clips rendered per video. Leave alone. |
| `YOUTUBE_API_KEY` | backend | Optional | Leave blank and the "paste a YouTube link" box shows "not configured — upload instead". Everything else still works. See "Getting a YouTube Data API key" below. |
| `OPENAI_API_KEY` | backend | Optional | Leave blank and clips are picked by the built-in heuristic scorer (app says "Scored by: Heuristic", $0). Add a key and the LLM scorer runs instead (see "LLM scoring" below). `OPENAI_MODEL` defaults to `gpt-4o-mini`; leave `OPENAI_BASE_URL` alone unless you use a different OpenAI-compatible provider. |
| `CORS_ORIGINS` | backend | No (blueprint default) | Default is the frontend URL above. Only change it if your real frontend URL is different. |
| `NEXT_PUBLIC_API_URL` | **frontend** | Yes | **Appendix D (Vercel):** set it to your backend URL, e.g. `https://clipper.example.com`. **Option A (Render):** `https://mmsn-backend.onrender.com` (set in `render.yaml`). This is baked into the frontend's files **at build time** — changing it needs a rebuild (Vercel/Render do that automatically when you change it and redeploy). Do not set it to `localhost` — that only works on a dev computer. |
| `REDIS_URL` / `CELERY_BROKER_URL` | backend | **Do not set unless you run a worker** | Background jobs (Redis + Celery) are **implemented and verified locally with a real Redis server** — when a broker is set, jobs run on a Celery worker and survive a backend restart. On Appendix D, start the worker with `docker compose --profile worker up -d` **and** set `CELERY_BROKER_URL=redis://redis:6379/0` in `.env`. On Render there is no worker service, so setting this there would queue jobs no worker ever runs — leave it unset and jobs run in-process (marked failed, not silently re-run, if the backend restarts). |
| `STORAGE_BACKEND` / `S3_BUCKET` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_ENDPOINT_URL` / `S3_REGION` | backend | Optional | Cloud file storage is **implemented** (`STORAGE_BACKEND=s3` + bucket/keys; blank endpoint = AWS S3, set it for MinIO/R2). Verified against a moto mock S3 server only — **not yet against real AWS S3/R2**. Default `local` keeps files on the VM's disk (Appendix D) or in the container (Option A / C). Cloudflare R2's free tier (10 GB, zero egress) is the $0-friendly choice, but **R2 needs a card/PayPal to enable** — that is why it is an optional upgrade, not the default. Only set these if you have a bucket ready; wrong values will break uploads/downloads. |
| `PORT` | both | **Do NOT set** | Render injects this itself (default 10000) and routes traffic to it; `docker-compose.yml` sets it to 8000 for Caddy. Setting it by hand on Render makes the service unreachable. The Dockerfiles already read it correctly. |

> **Rule of thumb:** leave `REDIS_URL` / `CELERY_BROKER_URL` alone unless
> you also start a worker (Option A `--profile worker`). `STORAGE_BACKEND=s3`
> only works with a real bucket and keys; the default `local` is the safe choice.

## Deploy on Railway (alternative)


**First check the trial is actually open for new customers** (see Option
B above): after Railway's Oct 2026 security incident, trial deploys were
"temporarily unavailable" for new signups at the Nov 2 reopening. If
Railway asks you to subscribe to Hobby/Pro before you can deploy, stop —
the trial is still closed and this path is not free right now.

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
6. **Remember the clock:** the $5 trial lasts 30 days, then the Free
   plan (0.5 GB RAM) cannot run the pipeline. Export/download anything
   you care about before it ends — trial volumes are deleted 30 days
   after the trial expires unless you upgrade.

## LLM scoring (optional — how it works on the deployed app)


Without a key, every clip is picked by the built-in heuristic scorer
and the app says **"Scored by: Heuristic"** next to each clip. If you
add `OPENAI_API_KEY` to the backend's environment (`.env` on the VM,
or the Environment tab on Render), the pipeline sends **only the
transcript text** to OpenAI and uses the model's picks instead, and the
app says **"Scored by: LLM"**. The label always shows which scorer
actually ran — it can never claim LLM when the heuristic ran.

- **Getting a key (phone):** open
  [platform.openai.com](https://platform.openai.com) in your phone
  browser → sign in → **API keys → Create new secret key** → copy it
  and set it as `OPENAI_API_KEY` (`.env` on the VM, or the backend's
  Environment tab on Render). You need a payment method on the
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
5. Copy the key and paste it as `YOUTUBE_API_KEY` — into `.env` on the
   VM (Appendix D, then `docker compose restart backend`) or into the
   backend's Environment tab on Render (Option A).
   (Restrict it: API restrictions → YouTube Data API v3.)

## Free vs paid — please read this


Video processing is **heavy**. Transcription (Whisper) and video rendering
(FFmpeg) need real CPU and RAM. Be honest about what to expect:

| Path | Cost | What happens |
|---|---|---|
| **Option A — Render free + Groq (default)** | **$0, no card** | The default that actually processes videos with no card: transcription on Groq's free Whisper API (8 h audio/day), backend + frontend on Render free (512 MB). Measured 2026-11-16: a full job peaks at **388 MB** (ultrafast renders, face tracking off, centre crop). Sleeps after 15 idle min; **all data lost on restart** (no disk — add free Neon Postgres for accounts); 5-min video cap; audio sent to Groq. |
| **Option C — Render free without a Groq key (demo only)** | **$0** | Same deploy as Option A with the key left out: site boots, you can sign up, but **jobs fail at transcription** with a clear "GROQ_API_KEY is not set" message. Sleeps after 15 idle min; all data lost on restart. Demo only. |
| **Option B — Railway trial** | **$5 credit, 30 days, no card — if trial deploys are open** | The no-card route that runs the **full** pipeline locally (local Whisper, `veryfast`, face tracking on — 2 vCPU / 1 GB during the trial, ~721 MB peak, fits). After 30 days it drops to the $1/mo Free plan (0.5 GB) and the pipeline stops working for free. **Status uncertain since Railway's Oct 2026 breach** — at the Nov 2 reopening, new customers had to subscribe to a paid plan before deploying. Try it; if it asks for Hobby, stop. Not a $0 home. |
| **Appendix D — Oracle Always Free VM + Vercel** | **$0 forever** (within limits) | The best free path for anyone WITH a Visa/Mastercard: 2–4 OCPU / 12–24 GB RAM, 200 GB disk, Postgres + files on the VM, no sleep, no expiry, full local pipeline, no third-party API. **Not available to this user** — Oracle rejected his RuPay card and he cannot get a Visa/Mastercard. Free ARM capacity can be "out of host capacity"; an idle VM can be reclaimed after 7 days below ~10–20% use. Vercel Hobby is non-commercial — earning money from the app needs Pro ($20/mo/seat). |
| **Render Standard backend + disk (~$25/mo + ~$2.50/mo — optional upgrade)** | Paid | No sleeping, 2 GB RAM, persistent 10 GB disk, one-click Blueprint deploy. This was the old default before the free directive. It still cannot do long videos fast on CPU, but it runs the pipeline reliably for short videos. **Needs a card too** — it does not solve a no-card situation. |
| **Bigger VPS (~$5/mo+ — optional upgrade)** | Paid | Any cheap VPS with ≥2 GB RAM (Hetzner, DigitalOcean, etc.) runs the same `docker-compose.yml` — just point `DOMAIN` at it. |
| **OpenAI key (optional, LLM scoring)** | Pay-per-use | A few paise/cents per video with `gpt-4o-mini`. Without it the heuristic scorer runs for $0 and the app says so. |

**Hosting tiers were tested with real videos locally, not on the live host** — the memory measurements in `TESTING.md` ran on a dev VM (1.5 shared CPUs): Groq-mode job peaks at 388 MB total (fits Render free's 512 MB), local-Whisper mode peaks at ~721 MB (fits Railway trial's 1 GB, not Render free). No live deploy has run yet (no Render/Railway/Oracle account exists here), so the first real deploy is still the test. Start with short test videos (under 1 minute) on the deployed app before trying anything long.

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
- **Costs to you:** the app itself is free/open source, and the default
  deployment (Option A: Render free + Groq)
  is **$0**. You only pay if you choose an optional upgrade: a paid
  host plan, an OpenAI key (pay-per-use, LLM scoring only), or paid
  cloud storage. The YouTube Data API is free within its quota.

## If something goes wrong


- **"Service unavailable / waking up"** (Options A/C) — free Render
  instance was asleep; wait ~1 minute and refresh.
- **Backend not responding on Appendix D** — on the VM, run
  `docker compose ps` (all services should say "running") and
  `docker compose logs -f backend` for the error. Common causes:
  wrong `DOMAIN` in `.env`, ports 80/443 not open in the Oracle
  security list, or the domain not pointing at the VM's public IP.
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
  on a small instance; try a shorter video. On Option A/C (Render free,
  512 MB) this is expected for videos near the 5-minute cap — the job
  fits with ~124 MB of headroom, so a long or complex video can still
  push it over. On Option B (Railway trial, 1 GB) the same video fits.
- **Upload fails with a network error** — check `CORS_ORIGINS` on the
  backend matches the frontend URL exactly (see "After the first
  deploy" above).
- **"YouTube API not configured"** — expected without a key; upload instead.
- **Job fails with "GROQ_API_KEY is not set"** — the backend is on
  `TRANSCRIPTION_PROVIDER=groq` with no key (Option C, demo). Add a
  free Groq key to the backend's Environment and redeploy/restart.
- **Job fails with "Groq rate limit"** — the free plan's daily
  quota (8 hours of audio/day) is spent; wait until tomorrow. If it
  happens on the first video of the day, the key itself may be wrong
  — check the backend logs for a 401 (bad key) instead.
- **Job fails with "Groq transcription: could not reach the Groq
  API"** — the host cannot reach api.groq.com (network/DNS). On
  Render free this should not happen; check the backend logs and
  retry once.
- **Sign-in works but your old projects are gone after a redeploy** —
  that means the database was not on persistent storage. On **Options A/C**
  this is expected: free Render has no disk and SQLite is lost on every
  restart — paste a free Neon Postgres URL into `DATABASE_URL` if you
  want accounts to survive. On **Appendix D**, check the VM:
  `docker compose ps` should show the `db` service running and
  `docker volume ls` should list `mmsn_pgdata` and `mmsn_media`. If the
  database was on SQLite outside a volume, projects created before the
  fix cannot be recovered.

## Deploy readiness checklist


Checked in this session (2026-11-16). "Verified" means actually checked
here; "not verified" means nobody has checked it yet — it is not a
promise.

### Verified ✅

- `render.yaml` parses as YAML and matches the Render Blueprint spec:
  two `web` services, `docker` env, `dockerfilePath` values that exist in
  the repo, valid `plan` names (**`free`** backend and frontend),
  `SECRET_KEY` with `generateValue: true`, `sync: false` on the optional
  keys, `healthCheckPath: /health` (the endpoint exists and is public),
  guardrails (`MAX_VIDEO_SECONDS: 300`, `MAX_UPLOAD_MB: 256`), the
  low-memory switches (`TRANSCRIPTION_PROVIDER=groq`,
  `RENDER_PRESET=ultrafast`, `FACE_TRACKING=0` — see "Verified" memory
  measurements in `TESTING.md`), and **no `disk:` and no `databases:`
  block on purpose** — free Render has no disk, and its free Postgres
  expires after 30 days.
- `docker-compose.yml` (Appendix D, Oracle VM) parses as YAML: services
  `db` (Postgres 16, volume `pgdata`), `backend`, `worker` and `redis`
  (both under profile `worker`), `caddy` (ports 80/443, `${DOMAIN}`);
  `backend` depends on `db` healthy and has a `/health` healthcheck.
- `scripts/oracle-setup.sh` passes `bash -n` (syntax check) and only
  installs free software; it generates `SECRET_KEY`/`POSTGRES_PASSWORD`
  into `.env` and never prints them.
- URLs are consistent: frontend `NEXT_PUBLIC_API_URL` =
  `https://mmsn-backend.onrender.com` matches the backend service name,
  and backend `CORS_ORIGINS` =
  `https://mmsn-frontend.onrender.com` matches the frontend service name
  (Option A). For Appendix D the backend URL is `https://${DOMAIN}` and
  the frontend is the Vercel URL (see D4).
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
- No real secrets in the repo: `SECRET_KEY` is generated by Render or
  the setup script, `.env` is gitignored, `.env.example` holds
  placeholders only.
- **Phase 3 hardening verified (see `TESTING.md`):** Postgres works
  against a real Postgres server (URL normalisation, all 7 tables,
  migration path); Redis/Celery works end-to-end against a real
  `redis-server` (register → upload → process on a worker, job `done`,
  backend-restart recovery re-queues a stuck job); S3 works against a
  moto mock S3 server (upload → process → presigned download →
  thumbnail, re-render publishes a new version). The Render blueprint
  wires **neither** Postgres nor Redis (both are demo-only on free
  Render — Postgres lives in `docker-compose.yml` for Appendix D, and
  Neon free is the documented alternative); S3 stays opt-in — see the
  env-var table above.

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
   (and `MEDIA_DIR=/app/media` explicitly) — **superseded twice since**:
   first by managed Postgres in `render.yaml` (Phase 3), then by the
   free-tier change (this session): the paid backend/disk and the
   managed Postgres are gone from `render.yaml`; persistence now lives
   in `docker-compose.yml` (Postgres container + `pgdata`/`media`
   volumes, Option A) or a free Neon Postgres URL (Option B). The
   SQLite-on-disk values remain the documented fallback if neither is
   used — but on free Render that fallback is still lost on restart,
   because free Render has no disk at all.
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
- **Live deploy on Render free + Groq — not run.** No Render account
  or credentials exist in this environment, and no account was created.
  The first Blueprint apply is the test. (The 388 MB peak is a local
  measurement, not a live-container measurement — no Docker/cgroup
  cap could be enforced in this VM to prove the 512 MB limit directly.)
- **Live deploy on Oracle VM + Vercel (Appendix D) — not run.** No Oracle account or
  credentials exist in this environment, and no account was created.
  `docker-compose.yml` and `scripts/oracle-setup.sh` were only
  syntax/consistency-checked here (YAML parse, `bash -n`, env wiring);
  the first real VM run is the test.
- **Live deploy on Railway — not run** (same reason; `railway.json`
  exists and was not changed). Trial deploys for new customers were
  "temporarily unavailable" at Railway's Nov 2, 2026 reopening after
  the Oct 21 security incident — re-check railway.com before trying.
- **Hugging Face Spaces — ruled out, not attempted.** Verified against
  Hugging Face's own docs (`huggingface.co/docs/hub/spaces-overview`,
  2026-11-16) that creating a Gradio/Docker Space requires PRO
  ($9/mo); free ZeroGPU is Gradio-only. No Space config was added to
  the repo because creation itself is paywalled for our FastAPI app.
- **Real OpenAI key / real YouTube API key** — only the mock / not-
  configured paths have ever run (see `TESTING.md`).
- **Postgres / Redis / S3 on a live host** — Postgres is wired in
  `docker-compose.yml` (Option A) and verified against a real local
  Postgres; Redis/Celery is implemented in the code with a `worker`
  profile in compose but the live worker run is not verified; S3 is
  opt-in via env vars and verified against a moto mock only. Real AWS
  S3/R2 and a live Neon Postgres deploy are not verified.
- **Phone-browser flow** (sign-up → upload → process → download) —
  verified at API/build level only; no live browser check exists in
  this environment.
## Appendix D — Oracle VM + Vercel (needs a Visa/Mastercard — not available to this user right now)


This was the old default and is still the best free path for anyone who HAS a Visa/Mastercard: the VM has 2–4 CPU cores and 12–24 GB of RAM (Oracle's Always Free allowance), 200 GB of disk, and never expires, so it runs the full pipeline locally (local Whisper, `veryfast` renders, face tracking on) with no third-party API and no 512 MB squeeze. The frontend runs free on Vercel.

**It is NOT available to this user:** Oracle rejected his only card (RuPay, domestic-only) and he cannot get a Visa/Mastercard. Do not start here — use Option A. This appendix stays in the docs so the path is not lost if a card ever becomes available.

### D1. Create the Oracle account and VM (phone browser)

1. Open [cloud.oracle.com](https://cloud.oracle.com) in your phone browser
   and tap **Sign up** (or "Start for free"). Create the account with your
   email. **Oracle asks for a payment card for identity verification** —
   it is not charged while you only use Always Free resources. **It must
   be a Visa/Mastercard (or another international network) — a RuPay
   debit card will fail** (RuPay is domestic-only; see the box at the
   top of this guide). If your only card is RuPay, stop here and use
   Option A (Render + Groq) instead — this appendix needs a card,
   and ask your bank for a Visa/Mastercard debit card.
2. Pick a **Home Region** carefully — it is locked forever, and Always Free
   resources only exist inside it. Pick a big multi-AD region such as
   **US East (Ashburn)** or **EU Central (Frankfurt)**.
3. After sign-up, open the **Compute → Instances → Create instance**.
   - Image: **Ubuntu 22.04 or 24.04** (Canonical Ubuntu).
   - Shape: **VM.Standard.A1.Flex** (Ampere ARM) — set **4 OCPU and
     24 GB RAM** (if the form only offers 2 OCPU / 12 GB, take that —
     either size runs this app; see `FREE_TIER.md`).
   - Networking: keep the default VCN, and make sure the instance gets a
     **public IP**. Open ports **80 and 443** in the security list
     (or add an ingress rule for 0.0.0.0/0 on 80 and 443).
   - Add your SSH key (or use a password — Oracle Cloud Shell can
     connect without a key).
   - Tap **Create**. If you get **"Out of host capacity"**, the region
     is full for free ARM shapes — wait and retry, or try another
     availability domain in the same region. This is the most common
     problem; it is not your fault.
4. Note the VM's **public IP address**.

### D2. Point a domain at the VM

You need a real hostname for automatic HTTPS (a bare IP only serves plain
HTTP). Free options: a subdomain from a free DNS service (e.g. DuckDNS,
afraid.org) or any domain you already own. Create an **A record** pointing
your name (e.g. `clipper.example.com`) at the VM's public IP, and wait a
few minutes for it to resolve.

### D3. Run the one-command setup (Cloud Shell, on your phone)

1. In the Oracle console, open **Cloud Shell** (the `>_` icon at the top —
   it runs in your phone browser, no app needed).
2. From Cloud Shell, connect to your VM (Oracle shows the SSH command;
   or use the console's "SSH" button). Then run:
   ```bash
   DOMAIN=clipper.example.com bash <(curl -fsSL https://raw.githubusercontent.com/shauryasinghchauhanpw/Mmsn/main/scripts/oracle-setup.sh)
   ```
   (Replace `clipper.example.com` with your real domain.) The script
   installs Docker, fetches the code, creates your `.env` with random
   secrets, and starts backend + Postgres + Caddy (automatic HTTPS).
   It takes a few minutes the first time.
3. Open `https://clipper.example.com/health` in your phone browser — you
   should see text starting with `{"status":"ok",…}`. That means the
   backend is live.

### D4. Deploy the frontend free on Vercel

1. Open [vercel.com](https://vercel.com), sign in with GitHub.
2. **Add New → Project → Import** the **`Mmsn`** repo.
3. Set **Root Directory** to **`frontend`**. (The repo root is not a
   Next.js app — the frontend lives in the `frontend/` folder.)
4. Set the environment variable **`NEXT_PUBLIC_API_URL`** to
   **`https://clipper.example.com`** (your backend URL from A3).
5. Tap **Deploy**. Vercel gives you a `*.vercel.app` URL — that is the
   app. Bookmark it / add it to your home screen.
6. **After the Vercel deploy:** the backend's `CORS_ORIGINS` must allow
   your Vercel URL, or uploads will fail with a network error. On the VM,
   edit `.env` in `~/mmsn` (`CORS_ORIGINS=https://YOUR-APP.vercel.app`),
   then restart the backend: `docker compose restart backend`.

> **Do not use GitHub Pages for the frontend.** Pages is static-only
> (our frontend is a Next.js Node-server build with dynamic routes),
> and GitHub's terms forbid using Pages to run a commercial SaaS — this
> project is one by design, and its sign-in page collects passwords,
> which Pages must not be used for. Vercel Hobby is the $0 frontend.
> Pages could only host a static landing page *about* the project.
> Full reasoning: `FREE_TIER.md`.

### What "Live" looks like — how to know it worked

- `https://clipper.example.com/health` shows `{"status":"ok",…}`.
- Opening the Vercel URL shows the MMSN sign-in page (not an error page).
- First real test: create an account (tap "Create one"), then upload a
  **short** video (under 1 minute) and tap Process. If a clip comes back,
  the whole thing works end to end.

### Appendix D limits (honest)

- **No SLA.** Oracle can reclaim an idle Always Free instance if CPU,
  memory and network all stay below ~10–20% for 7 days — using the app
  regularly prevents this; a VM nobody touches for a week may be stopped.
- **CPU transcription is slow.** A 10-minute video takes minutes to
  process; a 1-hour video is slow. Start with short videos.
- **Capacity:** free ARM shapes can be "out of capacity" — retry later or
  try another availability domain.
- **Vercel Hobby is non-commercial:** the moment the app earns money
  (ads, payments, paid plans), Vercel requires Pro ($20/mo/seat).

### Appendix D alternative — Coolify (not recommended for one app)

Coolify is a free, open-source dashboard that turns git pushes into live
apps with HTTPS and databases — and on the Oracle free VM the combination
is $0 in total. It is a legitimate alternative, but **not the default
for this project**: it adds a dashboard to secure and update, ~0.5–1 GB
RAM overhead, and more setup steps than the one-command
`scripts/oracle-setup.sh`, while the hard parts (Oracle account, VM,
domain, ports) stay exactly the same. Use it only if you later host
several apps on the one VM or want click-to-deploy instead of SSH
commands. Full evaluation, including Dokploy, is in `FREE_TIER.md`.

