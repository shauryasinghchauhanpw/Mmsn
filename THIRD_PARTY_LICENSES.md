# Third-party licences & attribution — MMSN Clipper

Every integrated library / tool, its licence, and what we do with it.
This project’s own code is MIT. Nothing here is legal advice.

## Integrated in Phase 1

| Component | Licence | Use in this project | Notes |
|---|---|---|---|
| **FFmpeg** (CLI, system install) | **LGPL 2.1+ by default; GPL if GPL components enabled** | Render engine: decode, cut, crop/scale to 1080×1920, caption burn-in (`ass` filter), H.264/AAC encode; `ffprobe` for duration. Called as a subprocess. | **Licence trap:** stock distro/Gyan builds are often GPLv3 (they include x264/x265). For a commercial product use an **LGPL build** (e.g. BtbN LGPL variant, or a custom `--disable-gpl --disable-version3 --disable-nonfree` build) and accept no x264/x265 in that build — or keep FFmpeg server-side only and take legal advice. H.264/H.265 **patent** licensing is independent of FFmpeg’s copyright licence. This VM uses the Ubuntu-packaged FFmpeg 8.1.2 for development only. |
| **faster-whisper** (+ CTranslate2, OpenAI Whisper models) | **MIT** (code and model weights; HF large-v3 card is tagged Apache 2.0 in one place — either way permissive) | Transcription with `word_timestamps=True` + VAD. | Keep the copyright notice. Models download from Hugging Face on first run (tiny ~75 MB, small ~490 MB, large-v3 ~3 GB). |
| **PySceneDetect** (`scenedetect`, headless) | **BSD-3-Clause** | Optional scene/cut detection hook; snaps clip boundaries to real cuts. | Optional dependency — pipeline works without it and logs a warning. (Older PyPI classifiers misleadingly say MIT; the repo LICENSE is BSD-3-Clause.) |
| **OpenCV** (`opencv-python-headless`) | **Apache 2.0** (v4.5.0+; ≤4.4.0 BSD-3-Clause) | Face detection for 9:16 reframing (Phase 2 hook). YuNet model: **MIT**. | Phase 1 ships the reframe module interface with centre crop; the YuNet detector is not wired in yet. Haar cascades are not used. |
| **FastAPI / Starlette / Uvicorn** | MIT / BSD-3-Clause | Backend web framework + server. | — |
| **SQLAlchemy** | MIT | ORM for users/projects/jobs/transcripts/highlights/clips/exports. | — |
| **Pydantic** | MIT | Request/response validation. | — |
| **python-multipart** | Apache 2.0 | File upload parsing. | — |
| **httpx / requests** | BSD-3-Clause / Apache 2.0 | YouTube Data API calls. | — |
| **Next.js / React / TypeScript / Tailwind CSS** | MIT | Frontend. | — |
| **python-dotenv** | **BSD-3-Clause** | Loads `.env` into the backend config. |
| **wavesurfer.js 7.9.0** | **BSD-3-Clause** (npm package; older README text says CC-BY 3.0 — the shipped package header is BSD-3-Clause) | Editor waveform: decodes clip audio, renders waveform, tap-to-seek. |
| **YuNet model** (`face_detection_yunet_2023mar.onnx`, OpenCV Zoo) | **MIT** | Face detection for 9:16 reframing. Downloaded on first use from a pinned revision, SHA-256 verified; **never committed** to the repo. |
| **libass** (via FFmpeg `ass` filter) | **ISC** | Caption burn-in. | Needs a real font installed on the system; bundle fonts under SIL OFL (e.g. Inter/Anton) and ship the font licence if bundling. |

## Optional / later phases (not integrated in Phase 1)

| Component | Licence | Status / condition |
|---|---|---|
| **yt-dlp** | **The Unlicense** (public domain) for the source. ⚠️ **Packaging caveat:** PyInstaller-bundled executables contain GPLv3+ code, so the combined binary is **GPLv3+**; the zipimport Unix binary / tarball also contain ISC-licensed `meriyah` and MIT-licensed `astring`. | **NOT integrated in Phase 1 — no download code path exists.** If ever added: source/PyPI form only (never a PyInstaller binary without advice), pinned version, `yt-dlp[default,deno]`, no `--cookies-from-browser`, no remote-components by default. **Use restriction (the important part):** the tool is lawful open-source software, but **downloading YouTube videos breaks YouTube’s Terms of Service** and can be copyright infringement. Only ever for videos the user owns or has explicit permission to use, clearly labelled, with an ownership/permission confirmation, never the default for arbitrary links. See `research.md` §12 and `README.md` “Ingestion rules”. |
| **stable-ts** | **MIT** | **Evaluated 2026-11-16, NOT integrated.** Silence suppression genuinely improves Whisper word timestamps, but it pulls torch 2.15 + torchaudio + CUDA toolkit — gigabytes, incompatible with the light CPU-only Phase 1 and free-tier hosting. Revisit only with a torch-based worker image. |
| **fastapi-users 15.0.0** | **MIT** | **Chosen for Phase 2 auth, NOT wired yet.** JWT + OAuth2 + registration for FastAPI/SQLAlchemy. Wiring half of auth now would be fake multi-user functionality. |
| **Rescript** (transcript-based editor) | **PolyForm Noncommercial 1.0.0** | **Rejected — not commercial-compatible.** Do not borrow code from it. |
| **designcombo/react-video-editor, openvideodev/react-video-editor, tooscut** | Various (check each repo) | **Evaluated, not adopted as wholes.** Complete editor apps (Remotion/Fabric/Konva timelines); we borrow the waveform/timeline pattern via wavesurfer.js instead of importing a whole second rendering model. |
| **ffmpeg-python** | MIT | **Evaluated, rejected.** Thin CLI wrapper; direct subprocess calls give the control this pipeline needs. |
| **boto3 / S3** | Apache 2.0 | **Evaluated, deferred** to the production step — an S3 helper with no bucket to test against would be untested code. |
| **Celery + Redis** | BSD-3-Clause | **Deferred** — documented Phase 2 queue path (ARCHITECTURE.md §5). |
| **WhisperX** | **BSD-2-Clause** (code); alignment models have their own terms | Optional upgrade for accurate word alignment. Not installed in Phase 1. |
| **pyannote.audio** | **MIT** (code). **Weights are separate and Hugging Face-gated**: `pyannote/speaker-diarization-3.1` + `pyannote/segmentation-3.0` are MIT but gated (accept terms + HF token); `pyannote/speaker-diarization-community-1` weights are **CC-BY-4.0 (commercial OK with attribution)**, also gated. | Optional, multi-speaker only, off by default. **Never bundle the weights** — each deployment accepts the terms with its own HF account/token. Not installed in Phase 1. |
| **MediaPipe** (BlazeFace fallback) | **Apache 2.0** | Fallback face detector for reframing. Tasks APIs send performance/utilisation metrics to Google (consent duty); no Python 3.13 wheels — pin Python ≤3.12 if used. Not installed in Phase 1. |
| **MoviePy** | MIT | **Rejected as the render core** (performance / memory leaks on long batch jobs). Prototyping only, if ever. Not a dependency. |
| **Auto-Editor** (CLI binary) | **The Unlicense** | Optional silence-trim pre-pass only, via the release binary (never pip — PyPI ships a stale v29 build). Not integrated in Phase 1. The paid GUI is a separate proprietary product. |
| **Remotion** | **NOT open source** — source-available under Remotion’s own licence. Free for individuals / companies of **up to 3 people**; at 4+ a Company Licence is required, and an automated clipper SaaS is the **“Automators” tier: $0.01/render, $100/month minimum**. Telemetry mandatory for Automators in v5.0. | **Not used in Phase 1.** Templated graphics are done with FFmpeg `drawtext`/ASS. Budget the Automators tier before any production commitment. |
| **YouTube Data API v3** | Governed by the **YouTube API Services Terms of Service + Developer Policies** (incl. audit/compliance review for production apps). Free, quota-capped (10,000 units/day default; `videos.list` 1 unit; quota cannot be bought). | Metadata only — returns no video bytes and no download URL. |

## Reference only (do not fork)

| Repo | Licence | Why not forked |
|---|---|---|
| **autoclip** (zhouxiaoka/autoclip) | MIT | Best reference architecture (transcript → LLM score → FFmpeg render). Built around yt-dlp link ingestion — the path we restrict. Borrow patterns, not the codebase. |
| **OpenShorts** (mutonby/openshorts) | MIT | Young (Dec 2025); watch, don’t adopt yet. |
| **SupoClip** (FujiwaraChoki/supoclip) | **AGPL-3.0** | **Do not fork.** Network-serving a modified AGPL version triggers source disclosure; also the same yt-dlp ingestion model. Useful as a second reference for captions/reframing. |

## Attribution

- FFmpeg: Copyright © FFmpeg developers, LGPL 2.1+ (see https://ffmpeg.org/legal.html).
- faster-whisper: © SYSTRAN, MIT.
- PySceneDetect: © Breakthrough, BSD-3-Clause.
- OpenCV: © OpenCV Foundation, Apache 2.0; YuNet model © its authors, MIT.
- WhisperX / pyannote.audio (if added later): see rows above; CC-BY-4.0 weights
  require attribution to the pyannote community model card.
- This file will be updated whenever a new dependency is added.
