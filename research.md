# MMSN Clipper — Phase 1 Component Research

**Project:** AI-powered long-form → Shorts/Reels/TikTok clipper SaaS (local project)
**Date:** 2026-11-16
**Scope:** Research only. No code written, no GitHub pushes, no YouTube downloads.
**Method:** `browser.search` + `browser.open` (README/docs pages) for each component below.
Checked: what it does, maintenance activity, license / commercial-use compatibility,
main dependencies, security / performance concerns.

> **Standing decisions (do not revisit without the user):**
> - **No pushing to GitHub** without explicit approval.
> - **No downloading YouTube videos** as the default ingestion path.
>   User upload is the safe primary path; YouTube Data API v3 metadata is the
>   link-paste path. yt-dlp, if ever used, is only an optional, clearly-labelled
>   path for videos the user owns or has explicit permission to use — see §12.
> - Ingestion is upload-based + YouTube Data API metadata only.

**Verdict key:** ✅ Adopt · ⚠️ Adopt with caution · ❌ Reject / do not use as planned

---

## 1. FFmpeg — video processing (decode / encode / cut / crop / burn-in)

| Field | Finding |
|---|---|
| What it does | CLI + `libav*` C libraries: decode, encode, transcode, mux/demux, filter, stream virtually every A/V format. The render backbone for almost every other tool in this list. Also `ffprobe` for metadata/duration. FFmpeg 8.0 added a built-in Whisper subtitle filter. |
| Maintenance | Very active. 8.0 "Huffman" released Aug 2025; 9.x branch appearing in late-2026 sources (9.0.1/9.0.2 reported Sep–Nov 2026 — treat the exact 9.x point release as "verify at build time"). ~57k+ GitHub stars, ~2,400 contributors, 25 years old. |
| License | **LGPL 2.1+ by default; GPL if optional GPL components are enabled.** Core is LGPL. Enabling e.g. libx264 / libx265 / libfdk-aac makes the whole build GPL. |
| Dependencies | None (self-contained C). Optional external codec libs depending on build. |
| Risks / concerns | **Licensing trap is the main risk, not the code.** A stock distro/Gyan build is typically GPLv3 (includes x264/x265). For a commercial product, use an **LGPL build** (e.g. BtbN LGPL variant, or a custom `--disable-gpl --disable-version3 --disable-nonfree` build) and accept no x264/x265 in that build — or keep FFmpeg server-side only and take legal advice. Separate issue: H.264/H.265 **patent** licensing is independent of FFmpeg's copyright licence. Security: FFmpeg has a steady stream of CVEs in decoders — pin a recent release and update it; never feed it untrusted files without sandboxing/timeouts. Performance: native C, multithreaded; the fastest option in this list. |
| **Verdict** | ✅ **Adopt — as the render engine, via direct subprocess calls.** Pin a recent LGPL build; document the exact build/flags in the repo. |

## 2. faster-whisper (and OpenAI Whisper) — speech-to-text with word timestamps

| Field | Finding |
|---|---|
| What it does | faster-whisper (SYSTRAN/faster-whisper) is a re-implementation of OpenAI Whisper on the CTranslate2 inference engine: ~4× faster than reference Whisper at the same accuracy, less memory, batched inference, Silero VAD filter, `word_timestamps=True` for per-word start/end times. OpenAI Whisper itself is the underlying model (tiny → large-v3-turbo, 39M–1,550M params). |
| Maintenance | Active. faster-whisper **v1.2.1 (31 Oct 2025)** on PyPI; last push reported Oct 2026; ~26k stars. OpenAI Whisper latest changelog entry v20250625 (Jun 2025). |
| License | **MIT** — faster-whisper code, CTranslate2, and OpenAI Whisper code **and model weights** are all MIT (HF large-v3 card is tagged Apache 2.0 in one place — either way permissive/commercial OK). Keep the copyright notice. |
| Dependencies | Python ≥3.9, CTranslate2, PyAV (bundles FFmpeg libs — no system FFmpeg needed for transcription). CUDA 12 for GPU; CPU works (int8). Models download from Hugging Face on first run (large-v3 ~3 GB; small ~490 MB). |
| Risks / concerns | Word timestamps from Whisper alone are **interpolated and drift** (typically 0.2–0.7 s early at segment starts; worse after pauses) — for karaoke-style captions prefer WhisperX forced alignment (§8) or add a Silero-VAD snap correction. No SRT writer in the library — format output yourself. `av<19` pin reported: PyAV 19 broke faster-whisper 1.2.1 on fresh installs (Oct 2026) — pin PyAV. Model download size / first-run latency; GPU strongly recommended for long videos. |
| **Verdict** | ✅ **Adopt — faster-whisper as the default transcriber** (`base`/`small` for speed, `large-v3-turbo` for accuracy; `word_timestamps=True`, `vad_filter=True`). |

## 3. PySceneDetect — scene detection

| Field | Finding |
|---|---|
| What it does | Python library + CLI that finds scene cuts/transitions (ContentDetector, ThresholdDetector, AdaptiveDetector) and can hand the scene list to FFmpeg/mkvmerge to split. Used to snap clip boundaries to real cuts and to reset face-tracking at cuts. |
| Maintenance | Very active. **v0.7.3 (8 Nov 2026)**, v0.7.2 (Oct 2026), v0.7 (May 2026); last push ~Nov 2026; ~5.2k stars. |
| License | **BSD-3-Clause** — permissive, commercial OK with attribution. |
| Dependencies | `opencv-python` (or `opencv-python-headless` via the `scenedetect-headless` package — use headless on servers), NumPy, Click, tqdm. PyPI package name is `scenedetect`. |
| Risks / concerns | Cut detection is threshold-based, not semantic: fast cuts / flashes / fades can false-positive; slow dissolves can be missed. Tune `threshold` per content type and validate on real footage. CPU cost is modest (frame differencing). Note older PyPI classifiers misleadingly say MIT — the repo LICENSE is BSD-3-Clause. |
| **Verdict** | ✅ **Adopt — for cut detection / boundary snapping.** Use `scenedetect-headless`. |

## 4. OpenCV — face detection / visual analysis

| Field | Finding |
|---|---|
| What it does | The standard computer-vision library: image/video I/O, filtering, DNN inference (`cv2.dnn`, `cv2.FaceDetectorYN`), tracking, motion saliency. In this pipeline: frame sampling + face detection for 9:16 reframing, plus thumbnail/blur-background work. |
| Maintenance | Very active. Stable **4.12.0 (2 Jul 2025)**; 4.13.0 in distro builds Jul 2026. Decades-old, Intel-origin, OpenCV Foundation maintained. |
| License | **Apache 2.0 (v4.5.0+)**; ≤4.4.0 was BSD-3-Clause. Either way permissive/commercial OK. **But check each DNN model separately:** YuNet model is MIT; Haar cascades ship with the library under Apache 2.0. |
| Dependencies | NumPy; `opencv-python-headless` for servers (no GUI deps). YuNet ONNX model from `opencv_zoo` (~300 KB, bundle it and pin its SHA-256). |
| Risks / concerns | Haar cascades are legacy (2001 Viola-Jones) — inaccurate on profile/turned faces; do not use for new work. YuNet (`cv2.FaceDetectorYN`) is the current lightweight choice: WIDER FACE hard ≈75, MIT, CPU-fast. No person segmentation built in. Heavyweight if imported just for face boxes — but PySceneDetect already pulls OpenCV in, so marginal cost is ~zero here. |
| **Verdict** | ✅ **Adopt — OpenCV (headless) + YuNet for face detection.** See §10 for the reframing design. |

## 5. MoviePy — video editing

| Field | Finding |
|---|---|
| What it does | Python library for programmatic editing: cuts, concatenation, compositing, titles, effects. Wraps FFmpeg via imageio-ffmpeg; Python 3.9+. |
| Maintenance | Alive but slow-moving. **v2.2.1 (21 May 2025)** is the latest release; ~15k stars; v2 (2024) was a breaking rewrite — v1 API is unmaintained and old tutorials (`moviepy.editor`, `subclip()`, `set_*`) fail on v2. Recent activity is mostly maintenance/docs/dependency fixes. |
| License | **MIT** — commercial OK. |
| Dependencies | NumPy, Pillow, imageio + imageio-ffmpeg (bundles an FFmpeg binary), decorator, proglog. TextClip needs ImageMagick on some setups. |
| Risks / concerns | **Performance is the problem.** MoviePy decodes frames to NumPy arrays in Python and re-encodes everything: widely reported 3–4× slower than direct FFmpeg, up to 10–100× slower for stream-copy-able operations, with documented memory leaks / zombie FFmpeg subprocesses on long batch jobs (issues #1284, #1508, #1535, #1892; one adversarial review calls it "unsuitable for a production pipeline" — that review is hostile, but the underlying issues are real and long-standing). Audio desync on concatenation is also reported. Fine for prototyping / one-off scripts; a liability as the render core of a SaaS. |
| **Verdict** | ⚠️ **Adopt with caution — prototyping / simple compositing only. Do NOT make it the render core.** Production cuts, crops, caption burns and concatenation go through direct FFmpeg commands (or `ffmpeg-python`/PyAV). Revisit only if a v2.x release demonstrably fixes the memory/subprocess issues. |

## 6. Auto-Editor — automatic editing

| Field | Finding |
|---|---|
| What it does | CLI that automatically cuts silence / dead space (audio loudness, motion, or subtitle-based) and exports the result or an NLE timeline (Premiere, Resolve, Final Cut, Kdenlive). One command: `auto-editor video.mp4`. |
| Maintenance | Very active. **v31.7.2 (3 Oct 2026)**; ~5.5–5.9k stars; commits within days of checking. **Rewritten from Python to Nim (v30+, ~99.7% Nim)** — this is a compatibility flag, not a bug. |
| License | **The Unlicense (public domain)** for the CLI — no commercial restriction. Note: the paid GUI at app.auto-editor.com is a *separate* proprietary product (from $23.99; $179 Studio tier for a commercial-use GUI licence) — the CLI itself needs none of that. |
| Dependencies | None for the binary (GitHub Releases / Homebrew / Arch AUR). **No longer published on PyPI** — `pip install auto-editor` silently installs a stale v29-era build. Optional yt-dlp for URL inputs (we will not use that path). |
| Risks / concerns | Cuts on **loudness/motion thresholds, not meaning** — it cannot tell a strong moment from a weak one, remove filler words by name, add captions, or reframe to vertical. Nim rewrite means it is a black-box binary to integrate (subprocess, not a Python import). Useful as a *pre-pass* (silence trimming) or as a reference implementation, not as the clip-selection brain. |
| **Verdict** | ⚠️ **Adopt with caution — optional silence-trim pre-pass only, via the release binary (never pip).** Do not build clip selection on it. |

## 7. Remotion — programmatic video

| Field | Finding |
|---|---|
| What it does | React framework for building videos as code: scenes are React components rendered frame-by-frame in a headless browser, stitched by FFmpeg underneath. Great for templated motion graphics, titles, progress bars, audiograms — not for editing camera footage. |
| Maintenance | Active, commercial company behind it. v5.0 current (2026); renders locally, via CLI, SSR API, or AWS Lambda. |
| License | ⚠️ **NOT open source — source-available under Remotion's own licence.** Free for individuals, non-profits, and companies of **up to 3 people** (unlimited commercial use in that band). At 4+ people a Company Licence is required: Creators $25/seat/month, **Automators $0.01/render with $100/month minimum** (an automated clipper SaaS is squarely "Automators"), Enterprise from $500/month. Eligibility is by **total company headcount**, not just Remotion users. Telemetry mandatory for Automators in v5.0. |
| Dependencies | Node.js, React, FFmpeg, headless Chrome. |
| Risks / concerns | **Licence cost scales with renders** ($0.01/render, $100/mo floor) — fine at prototype scale, a real line-item at SaaS scale. Headless-browser rendering is heavier than pure FFmpeg for simple overlays. Vendor lock-in on the licence terms. |
| **Verdict** | ⚠️ **Adopt with caution — only for templated graphics (titles, progress bars, hooks) and only while the team is ≤3 people.** Defer the decision; the same overlays can be done with FFmpeg `drawtext`/ASS subtitles at zero licence cost. Budget the Automators tier before any production commitment. |

## 8. Speaker diarization — pyannote.audio (and WhisperX)

| Field | Finding |
|---|---|
| What it does | pyannote.audio is the open-source standard for "who spoke when": VAD → segmentation → speaker embeddings → clustering, outputting a speaker timeline. WhisperX (m-bain/whisperX) bundles faster-whisper + wav2vec2 forced alignment + pyannote into one pipeline: accurate word timestamps **and** speaker labels per word. |
| Maintenance | Active. pyannote.audio 3.x/4 (2026); WhisperX **v3.8.6 (25 May 2026)**, ~24k stars, last push Aug 2026. |
| License | ⚠️ **Split licence — read carefully.** pyannote.audio **code is MIT**. The **model weights are separate and gated on Hugging Face**: `pyannote/speaker-diarization-3.1` + `pyannote/segmentation-3.0` are MIT but gated (accept terms + HF token; both pages must be accepted — missing the segmentation one gives an opaque 401); the newer `pyannote/speaker-diarization-community-1` weights are **CC-BY-4.0** (commercial OK **with attribution**), also gated, and require sharing contact info / agreeing to occasional emails. WhisperX code is **BSD-2-Clause**; its alignment models have their own terms. |
| Dependencies | PyTorch (large), torchaudio/torchcodec, FFmpeg (audio decode), Hugging Face token. GPU strongly recommended; CPU works but slow. Never bundle the gated weights — each user/deployment must accept the terms with its own HF account/token. |
| Risks / concerns | Diarization adds a second model pass, more VRAM, and a **first-run failure mode** (the HF gate) that looks like a code bug. Accuracy is good but not perfect (DER ~9–19% depending on dataset); multi-speaker panels benefit most. **For single-speaker talking-head videos diarization adds cost for zero benefit — make it optional / detect speaker count first.** |
| **Verdict** | ⚠️ **Adopt with caution — via WhisperX, as an optional stage.** Default path: faster-whisper only. Enable diarization only for multi-speaker content, with the HF token + accepted terms documented in setup, and attribution for CC-BY-4.0 weights. Alternative to evaluate later: SpeechBrain (also used by some reframe pipelines) — not yet assessed for licence/accuracy. |

## 9. Subtitle / caption tooling — ASS subtitles, word timestamps, auto-caption libraries

| Field | Finding |
|---|---|
| What it does | Pipeline: faster-whisper/WhisperX word timestamps → group words into short captions (≤3–4 words, break on punctuation / pauses >0.6 s) → write **Advanced SubStation Alpha (.ass)** with one Dialogue event per word and karaoke-style `{\c}` highlight overrides → burn in with FFmpeg's `ass`/`subtitles` filter (**libass**). Sidecar SRT/VTT for platforms/editors. |
| Maintenance | libass/FFmpeg: actively maintained (see §1). Small caption helper repos exist (e.g. `whisper-word-captions`, MIT; `sebetancurch/auto-caption`, MIT) — useful as **reference implementations**, not dependencies. WhisperX for alignment: §8. |
| License | **No licence problem:** ASS is a format, libass is ISC-licensed, FFmpeg's `ass` filter is LGPL. Caption helper scripts are MIT where checked. |
| Dependencies | FFmpeg built **with libass** (check with `ffmpeg -h filter=ass`; Homebrew's `ffmpeg-full` / Gyan builds include it; `imageio-ffmpeg`'s bundled binary may not — verify). A real font file installed on the system — libass **silently substitutes a fallback font** if the named font is missing (most common cause of ugly burns). |
| Risks / concerns | Burned-in ASS cannot render colour emoji; box + outline together need a two-pass burn (libass limitation). Font licensing: bundle fonts under SIL OFL (e.g. Inter/Anton) and ship the licence. Caption timing drift (§2) — snap to VAD or use WhisperX alignment. `PlayResX/PlayResY` must match the video (1080×1920 for Shorts) or sizing breaks. |
| **Verdict** | ✅ **Adopt — own the caption generator (small Python module), render with FFmpeg + libass.** Do not depend on a third-party auto-caption repo; copy the pattern, not the dependency. |

## 10. Smart cropping / face-tracking for 9:16 reframing

| Field | Finding |
|---|---|
| What it does | Reframe landscape → 1080×1920 by tracking the speaker's face and moving a 9:16 crop window. Established pattern (used by SmartSplit, ClipCup, several 2026 local clipper builds): sample face position a few times/sec → smooth the path (EMA / zero-phase / One-Euro filter, with a max-displacement clamp) → reset instantly at scene cuts → fall back to centre crop when no face is found. Two framing policies: **fit** (letterbox full frame + blurred background — nothing is cut off) vs **crop** (fill frame, follow face — better for talking-head, worse for slides/two-person shots). |
| Maintenance | Components are the maintained ones above (OpenCV, PySceneDetect, FFmpeg). No single "smart crop" library to adopt — this is a small module we write. |
| License | **Clean, if we use the right detector.** OpenCV YuNet model: **MIT**. MediaPipe BlazeFace + Face Landmarker: **Apache 2.0** (code and model card), commercial OK. Avoid OpenPose (licence restricts commercial use) and Haar cascades (inaccurate). Note: MediaPipe Tasks APIs send performance/utilisation metrics to Google — consent obligation is on us; and MediaPipe Solutions are labelled early-preview with no SLA. |
| Dependencies | OpenCV + YuNet ONNX (bundled, SHA-pinned) *or* MediaPipe (`mediapipe` PyPI, Apache 2.0). MediaPipe publishes **no Python 3.13 wheels** (reported by at least one clipper project) — pin Python 3.11/3.12 if MediaPipe is chosen. SciPy/NumPy for smoothing. |
| Risks / concerns | Raw per-frame detections jitter badly when zoomed into a 9:16 crop — **smoothing is not optional**. Two faces / active-speaker switching needs diarization + active-speaker detection to do well (v2 feature, not v1). Face detection ≠ face recognition: we track boxes, we do not identify people — keep it that way (privacy). |
| **Verdict** | ✅ **Adopt — build it ourselves on OpenCV YuNet (MIT) + PySceneDetect cut resets + FFmpeg `crop`.** MediaPipe BlazeFace (Apache 2.0) is the approved fallback/alternative. Default framing policy: `fit` (blurred background) with `crop` as an option for talking-head. |

## 11. YouTube Data API v3 — metadata only

| Field | Finding |
|---|---|
| What it does | Official Google API for **metadata**: video title/description/duration, channel, thumbnails, captions metadata, search, playlists, and (with OAuth + ownership) uploading. It returns **no video bytes and no download URL** — it cannot fetch video content, by design. |
| Maintenance | Actively maintained by Google; quota rules changed twice in 2025–26 (see below) — re-check the official quota calculator at build time. |
| License / cost | **Free, $0 per call — but quota-capped, and quota cannot be bought.** Default per project: **10,000 units/day** for most endpoints, with separate buckets reported since Jun 2026 of **100 search.list calls/day** and **100 videos.insert calls/day**. Costs: `videos.list` / `channels.list` **1 unit** (up to 50 items/call → ~500k videos/day of metadata), `search.list` **100 units**, most writes 50 units, `captions.download` 200 units. Upload cost changed Dec 2025 (1,600 → ~100 units) and again Jun 2026 (own bucket, 1 unit/call, 100/day) — sources disagree on the exact current figure, **verify against developers.google.com/youtube/v3/determine_quota_usage**. Quota resets midnight Pacific; failed calls still cost ≥1 unit; exceeding quota → 403 `quotaExceeded`. More quota only via the manual Audit/Quota Extension form (weeks, not guaranteed). API use is governed by the YouTube API Services Terms of Service + Developer Policies (including an audit/compliance review for production apps). |
| Dependencies | Google Cloud project + API key (or OAuth for uploads / private data). |
| Risks / concerns | **Search is the quota bottleneck** (100 searches = the whole day). Architecture must be ID-first: extract the video ID from the pasted URL (no API call), then `videos.list` at 1 unit. Never use `search.list` in a hot path. Quota exhaustion is a hard failure with no paid escape hatch — design caching + graceful degradation. Do not store API keys client-side. |
| **Verdict** | ✅ **Adopt — for the link-paste path only: title/duration/thumbnail/channel via `videos.list`.** This is the *only* YouTube touchpoint in the default flow. It does not, and cannot, download video. |

## 12. yt-dlp — the standard open-source downloader (EVALUATED IN FULL, 2026-11-16)

| Field | Finding |
|---|---|
| What it does | Feature-rich CLI audio/video downloader, fork of youtube-dl (based on the now-inactive youtube-dlc). Downloads video/audio from **YouTube and thousands of other sites** (supportedsites.md lists 1,000+), with format/quality selection, merging separate video+audio streams, audio extraction, subtitles, thumbnails, playlists, SponsorBlock, and a Python embedding API. The standard tool for this job — every open-source clipper in §13 uses it or an equivalent. |
| Maintenance | **Very actively maintained.** Repo: github.com/yt-dlp/yt-dlp — **208,162 stars, 18,359 forks, 24,040 commits, 138 releases** (checked 2026-11-16; ~199k stars was the figure circulating a few weeks earlier, so it is still growing fast). Created 2020-10-26, not archived. Latest stable reported **2026.10.26** (Python 3.11+ minimum; 3.10 support removed). Three release channels: `stable` (monthly, often stale), **`nightly` (recommended by the maintainers)**, `master` (canary, may regress). Versions older than 90 days print an update warning. |
| License | **The Unlicense (public domain)** for the source (git repo, PyPI sdist/wheel). ⚠️ **Packaging caveat, from the README's own Licensing section:** PyInstaller-bundled executables contain GPLv3+ code, so the combined binary is **GPLv3+**; the zipimport Unix binary / tarball also contain ISC-licensed `meriyah` and MIT-licensed `astring`. See `THIRD_PARTY_LICENSES.txt`. If we ever ship a binary, use the source/PyPI form or take advice — do not assume "Unlicense" covers the binary. |
| Dependencies | Python **3.11+**. `pip install yt-dlp` alone installs almost nothing (`dependencies = []` in pyproject.toml) — the useful pieces are extras: **`yt-dlp[default]`** pulls brotli, certifi, mutagen, pycryptodomex, requests, urllib3, websockets, **yt-dlp-ejs**. Strongly recommended / effectively required: **ffmpeg + ffprobe binaries on PATH** (merging, post-processing; the *binary*, not the PyPI package named `ffmpeg`; yt-dlp publishes its own FFmpeg builds), **yt-dlp-ejs + a JS runtime** — **Deno (recommended, default, ≥2.3; `deno` pip extra ships Deno ≥2.6.6)**, or Node ≥22 / Bun / QuickJS via `--js-runtimes` (only Deno is enabled by default — a deliberate security choice). Optional: `curl_cffi` for browser impersonation (TLS fingerprinting), `mutagen`/`AtomicParsley` for thumbnail embedding, `secretstorage` for `--cookies-from-browser`. |
| Security / robustness | **Extractors break often — this is the defining operational fact.** YouTube changes its player / JS challenges regularly; since release **2025.11.12** full YouTube support *requires* an external JS runtime to solve the player's `n` challenge (yt-dlp-ejs runs YouTube's challenge JS). Without it, formats go missing or downloads fail. The README itself warns stable releases are "often stale and prone to external breakage". Mitigations: pin a version, track `nightly`, budget for breakage windows, surface clear errors. **Security notes:** (1) `--remote-components ejs:github/npm` lets yt-dlp fetch remote JS challenge-solver code — that is remote code execution by design; it is **off by default**, enable deliberately if at all. (2) `curl_cffi` impersonation and `--cookies-from-browser` (reads browser cookies / OS keyring) raise account-security and ToS questions — avoid both in a server product. (3) A secondary source reports release 2026.06.09 fixed three security issues — not verified against the primary changelog here; check the changelog before pinning. (4) Plugin system / `--update-to <other-repo>` can pull unverified code — never enable in production. (5) Never run it on untrusted URLs without timeouts, size caps, and sandboxing — a URL is user input. |
| The legal point (the reason for the verdict) | The **tool** is lawful open-source software (cf. the 2020 youtube-dl/RIAA takedown, reversed after the EFF showed substantial non-infringing uses; yt-dlp itself circumvents no DRM). **The use is what matters.** YouTube's Terms of Service ("Permissions and Restrictions") prohibit accessing, reproducing, downloading or distributing content except where the Service expressly authorises it or YouTube gives prior written permission. Downloading someone else's copyrighted video with yt-dlp **violates YouTube's ToS** (remedy: account action / civil claim, not criminal) and, separately, can be **copyright infringement** by the downloader. Defensible uses are narrow: your own uploads, Creative Commons (CC BY) videos with attribution, public-domain material, or content you have written permission to process. Building a commercial SaaS whose default flow downloads arbitrary third-party YouTube videos would put the product (and its users' accounts) at odds with the platform it depends on. |
| **Verdict** | ⚠️ **ADOPT WITH STRICT GUARDRAILS — optional ingestion path ONLY, never the default.** Conditions, all of them: (1) **User upload stays the safe primary path; YouTube Data API metadata (§11) stays the link-paste path.** (2) yt-dlp may only ever be an **optional, clearly-labelled** ingestion path for videos **the user owns or has explicit permission to use** — with that condition shown in the UI and an ownership/permission confirmation before any download. (3) **Never the default for arbitrary YouTube links; never for other people's copyrighted videos.** (4) If implemented, pin a version, use `yt-dlp[default,deno]`, keep ffmpeg/deno current, no `--cookies-from-browser`, no remote-components by default, no impersonation extras unless reviewed. (5) **Testing rule: do not test it with any real download of a video the user does not own — metadata listing only (`--simulate` / `--get-title` style, no download), or not at all.** (6) Revisit with the user before shipping this path at all. |

---

## 13. AI video-clipping repos — reuse vs build our own?

Searched "AI video clipping long form to shorts open source github". Three credible candidates:

### a) autoclip — github.com/zhouxiaoka/autoclip — **closest to our product**
- **What:** Open-source AI clipper (Python desktop app + CLI + MCP + Docker web UI). Paste a link → transcript → LLM picks highlights → renders platform-ready clips (Shorts/TikTok/Reels/Douyin/Bilibili) with subtitles, covers, publish copy. Up to 10 top-ranked clips per run.
- **Licence / maintenance:** **MIT**, ~10.5–11k stars, 1,852 forks, last push within ~12 hours of checking (late Oct 2026), latest release v1.5.7 (24 Oct 2026). Very active, incl. GitHub Trending appearances.
- **Stack:** Python 3.10+, FFmpeg, LLM via Qwen / OpenAI-compatible / Gemini / SiliconFlow / Ollama / LM Studio (own keys). Reported real-world run: 1h43m interview → 10 clips in 7.5 min.
- **Caveats:** Built around **link ingestion (YouTube/Bilibili) via yt-dlp** — exactly the path we are restricting. Subtitle-only scoring in some paths (weak on music/gameplay/no-dialogue video); no frame-level visual analysis in the core scoring. Chinese-first project (docs in Chinese + English README).
- **Verdict:** **Best reference architecture; do not fork wholesale.** Study its pipeline (transcript → LLM scoring → FFmpeg render), its clip-ranking prompts, and its export presets. Our differentiator and our legal posture (upload-first, no default YouTube download) differ enough that a fork would carry its ingestion assumptions with it.

### b) OpenShorts — github.com/mutonby/openshorts — **worth a look, younger**
- **What:** "Open-source OpusClip alternative": Clip Generator (long video → ranked 9:16 shorts), AI Shorts (UGC with AI actors), YouTube Studio. AI moment detection, face tracking, subtitles, dubbing. Self-host free with Docker, or hosted cloud from $12/mo. MCP server + API.
- **Licence / maintenance:** **MIT**, created 19 Dec 2025 — very young. Passed ~5,600 stars by late Oct 2026.
- **Caveats:** Youngest of the three; hosted-cloud upsell means the self-host path may lag; "AI moment detection" internals less documented than autoclip's. Default mode reportedly needs a paid MuAPI key for download/transcription/cropping; `--mode local` needs FFmpeg + OpenAI/Gemini key.
- **Verdict:** **Watch, don't adopt yet.** Re-check in a few months; if it matures, its face-tracking + MCP/API surface could be worth borrowing ideas from.

### c) SupoClip — github.com/FujiwaraChoki/supoclip — **cleanest licence story, copyleft catch**
- **What:** Paste a YouTube link or upload → transcribe (local Whisper or AssemblyAI) → LLM picks self-contained moments → renders 9:16 clips with word-synced captions, face-aware reframing, hook titles. Docker Compose self-host; BYO AI (OpenAI/Google/Anthropic/OpenRouter/Ollama). Hosted plans $10–50/mo.
- **Licence / maintenance:** **AGPL-3.0** — the copyleft catch: if we run a modified version as a network service, we must offer the source. That is compatible with an open product, but it constrains a closed SaaS. Active (Show HN, Oct 2026).
- **Caveats:** Same yt-dlp link-ingestion assumption as autoclip. CPU-only Whisper is slow on long videos (their own note).
- **Verdict:** **Do not fork (AGPL-3.0 + same ingestion model).** Useful as a second reference for the caption/reframe implementation.

### Overall reuse verdict
**Build our own pipeline; borrow patterns, not codebases.** None of the three matches our
ingestion posture (upload-first, Data-API metadata, yt-dlp only as a gated optional path),
and each would import its own licence/ingestion assumptions. The reusable ideas: autoclip's
transcript→LLM-score→rank→render loop and export presets; SupoClip's face-aware reframe +
word-synced captions; OpenShorts' MCP/API shape. All three confirm the same stack we
independently selected: **FFmpeg + faster-whisper/WhisperX + LLM scoring + libass captions**.

---

## 14. Reuse sweep, 2026-11-16 (user: "use every repo which helps, broadly")

Second pass over the categories the first pass left as "build ourselves":
transcription timestamps, auth, queues, storage, timeline UI, deployment.
Rule applied: integrate only what actually works in our pipeline — a listed
dependency that never runs is worse than no dependency.

### Integrated in this sweep

| Component | Verdict | What changed |
|---|---|---|
| **OpenCV YuNet** (`face_detection_yunet_2023mar.onnx`, OpenCV Zoo) | ✅ **Adopted — now wired, not a hook.** MIT model. Pinned revision + SHA-256 verified on download (232,589 bytes, SHA `8f2383…2552fa4`); loads and runs on OpenCV 5.0. Model is NOT committed — downloads on first use into `backend/pipeline/models/` (gitignored). | `pipeline/reframe.py`: 2 fps sampling, largest-face wins, EMA smoothing + max-step clamp, instant reset at PySceneDetect cuts, per-scene-cut segment crops in `render.py`. Falls back to centre crop with a warning whenever the model/detector/no-face is missing. |
| **wavesurfer.js v7** (katspaugh/wavesurfer.js) | ✅ **Adopted — editor waveform.** BSD-3-Clause (v6.6.3+ header; older README text says CC-BY 3.0 — the npm package ships BSD-3-Clause). Actively maintained (v8 current; we pin v7.9.0, the API we verified). | Editor page: decodes the clip's audio, renders the waveform, tap-to-seek moves the video playhead, playhead follows video playback. Needs CORS from the backend (already configured). |
| **python-dotenv** | ✅ **Adopted.** BSD-3-Clause. | `.env` is now actually loaded (`load_dotenv()` in `config.py`) — before this sweep the README told users to create `.env` but nothing read it. |
| **fastapi-users 15.0.0** | ⚠️ **Chosen for Phase 2 auth, NOT wired yet.** MIT, maintained, JWT + OAuth2 + registration out of the box, fits our SQLAlchemy models. Wiring half of auth in Phase 1 would be fake multi-user functionality, so it stays a documented decision (see ARCHITECTURE.md §2) until the auth phase. Alternatives seen: `fauth` 3.0.0, `fastapi-myauth` 1.7.0, `pyallauth` 0.1.0 — all MIT, all younger/smaller than fastapi-users. | None in code yet. |
| **stable-ts** (jianfch/stable-ts) | ❌ **Evaluated, rejected for Phase 1.** MIT, supports faster-whisper (`load_faster_whisper` + `transcribe_stable`), silence suppression genuinely improves word timestamps. **But:** `pip install --dry-run` shows it pulls **torch 2.15 + torchaudio + a CUDA toolkit** — gigabytes, and it breaks the light CPU-only Phase 1 (and free-tier hosting). Keep faster-whisper native word timestamps; WhisperX stays the later alignment upgrade (same torch caveat). Revisit only if we accept a torch-based worker image. | None. Documented here + ARCHITECTURE.md. |
| **Full timeline-editor apps** (designcombo/react-video-editor, openvideodev/react-video-editor, mohebifar/tooscut, MartinDelophy/ai-video-editor) | ❌ **Evaluated, not adopted as wholes.** These are complete editor applications (Remotion/Fabric.js/Konva canvas timelines, Zustand stores). Forking one would import its whole rendering model and licence stack (designcombo's is Remotion-based — see the Remotion licence note) for an editor that is still a skeleton in Phase 1. We borrow the *pattern* (waveform + tap-to-seek timeline) via wavesurfer.js instead. **Rescript** is explicitly rejected: **PolyForm Noncommercial 1.0.0** — not commercial-compatible. | None. |
| **ffmpeg-python** | ❌ **Evaluated, rejected.** MIT wrapper around the FFmpeg CLI. Adds a dependency and an abstraction layer for commands we already issue directly and need full control over (per-segment crop expressions, concat, libass escaping). Direct subprocess stays. | None. |
| **boto3 / S3 storage** | ⚠️ **Evaluated, deferred.** Apache 2.0, the obvious production storage choice. Not integrated: an S3 helper with no credentials to test against would be untested, untestable-here code — the guardrail says a reused component must actually work, not just be listed. Add it with the Postgres/Redis production step, tested against a real bucket. | None yet; `UPLOAD_DIR`/`MEDIA_DIR` local storage stays. |
| **Celery + Redis** (queues) | ⚠️ **Deferred, unchanged.** The in-process queue stays for Phase 1; Celery is the documented Phase 2 path (ARCHITECTURE.md §5). | None. |
| **yt-dlp** | Unchanged — §12 guardrails stand. | None. |

## Recommended component per pipeline stage

| Stage | Recommended | Runner-up / note |
|---|---|---|
| Ingest (primary) | **User upload** (local file) | — |
| Ingest (link paste) | **YouTube Data API v3** `videos.list` — metadata only | Never `search.list` in a hot path (100 units) |
| Ingest (optional, gated) | **yt-dlp** — only for owned/permissioned videos, clearly labelled, never default | Pin version + `yt-dlp[default,deno]`; metadata-only testing |
| Audio extraction | **FFmpeg** (`-vn -ac 1 -ar 16000`) | — |
| Transcription | **faster-whisper** (`word_timestamps=True`, VAD) | WhisperX when word accuracy matters |
| Word alignment + diarization | **WhisperX** (wav2vec2 alignment + pyannote) — optional stage | Diarization only for multi-speaker |
| Scene / cut detection | **PySceneDetect** (headless) | — |
| Clip selection / scoring | **LLM over transcript text only** (never send video/audio to the LLM) + heuristic scorer (silence, energy, hook) | autoclip's ranking prompts as reference |
| Silence trimming | **Auto-Editor** binary (optional pre-pass) | Or VAD-based trimming in our own code |
| Face tracking / 9:16 reframe | **Own module: OpenCV YuNet + smoothing + PySceneDetect cut resets** | MediaPipe BlazeFace as fallback |
| Captions | **Own .ass generator + FFmpeg libass burn-in** | — |
| Rendering / cutting / encoding | **FFmpeg directly (LGPL build)** | MoviePy for prototyping only |
| Templated graphics (titles, progress bar) | **FFmpeg drawtext / ASS** first | Remotion only if React templating is wanted and team ≤3 |
| Upload / publish | **YouTube Data API v3** `videos.insert` (OAuth, user's own channel) | Verify current quota cost at build time |

## Licensing red flags (summary)

1. **FFmpeg — GPL trap.** Default/stock builds are often GPLv3 (x264/x265). Ship/use an **LGPL build** and document flags; H.264/H.265 patents are a separate question.
2. **yt-dlp — ToS, not licence.** Code is Unlicense, but **downloading YouTube videos breaches YouTube's ToS** and can infringe copyright. Optional, owned/permissioned-only, never default. Binary distributions are GPLv3+ (bundled code) — use source/PyPI form.
3. **Remotion — not open source; headcount licence.** Free only ≤3 people; an automated SaaS is "Automators" ($0.01/render, $100/mo min). Do not build the core on it without budgeting this.
4. **pyannote / WhisperX — gated weights.** Code is MIT/BSD-2-Clause, but diarization weights are **gated on Hugging Face** (accept terms + token on two pages) and community-1 weights are **CC-BY-4.0 (attribution required)**. Never bundle the weights.
5. **SupoClip (if ever borrowed from) — AGPL-3.0.** Network-serving a modified version triggers source-disclosure. Do not fork.
6. **MediaPipe — telemetry + no 3.13 wheels.** Tasks APIs send metrics to Google (consent duty); pin Python ≤3.12 if used.
7. **MoviePy — no licence issue (MIT), but a production-risk issue.** Performance/memory problems are well documented; keep it out of the render core.
8. **YouTube Data API — quota cannot be bought.** 10,000 units/day default; extension only via manual audit form. Design ID-first and cache aggressively.

## Open questions / verify at build time
- Exact FFmpeg 9.x point release and LGPL build availability (BtbN LGPL vs custom build).
- YouTube Data API current `videos.insert` quota cost (sources disagree: 1,600 vs ~100 vs 1 unit in its own bucket).
- PyAV version pin for faster-whisper 1.2.1 (`av<19` reported).
- Whether diarization is needed at all for v1 (single-speaker content dominates Shorts use).
- yt-dlp changelog check for the security fixes reported in release 2026.06.09 before pinning any version.
- Legal advice (not this note) before enabling the yt-dlp path in any user-facing build.

## Sources
- FFmpeg: ffmpeg.org / GitHub FFmpeg/FFmpeg; BtbN/Gyan build licensing notes.
- faster-whisper: github.com/SYSTRAN/faster-whisper; PyPI faster-whisper 1.2.1.
- PySceneDetect: github.com/Breakthrough/PySceneDetect; PyPI scenedetect 0.7.3.
- OpenCV: opencv.org; github.com/opencv/opencv; OpenCV Zoo (YuNet).
- MoviePy: github.com/Zulko/moviepy (v2.2.1); adversarial analysis + issue references #1284/#1508/#1535/#1892.
- Auto-Editor: github.com/WyattBlue/auto-editor; auto-editor.com.
- Remotion: remotion.dev licence/pricing pages (v5.0).
- pyannote.audio: github.com/pyannote/pyannote-audio; huggingface.co/pyannote/speaker-diarization-community-1, /speaker-diarization-3.1, /segmentation-3.0.
- WhisperX: github.com/m-bain/whisperX (v3.8.6).
- MediaPipe: github.com/google-ai-edge/mediapipe; developers.google.com/edge/mediapipe.
- YouTube Data API v3: developers.google.com/youtube/v3 (quota calculator); 2025–26 pricing guides.
- yt-dlp: **github.com/yt-dlp/yt-dlp README, fetched 2026-11-16** (208,162 stars, 24,040 commits, Unlicense; Dependencies section incl. ffmpeg/ffprobe, yt-dlp-ejs, Deno/Node/Bun/QuickJS, curl_cffi; Licensing section incl. GPLv3+ binaries); plus 2026 install/deno guides.
- Clipper repos: github.com/zhouxiaoka/autoclip; github.com/mutonby/openshorts; github.com/FujiwaraChoki/supoclip.
- Caption pattern: faster-whisper word timestamps → .ass → FFmpeg libass (multiple 2026 guides; whisper-word-captions / auto-caption, MIT).

*This note is research, not legal advice. Licence/ToS questions that affect shipping should go to a lawyer, not to this file.*
