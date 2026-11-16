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
| **GitHub Pages** | $0, public repos on GitHub Free; published site ≤ **1 GB**, soft **100 GB bandwidth/mo**, soft 10 builds/hour, 10-min deploy timeout, custom domain + HTTPS | **Not for this app** — see below. Static files only, and GitHub's terms forbid running a commercial SaaS on it. |

### GitHub Pages — why it cannot host this app

GitHub Pages is real free hosting, but it is the wrong tool for MMSN
Clipper, for three separate reasons — any one of them is enough:

1. **It can never host the backend.** Pages serves static files only.
   GitHub's docs state it "does not support server-side languages such
   as PHP, Ruby, or Python" — so the FastAPI backend, Whisper, FFmpeg
   and Postgres cannot run there at all.
2. **It cannot host our frontend as built.** The frontend is Next.js
   with `output: "standalone"` (a Node server build), and every page
   is a client component with dynamic routes (`/projects/[id]`,
   `/clips/[id]`) whose IDs only exist at runtime. A static export
   would need code changes (static-export build, dynamic routes
   reworked, a `404.html` hack for client-side routing) and has never
   been tried for this app.
3. **GitHub's terms forbid this use.** GitHub's Terms for Additional
   Products and Features say Pages "is not intended for or allowed to
   be used as a free web-hosting service to run your online business,
   e-commerce site, or any other website that is primarily directed at
   either facilitating commercial transactions or providing commercial
   software as a service (SaaS)." This project is a SaaS by design
   (accounts, sign-in, video processing; payments planned later), and
   Pages also must not be used for "sensitive transactions like sending
   passwords" — our sign-in page does exactly that. Donation buttons
   and crowdfunding links are the only monetisation Pages allows.

**The one legitimate Pages use for this project:** a static
landing/docs page about the clipper (what it does, screenshots, link
to the real app) would fit Pages perfectly — 1 GB and 100 GB/mo are
plenty for that, and a project showcase is Pages' intended use. It
just cannot be the app itself.

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

## Self-hosted PaaS on the free VM — Coolify (and Dokploy)

A PaaS is a dashboard that turns "push code" into a live app with HTTPS
and databases, without writing server configs by hand. Both tools below
are free to self-host; they need a server of their own, which is normally
a $5–20/mo VPS — **but on the Oracle Always Free VM the combination is
$0 in total** (free PaaS + free server). That makes them worth evaluating
against deploying directly with Docker Compose on the same VM.

### Coolify

- **What it is:** open-source self-hosted PaaS (Apache-2.0,
  [github.com/coollabsio/coolify](https://github.com/coollabsio/coolify),
  ~63k stars as of Oct 2026). Git-push deploys from GitHub/GitLab,
  builds with Nixpacks/Dockerfile/Docker Compose, automatic HTTPS via
  Traefik + Let's Encrypt, one-click databases and services, web
  dashboard (port 8000). Self-hosting is free forever with all features;
  Coolify Cloud (a hosted dashboard for your own servers) is $5/mo for
  2 servers and is **not needed** here.
- **Requirements:** 2 CPU cores, 2 GB RAM, 10 GB disk minimum (4 GB RAM
  recommended), Ubuntu 22.04/24.04 or Debian, Docker Engine 24+,
  **amd64 and ARM64** — so it fits the Oracle free Ampere A1 VM
  (2–4 OCPU / 12–24 GB RAM, 200 GB disk) with room to spare. Install is
  one command as root (`curl …/coolify/install.sh | bash`), then the
  dashboard walks through setup.
- **What it would buy over direct Docker Compose:** a phone-friendly
  dashboard (deploy, logs, env vars, domains in a browser instead of
  SSH commands), automatic rebuild on every git push, and one-click
  Postgres/Redis provisioning.
- **What it costs (not money — complexity and risk):**
  - **An extra layer that can break.** Coolify runs its own containers
    (dashboard, proxy, its database) on top of the app — roughly
    0.5–1 GB RAM overhead, and a Coolify upgrade or misconfiguration
    can take the app down in ways plain Compose cannot.
  - **More setup steps, not fewer.** Install script → dashboard
    account → connect GitHub → create separate resources for the
    backend, the frontend, Postgres and Redis → set each one's env
    vars → set each one's domain. Our `docker-compose.yml` +
    `scripts/oracle-setup.sh` already does all of that in **one
    command**.
  - **Builds run on the same VM** and can make it unresponsive while a
    Next.js build runs (Coolify's own docs warn about this).
  - **A security-sensitive surface.** The dashboard is internet-facing
    and must be kept updated — one comparison counted 61 published
    advisories Jan–Jul 2026, 16 of them critical. Plain Compose has no
    dashboard to attack.
  - **It does not remove the hard parts.** You still need the Oracle
    account, the VM, a domain, and open ports — exactly the same as
    Option A. Coolify only replaces the last step (starting the
    containers).

### Dokploy (the closest alternative)

- Also open source and free to self-host; Docker Swarm-based,
  compose-native, dashboard + one-click databases + Traefik HTTPS,
  minimum 2 GB RAM / 30 GB disk, ports 80/443/3000. Differences that
  matter here: a **smaller, newer community** than Coolify; licence is
  Apache-2.0 **except** `/proprietary` folders (source-available,
  commercial agreement needed for production use); SSO/roles/audit
  logs need an Enterprise licence, and Dokploy Cloud starts at
  $4.50/mo/server. Swarm adds its own quirks on top of plain Compose.
  No advantage over Coolify for this single-app case.

### Verdict

**Coolify on the Oracle free VM is a legitimate $0 combination — but it
is NOT the recommended default for this project.** Direct Docker Compose
is simpler (one script, fewer moving parts, less RAM, no dashboard to
secure or update), and it is already built and documented for this repo.
Choose Coolify only if you later want to host **several apps on the one
VM** or you want **click-to-deploy instead of SSH commands** — at that
point its dashboard earns its overhead. If a PaaS is ever wanted,
Coolify is the pick over Dokploy (bigger community, plain Apache-2.0
licence, self-updates). Nothing about Coolify changes the $0 math: the
server is the cost, and the Oracle VM is already free.

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
- **GitHub Pages cannot host this app** (static only, no backend; and its
  terms forbid running a commercial SaaS on it) — it could only host a
  static landing page about the project. **Coolify/Dokploy on the same
  Oracle VM is also $0 total** and is documented above as an alternative,
  not the default — direct Docker Compose is simpler for one app.

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
Oracle Always Free, Vercel Hobby, Neon, Supabase, Cloudflare R2). GitHub
Pages limits and terms (GitHub Docs, "GitHub Pages limits" and "Terms for
Additional Products and Features", effective Aug 27, 2026) and the
Coolify/Dokploy comparison (their docs and GitHub pages, checked Oct–Nov
2026) were checked again 2026-11-16. Re-check before deploying.
