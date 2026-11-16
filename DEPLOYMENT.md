# Deploying MMSN Clipper — written for a phone-only user

You have no computer. You do **not** need one for this. The code lives on
GitHub, a cloud host runs it, and you open it in your phone browser like any
website. Everything below is taps in apps/websites — no terminal, no laptop.

## The flow (one line)

**GitHub repo → Render (or Railway) → live link → open it on your phone.**

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
   `mmsn-backend` and `mmsn-frontend`. Tap **Apply**.
5. While it builds (a few minutes), tap the **backend service** →
   **Environment** and add these if you have them (all optional):
   - `YOUTUBE_API_KEY` — your YouTube Data API key (see below).
   - `OPENAI_API_KEY` — only if you want LLM highlight scoring
     (see "LLM scoring" below). You can also set `OPENAI_MODEL`
     (default `gpt-4o-mini`) — leave `OPENAI_BASE_URL` alone unless
     you use a different OpenAI-compatible provider.
   Leave them out and the app still works: upload → transcribe → clips,
   with the built-in heuristic scorer.
   `SECRET_KEY` is **not** optional — Render auto-generates it from
   `render.yaml` (a random JWT signing secret). If you ever reset it,
   everyone gets signed out and must sign in again.
6. Wait for both services to show **Live**. Tap the **frontend** service →
   copy its URL (something like `https://mmsn-frontend.onrender.com`).
7. **Open that link on your phone.** That is the app. Bookmark it / add it
   to your home screen (browser menu → "Add to Home screen") so it feels
   like an app.

> **Important:** after the first deploy, go back to the backend's
> Environment settings and set `CORS_ORIGINS` to your real frontend URL
> (the one from step 6). The default in `render.yaml` is a guess —
> if uploads fail with a network/CORS error, this is the first thing to
> check. Then tap **Manual Deploy → Deploy latest commit** on the backend.

## Deploy on Railway (alternative)

1. Open [railway.app](https://railway.app), sign in with GitHub.
2. **New Project → Deploy from GitHub repo** → pick `Mmsn`.
3. Railway uses `railway.json` and deploys the backend. Add a second
   service for the frontend from the same repo (root directory `frontend`,
   Dockerfile `frontend/Dockerfile`).
4. Set the same optional env vars as above, plus
   `NEXT_PUBLIC_API_URL` on the frontend service to the backend's public URL.
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
| **Render free / Railway trial credits** | The dashboard and the API will run. Processing will be **slow** — a 10-minute video can take many minutes — and **long videos may run out of memory and fail** (free instances have ~512 MB RAM; the Whisper `tiny` model alone wants ~1 GB while running). Free Render instances also **sleep after inactivity** and take ~1 minute to wake up. Good for trying the app with short test clips, **not** for real daily use. |
| **Render Standard (~$7–25/month per service) or Railway paid usage** | The realistic minimum for actual use. More RAM/CPU, no sleeping, longer videos work. Even then, very long videos (1h+) are slow on CPU — GPU or a bigger instance is a later-phase upgrade. |
| **Storage** | Render's free tier has **no persistent disk** — uploaded videos and rendered clips disappear when the service restarts or redeploys. `render.yaml` adds a 10 GB disk (paid). For real use, move storage to S3-compatible object storage (later phase). |

**We have not tested the free tier with real videos** — the local test in
`TESTING.md` ran on a VM with 8 GB RAM. Do not expect smooth free-tier
performance; if clips fail on the free tier, it is almost certainly the
memory limit, not a bug in the app.

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

- **"Service unavailable / waking up"** — free Render instance was asleep;
  wait ~1 minute and refresh.
- **Processing fails on a long video** — almost certainly out of memory on
  the free tier; try a shorter video or upgrade the plan.
- **Upload fails with a network error** — check `CORS_ORIGINS` on the
  backend matches the frontend URL exactly (step 7 note above).
- **"YouTube API not configured"** — expected without a key; upload instead.
