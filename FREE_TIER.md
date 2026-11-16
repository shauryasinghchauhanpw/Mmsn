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
| **Railway Free** | $1 of usage credit/mo (no rollover); one-time $5 trial, 30 days, **no card** | Trial: **2 vCPU / 1 GB** per service; Free plan after trial: **0.5 GB**, 1 vCPU; 0.5 GB volume | No sleep stated; trial credits expire after 30 days; trial volumes are deleted 30 days after the trial ends unless upgraded | **The only no-card route that can actually run the pipeline — but only for 30 days, and currently uncertain.** During the trial a service gets 2 vCPU / 1 GB, which fits Whisper tiny, so real clips are possible. After the trial the Free plan's 0.5 GB cannot run the pipeline. **Status warning (2026-11-16):** after Railway's Oct 21, 2026 security incident, new signups reopened Nov 2 — but at reopening "new customers must subscribe to a paid plan (Hobby or Pro) before they can deploy, and free trial deployments remain temporarily unavailable." Railway's pricing page still advertises the trial with no card (checked Nov 16), so it may be back — **try it, but do not count on it until the deploy actually starts.** |
| **Koyeb free** | 1 web service per org | **512 MB**, 0.1 vCPU, 2 GB SSD | Scales to zero after 1 h idle; no volumes; **card required ($29 hold)** | **Cannot run the pipeline** (512 MB). Card required even for free. |
| **Fly.io** | **No free tier for new accounts** — trial only ($1 credit, 7 days) | Trial machines up to 2 vCPU / 4 GB | Trial only | **Not free.** Cheapest always-on machine ~$2.19/mo (256 MB — also too small for Whisper). |
| **Hugging Face Spaces** | Static Spaces free; up to 2 Gradio Spaces on ZeroGPU (5 min GPU/day) | CPU Basic is 2 vCPU / **16 GB RAM**, 50 GB ephemeral disk | Sleeps after 48 h idle; disk wiped on restart | **Cannot host this app free — confirmed against Hugging Face's own docs** (`huggingface.co/docs/hub/spaces-overview`, read 2026-11-16): "Static Spaces are free for everyone. Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts, Team or Enterprise for organizations." Our app is FastAPI + Next.js, so it needs the Docker SDK — PRO **$9/mo**. The only free compute is ZeroGPU, which is **Gradio-only** (2 Spaces, 5 min GPU/day) and cannot run a FastAPI backend. The 16 GB RAM is real but unreachable for free. |
| **Zeabur free** | Free plan $0, no card | — (no hosted compute) | — | **Cannot host the backend for $0.** The free plan only manages a server you own elsewhere (dashboard + build CI); the usage-billed shared cluster closed to new projects in March 2026, so there is no free compute to run on. You would still have to buy a server. |
| **Streamlit Community Cloud** | Free, public apps | ~**1 GB RAM**, shared CPU | Sleeps after 12 h idle | **Cannot run this backend.** Streamlit apps only — no FastAPI, no long-running worker, no FFmpeg pipeline. The wrong tool, even though the RAM number looks close. |
| **Google Cloud free tier** | e2-micro, always free (US regions) | **1 vCPU / 1 GB RAM**, 30 GB disk, 1 GB egress/mo | Always on | **Marginal — not recommended.** 1 GB is right at Whisper tiny's needs with nothing left for FastAPI/FFmpeg; expect OOM on anything but the shortest clips. |
| **Oracle Cloud Always Free** | Ampere A1 VM(s) | **Up to 4 OCPU / 24 GB RAM** total (see note below), 200 GB block storage, **10 TB egress/mo** | **No expiry — forever free.** No sleep. Idle instances *can* be reclaimed if CPU+memory+network all stay below ~10–20% for 7 days (regular use prevents this). Capacity is contended: "Out of host capacity" errors are common in busy regions. | **Yes — the only free host that can genuinely run the whole stack.** Card required for identity verification (not charged while inside Always Free limits). Setup is a raw Linux VM (Docker, reverse proxy, HTTPS) — harder than a one-click PaaS, so this repo ships `docker-compose.yml` + `scripts/oracle-setup.sh` to make it one command. |

**Oracle quota note:** most sources still list 4 OCPU / 24 GB RAM. One
September 2026 source reports Oracle cut the free A1 allocation to
**2 OCPU / 12 GB** around June 2026. Either size runs this app comfortably
(backend + Postgres + Redis + Caddy use ~2–3 GB); the docs below say
"2–4 OCPU / 12–24 GB" wherever the exact number matters.

## Transcription offload — Groq free Whisper API (2026-11-16)

The finding that changes the no-card math: **Groq's free plan serves
Whisper `large-v3-turbo` with word-level timestamps, no card, no end
date** — 20 requests/min, 2,000 requests/day, 7,200 audio seconds/hour,
28,800 audio seconds/day (8 hours of audio a day), 25 MB max per file,
`verbose_json` + `timestamp_granularities=["word","segment"]`
(Groq's own Speech-to-Text docs, checked 2026-11-16). That is a
*better* transcriber than local `tiny` (large-v3-turbo vs tiny), for
$0. This repo now has a `TRANSCRIPTION_PROVIDER=groq` switch
(`backend/pipeline/groq_transcribe.py`): audio is split into ≤10-min
chunks under Groq's 25 MB cap, transcribed remotely, and the word
timestamps are merged with offsets into the exact shape the local
transcriber returns — captions, highlights and the editor work
unchanged. Verified by tests against a local mock Groq server
(`backend/tests/test_groq_transcribe.py`, 10 tests); no real Groq key
has been used yet, so the first real-key run is still unverified.

Offloading transcription removes the ~1 GB Whisper need — but it does
**not** by itself make Render free work. The 1080x1920 render is the
second memory hog, and it was measured, not guessed (2026-11-16,
concurrent RSS sampling of a full 66 s job → 3 clips, this VM):

| Setup | Peak total (backend + live FFmpeg child) | Fits 512 MB? |
|---|---|---|
| Local Whisper + `veryfast` + face tracking (the old default) | **~721 MB** (backend 312 MB + render child 409 MB) | **No** |
| Groq + `veryfast` + face tracking | ~721 MB (same render child) | **No** — transcription was never the only problem |
| Groq + `ultrafast` + face tracking (+ `malloc_trim`) | **~569 MB** (backend 284 MB + child 284 MB) | **No** — still over |
| Groq + `ultrafast` + face tracking **off** (+ trim) | **~388 MB** (backend 168 MB + child 219 MB) | **Yes — ~124 MB headroom** |

What each switch costs: `ultrafast` renders faster at slightly lower
quality per bit than `veryfast`; face tracking off means a centre crop
instead of the crop following the speaker; `malloc_trim` after face
tracking/scene detection hands ~50 MB back to the OS. The render
child alone measures ~418 MB (`veryfast`) / ~210 MB (`ultrafast`) at
1080x1920, and the YuNet face tracker holds ~180 MB in-process —
those two numbers are why all three switches are needed together.
Honest caveats: the 388 MB figure is a local measurement (no
Docker/cgroup cap could be enforced in this VM to prove the 512 MB
limit directly), it used the synthetic test video, and the real
uvicorn server adds some overhead on top — the headroom is real but
not huge. Longer videos near the 5-minute cap can still push it over.

Privacy note: in Groq mode the audio leaves the machine and is sent
to Groq's API (their free plan has zero data retention as a self-serve
setting). Local transcription keeps audio on the server. The provider
is opt-in and the default stays local.

## No card? The RuPay problem (2026-11-16)

**The finding:** the user (phone-only, India) has only a **RuPay debit
card**, and Oracle rejected it. That is expected, not a glitch: RuPay is
India's **domestic-only** card network. Multiple sources agree — "The
RuPay debit card is only accepted in India. You cannot use the RuPay
debit card to purchase items from international websites" — and "If you
have a RuPay Card, you can ask your bank to provide a Visa or MasterCard
debit card." Oracle is a US merchant, so its identity-verification charge
runs on international card rails that RuPay does not use. (RuPay Global /
RuPay–JCB co-branded cards exist for travel, but whether one passes
Oracle's verification was **not** verified — do not rely on it.) Turning
on "international transactions" in the bank app does **not** fix a RuPay
card, because the block is the network, not a setting.

That matters because **every permanent free host that can run this
backend wants a card**: Oracle (verification only), Google Cloud
(e2-micro), AWS, Azure, Fly.io, Koyeb ($29 hold). The no-card hosts were
all re-checked on 2026-11-16:

| No-card host | Why it cannot run the backend permanently for $0 |
|---|---|
| **Hugging Face Spaces** | **Ruled out — Hugging Face's own docs** (`huggingface.co/docs/hub/spaces-overview`, read 2026-11-16): "Static Spaces are free for everyone. Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts." The free ZeroGPU tier is **Gradio-only** (2 Spaces, 5 min GPU/day). Our FastAPI + Next.js app needs the Docker SDK, i.e. PRO $9/mo. No Space config was added to the repo — there is nothing to wire up, because creation itself is paywalled. |
| **Railway trial** | The one real exception — **30 days only, and currently uncertain** (see the Railway row above). Trial: 2 vCPU / 1 GB, no card, can genuinely run the pipeline. After 30 days it drops to the $1/mo Free plan (0.5 GB), which cannot. And after the Oct 21, 2026 breach, new-customer trial deploys were "temporarily unavailable" at the Nov 2 reopening — try it, but verify on railway.com first. |
| **Render free** | No card, but **512 MB RAM** — Whisper alone wants ~1 GB. Demo only (site boots, processing fails, data lost on restart). |
| **Northflank Sandbox** | **Contradictory — do not rely on it.** Its pricing page says "No card needed" for the $20/mo Sandbox (2 services, 2 jobs, 1 database; a 1 vCPU / 1 GB service ≈ $18/mo fits inside $20), but its billing docs say "all users must add a payment method to start creating resources on Northflank, regardless of plan selection." If a card is demanded at resource creation, it is not a no-card path. |
| **Replit free** | 512 MB RAM, sleeps after inactivity, deployments need a paid plan. Cannot run the pipeline. |
| **PythonAnywhere free** | WSGI-only web apps (ASGI/FastAPI is experimental), 512 MB storage, 100 CPU-seconds/day, **no always-on or scheduled tasks** on the free tier, no Docker. Cannot run the pipeline or its worker. |
| **Glitch** | Project hosting shut down July 2025. Gone. |
| **Komuta free** | One free service: 0.1 vCPU / 256 MB RAM. Far too small. |
| **Vercel / Netlify / Cloudflare Pages** | Frontend/static only — no long-running Python backend, no Whisper/FFmpeg. (Vercel Hobby is already our $0 frontend.) |

**Honest conclusion (updated 2026-11-16): a permanent no-card path
now EXISTS — Render free + Groq transcription + the low-memory
switches** (`TRANSCRIPTION_PROVIDER=groq`, `RENDER_PRESET=ultrafast`,
`FACE_TRACKING=0`, all set in `render.yaml`). Measured peak for a full
job: **388 MB**, inside Render free's 512 MB. It is a real path, not a
demo — but a tight one: ~124 MB of headroom, `ultrafast` quality,
centre crop instead of face-following, audio sent to Groq, services
sleep after 15 idle minutes, and all data is lost on restart (no
disk). The old conclusion ("no no-card host can run it") was true
while transcription had to run locally; Groq's free Whisper API plus
the measured render/face-tracking savings changed the math. What is
still true: no no-card host can run the **unmodified** pipeline
(local Whisper + `veryfast` + face tracking needs ~721 MB) — only
Railway's 30-day trial (1 GB) can do that, and only for 30 days.

### The fallback ladder (no card in hand)

1. **Use the default: Render free + Groq** (Option A in
   `DEPLOYMENT.md`) — no card, permanent $0, processes videos. Get
   the free Groq key first (console.groq.com, no card).
2. **Railway trial** (Option B) — no card, and if trial deploys are
   back it runs the *full* pipeline locally (local Whisper,
   `veryfast`, face tracking on) for 30 days. Treat it as a test
   window or a quality upgrade window, not a home: on day 31 the app
   stops working for free.
3. **Get a Visa/Mastercard debit card from your own bank** — the
   permanent fix for the *best* free path. Banks issue one on request
   (in the bank app or at a branch, usually free or a small one-time
   fee) to replace a RuPay card. Once you have it, Oracle Always Free
   works (Appendix D in `DEPLOYMENT.md`): full local pipeline, no
   third-party API, no 512 MB squeeze. **This user cannot do this
   right now** (no Visa/Mastercard available) — recorded here so the
   path is not lost.
4. **Use a parent/family member's Visa/Mastercard for Oracle's
   verification step only** — Oracle does not charge it while you stay
   inside Always Free limits; it is identity verification, not a
   purchase. (Their choice, their card — ask first.)
5. **Render free demo without a Groq key** (Option C) — no card, site
   boots, you can sign up and click around, but jobs fail at
   transcription and everything is wiped on restart.
6. **Cheapest paid fallback, if the card problem never resolves:**
   Render Standard backend + disk ~$25/mo — but it also needs a card,
   so it does not solve a no-card situation; it only solves the
   "free tier is too small" problem. There is no permanent no-card
   paid route either: every paid host bills a card (or PayPal).

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

Default deployment ($0, **no card anywhere**):

- **Backend + frontend:** Render free (both services, `render.yaml`)
  — $0. Transcription runs on **Groq's free Whisper API** (free key,
  no card, 8 h audio/day). The low-memory switches are on by default
  in the blueprint: `TRANSCRIPTION_PROVIDER=groq`,
  `RENDER_PRESET=ultrafast`, `FACE_TRACKING=0`.
- **Scoring:** built-in heuristic — $0. **YouTube metadata:** YouTube Data
  API free quota, 10,000 units/day — $0. **yt-dlp:** optional,
  own-videos-only, $0.
- **Database that survives restarts (optional):** free Neon Postgres
  (0.5 GB, 100 CU-hours/mo, no card, no expiry) — paste the URL into
  `DATABASE_URL`. Without it, accounts live in SQLite and are lost on
  every Render restart/sleep.
- **Oracle Always Free VM is now Appendix D, not the default** — it is
  still the best free path for anyone WITH a Visa/Mastercard
  (full local pipeline, no third-party API, no 512 MB squeeze), but
  **this user cannot use it**: Oracle rejected his RuPay card and he
  cannot get a Visa/Mastercard (see "No card? The RuPay problem"
  above).

**Honest limits of the $0 path (see `DEPLOYMENT.md`):**

- No SLA anywhere; free tiers can change or be withdrawn.
- Render free is **512 MB and tight**: the measured job peak is
  388 MB (~124 MB headroom). Longer videos near the 5-minute cap can
  still push it over — start with short videos.
- Render free sleeps after 15 idle minutes and has no persistent disk:
  everything is lost on restart unless Neon Postgres is set (and even
  then, uploaded videos/clips are lost — only accounts/projects
  survive).
- The free path trades quality for fit: `ultrafast` renders and a
  centre crop instead of face-following. Groq's free tier can change;
  if it does, jobs fail with a clear message (nothing is faked).
- Whisper runs remotely (Groq) instead of on CPU here, so
  transcription itself is fast — the slow part on Render free is the
  FFmpeg render on a small shared CPU. Keep test videos short first.
- Vercel Hobby (the frontend alternative in Appendix D) is
  non-commercial — the moment the app earns money (ads, payments,
  paid plans), Vercel requires Pro ($20/mo/seat).
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
2026) were checked again 2026-11-16. **No-card re-check 2026-11-16:**
Hugging Face's own Spaces docs (`huggingface.co/docs/hub/spaces-overview`,
crawled 2026-11-16 — PRO required to create a Gradio/Docker Space, free
ZeroGPU is Gradio-only); Railway's pricing page + Oct 21, 2026 incident
report (Nov 10, 2026 update — trial deploys "temporarily unavailable" for
new customers at the Nov 2 reopening); Northflank pricing page vs billing
docs (contradictory card requirement); RuPay domestic-only acceptance
(moneyview, Motilal Oswal, calendar-uk comparisons — "ask your bank to
provide a Visa or MasterCard debit card"); Replit / PythonAnywhere /
Glitch / Komuta free-tier limits (Sep–Nov 2026 comparisons). **Groq
free-tier re-check 2026-11-16:** Groq's own Speech-to-Text docs
(`console.groq.com/docs/speech-to-text` — free plan, word-level
`timestamp_granularities`, 25 MB/file) and its rate-limits page via
secondary sources quoting it (20 RPM, 2,000 RPD, 7,200 audio sec/hour,
28,800/day; no card, no end date). **Zeabur 2026-11-16:** free plan
verified no-card but manages only a server you own — the shared
cluster closed to new projects March 2026, so no hosted free compute.
**Streamlit Community Cloud 2026-11-16:** Streamlit apps only, ~1 GB
RAM, sleeps after 12 h — cannot run a FastAPI backend. **Memory
measurements 2026-11-16:** measured on this VM with concurrent RSS
sampling (see `TESTING.md`) — render child 418 MB (`veryfast`) /
210 MB (`ultrafast`) at 1080x1920, face tracker ~180 MB in-process,
`malloc_trim` ~50 MB back, full-job peaks 721 MB (default) / 569 MB
(`ultrafast`) / 388 MB (all low-memory switches). Re-check before
deploying — free tiers and trial availability change without notice.
