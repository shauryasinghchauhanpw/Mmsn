# Free-tier research — can this stack run for $0?

Researched 2026-11-16 (secondary sources quoting each vendor's own pricing/docs
pages, checked Oct–Nov 2026). **Free tiers change without notice — re-check the
vendor's pricing page before you deploy.** Nothing here is a promise.

## The constraint that decides everything

The pipeline needs **~1 GB of RAM while Whisper `tiny` is transcribing** (plus
FastAPI + FFmpeg on top), a place where uploaded videos, clips and the user
database survive restarts, and no time limit. Any host that fails one of those
cannot run the backend for real — it can only serve the dashboard.

## Hosts evaluated

| Host | Free compute | RAM / CPU | Sleep / persistence | Verdict for the backend |
|---|---|---|---|---|
| **Render free** | Web service, 750 instance-hours/mo/workspace | **512 MB**, 0.1 CPU | Sleeps after 15 min idle (~1 min wake); **no persistent disk**; free Postgres expires after **30 days** (deleted 14 days later) | **Cannot run the pipeline.** Boots and serves pages, but Whisper transcription will run out of memory. Demo only. |
| **Railway Free** | $1 of usage credit/mo (no rollover); one-time $5 trial, 30 days | **0.5 GB**, 1 vCPU per service; 0.5 GB volume | No sleep stated, but $1 buys ~0.1 GB-month of RAM — a continuously running 0.5 GB service costs ~$5/mo | **Cannot run for $0.** The trial (2 vCPU / 1 GB, 30 days) can test it, then it bills. |
| **Koyeb free** | 1 web service per org | **512 MB**, 0.1 vCPU, 2 GB SSD | Scales to zero after 1 h idle; no volumes; **card required ($29 hold)** | **Cannot run the pipeline** (512 MB). Card required even for free. |
| **Fly.io** | **No free tier for new accounts** — trial only ($1 credit, 7 days) | Trial machines up to 2 vCPU / 4 GB | Trial only | **Not free.** Cheapest always-on machine ~$2.19/mo (256 MB — also too small for Whisper). |
| **Hugging Face Spaces** | Static Spaces free; up to 2 Gradio Spaces on ZeroGPU (5 min GPU/day) | CPU Basic is 2 vCPU / **16 GB RAM**, 50 GB ephemeral disk | Sleeps after 48 h idle; disk wiped on restart | **Cannot host this app free.** As of 2026, creating a Gradio/Docker Space on compute **requires PRO ($9/mo)**; only Static + ZeroGPU Gradio Spaces are free for personal accounts. Our app is FastAPI + Next.js, not Gradio. |
| **Google Cloud free tier** | e2-micro, always free (US regions) | **1 vCPU / 1 GB RAM**, 30 GB disk, 1 GB egress/mo | Always on | **Marginal — not recommended.** 1 GB is right at Whisper tiny's needs with nothing left for FastAPI/FFmpeg; expect OOM on anything but the shortest clips. |
| **Oracle Cloud Always Free** | Ampere A1 VM(s) | **Up to 4 OCPU / 24 GB RAM** total (see note below), 200 GB block storage, **10 TB egress/mo** | **No expiry — forever free.** No sleep. Idle instances *can* be reclaimed if CPU+memory+network all stay below ~10–20% for 7 days (regular use prevents this). Capacity is contended: "Out of host capacity" errors are common in busy regions. | **Yes — the only free host that can genuinely run the whole stack.** Card required for identity verification (not charged while inside Always Free limits). Setup is a raw Linux VM (Docker, reverse proxy, HTTPS) — harder than a one-click PaaS, so this repo ships `docker-compose.yml` + `scripts/oracle-setup.sh` to make it one command. |

**Oracle quota note:** most sources still list 4 OCPU / 24 GB RAM. One
September 2026 source reports Oracle cut the free A1 allocation to
**2 OCPU / 12 GB** around June 2026. Either size runs this app comfortably
(backend + Postgres + Redis + Caddy use ~2–3 GB); the docs below say
"2–4 OCPU / 12–24 GB" wherever the exact number matters.

## Frontend

| Host | Free tier | Verdict |
|---|---|---|
| **Vercel Hobby** | $0 forever; 100 GB transfer/mo, 1M CDN requests, 4 Active-CPU-hours/mo; **non-commercial personal use only** (ads/payments/affiliate use need Pro $20/mo) | **Recommended default.** Next.js-native, no sleep for static serving. |
| Render free static / Cloudflare Pages | $0, generous static hosting | Fine alternatives; Vercel is the natural fit for Next.js. |

## Database (free)

| Service | Free tier | Catch |
|---|---|---|
| **Neon** (recommended) | **0.5 GB storage, 100 CU-hours/project/mo**, up to 100 projects; **no card, no expiry** | Compute scales to zero after 5 min idle (wakes on next query); exceeding a limit suspends compute until next month — data is not deleted. |
| Supabase | 500 MB DB, 1 GB files, 2 projects | Free projects **pause after 1 week without activity** (restore from dashboard; data kept). |
| Render free Postgres | 256 MB RAM, 1 GB storage | **Expires after 30 days, then deleted.** Do not use for anything you want to keep. |
| Postgres in Docker on the Oracle VM | Included in the VM's 200 GB disk | No extra account; data lives on the VM's disk. **Default in `docker-compose.yml`.** |

## File storage (free)

| Service | Free tier | Catch |
|---|---|---|
| **Local disk on the Oracle VM** (default) | 200 GB block storage, included | Files live on the VM; back them up yourself. |
| Cloudflare R2 | 10 GB-month, 1M writes / 10M reads, **zero egress fees** | **Card or PayPal required to enable R2**, even inside the free allowance. Optional upgrade, not the default. |
| Backblaze B2 | 10 GB free | Egress fees apply above the free allowance. |

## What "everything free" actually means here

Default deployment ($0, no card except Oracle's verification card):

- **Frontend:** Vercel Hobby — $0.
- **Backend + worker + Postgres + files:** one Oracle Always Free VM —
  $0 forever (within Always Free limits).
- **Scoring:** built-in heuristic — $0. **YouTube metadata:** YouTube Data
  API free quota, 10,000 units/day — $0. **yt-dlp:** optional,
  own-videos-only, $0.

**Honest limits of the $0 path (see `DEPLOYMENT.md`):**

- No SLA anywhere; free tiers can change or be withdrawn.
- The Oracle VM needs a card for verification and can be hard to provision
  in busy regions; idle VMs can be reclaimed after 7 days below ~10–20% use.
- Whisper runs on CPU: a 10-minute video takes minutes, not seconds, and
  a 1-hour video is slow. Keep test videos short first.
- Vercel Hobby is non-commercial — the moment the app earns money (ads,
  payments, paid plans), Vercel requires Pro ($20/mo/seat).
- Render free remains in `render.yaml` only as a **demo**: the site boots,
  but video processing will run out of memory and all data is lost on
  every restart/sleep.
- Cloudflare R2 needs a card to enable, so it is an optional upgrade, not
  part of the $0 default.

## What paid buys (optional upgrades, never the default)

| Upgrade | Cost (at time of writing) | What it buys |
|---|---|---|
| Render Standard backend + disk | ~$25/mo + ~$2.50/mo | No sleep, 2 GB RAM, persistent disk, one-click deploy — the easy path. |
| Railway Hobby | $5/mo minimum (incl. $5 usage) | Up to 48 GB RAM per service, no sleep, volumes. |
| Hugging Face PRO | $9/mo | Docker/CPU Spaces, 10 ZeroGPU Spaces. |
| OpenAI key (LLM scoring) | Pay-per-use | Smarter highlight picks; heuristic stays the free fallback. |
| Cloudflare R2 | $0 to start, then per-GB | Durable object storage with free egress (card needed to enable). |
| A bigger Oracle shape / any VPS | From ~$5/mo | More CPU/RAM for long videos; removes the idle-reclamation risk. |

Sources: vendor pricing/docs pages as quoted by the free-tier comparisons
checked 2026-11-16 (Render, Railway, Koyeb, Fly.io, Hugging Face Spaces,
Oracle Always Free, Vercel Hobby, Neon, Supabase, Cloudflare R2). Re-check
before deploying.
