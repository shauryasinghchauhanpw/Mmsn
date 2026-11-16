# TESTING.md — what was actually tested (Phase 1)

**Date:** 2026-11-16. **Machine:** this VM — ffmpeg 8.1.2, Python 3.12.3,
Node v24.22.1, ~1.5 shared CPUs, ~650 MB free RAM at test time.
**Test input:** a video generated locally with FFmpeg — `testsrc` 1280×720
30 fps + real spoken English via the `flite` filter (~230 words, 69.9 s,
1.3 MB). **No YouTube video was downloaded at any point.**

## End-to-end runs (backend)

| Check | Result |
|---|---|
| `pip install -r backend/requirements.txt` in a fresh venv | ✅ PASS — faster-whisper 1.2.1, av 18.1.0, scenedetect 0.7.3, opencv 5.0.0, SQLAlchemy 2.0.36, FastAPI 0.115.6 all installed; `import fastapi, sqlalchemy, faster_whisper, scenedetect` OK. Note: `scenedetect` pulls in non-headless `opencv-python` 5.0.0 alongside headless 4.12; cv2 resolves to 5.0.0. |
| `GET /health` | ✅ PASS — `{"status":"ok","version":"0.1.0","youtube_api_configured":false,"llm_scoring_configured":false,"whisper_model":"tiny"}` |
| `POST /api/projects/upload` (test video) | ✅ PASS — project created, `duration_sec: 69.866667`, status `uploaded`. |
| `POST /api/projects/{id}/process` — cold run (job 1) | ✅ PASS — job `done`, 100%, 280 s total. Includes first-run download of the faster-whisper `tiny` model (~75 MB from Hugging Face). |
| `POST /api/projects/{id}/process` — warm run (job 2, model cached) | ✅ PASS — job `done`, 100%, **121 s** total for the same 70 s video. |
| `GET /api/projects/{id}/clips` | ✅ PASS — 2 clips per run (a 3rd did not fit: remaining speech after the 2 non-overlapping windows was ~12 s, below the 15 s minimum — correct behaviour, not a bug). |
| `ffprobe` on both clips | ✅ PASS — `h264, 1080×1920, 30 fps, aac`, durations 28.63 s and 29.17 s, ~1.7 MB / ~2.0 MB. Real 1080×1920 MP4s. |
| `GET /api/clips/{id}/download` | ✅ PASS — HTTP 200, 1,743,977 bytes, byte-identical to the file on disk (`cmp` clean). |
| `GET /api/projects/{id}/transcript` | ✅ PASS — language `en`, 3 segments, 86 words with word timestamps in segment 0. (Tiny-model accuracy note: it misheard "2026" as "2020's X" — expected for `tiny`; use `small`/`large-v3-turbo` for better accuracy.) |
| `GET /api/projects/{id}/highlights` | ✅ PASS — 2 highlights, score **81/100** each, with reasons (hook words, concrete numbers, speaking pace) + titles + hashtags. |
| Burned-in captions (visual check) | ✅ PASS — extracted a frame at 5 s from clip 1: vertical 1080×1920 crop of the test pattern with karaoke captions visible ("secret **about** how to", current word highlighted yellow). |
| `POST /api/projects/youtube` — valid URL, no API key | ✅ PASS — HTTP 501, `{"code":"youtube_api_not_configured","message":"YouTube Data API is not configured on this server. Upload the video file instead — a link alone cannot be processed."}`. No fake metadata. |
| `POST /api/projects/youtube` — non-YouTube URL | ✅ PASS — HTTP 400 with a clear message. |
| `extract_video_id` unit check (11 cases) | ✅ PASS — watch (v first / v later), youtu.be, Shorts, embed, /live/, music.youtube.com, bare ID all parse; non-YouTube and short IDs return None. |

## Bugs found by testing (all fixed)

1. **SQLAlchemy `Highlight` had no `project` relationship** while
   `Project.highlights` used `back_populates="project"` — server failed at
   startup (`Mapper[Highlight] has no property 'project'`). Fixed in
   `backend/app/models.py`; server then booted.
2. **YouTube URL regex rejected standard watch URLs** — `watch\?.*?[?&]v=`
   never matches when `v` is the first query param, so the most common
   YouTube URL form returned 400. Rewrote `extract_video_id()` on
   `urllib.parse` (query param `v` + path prefixes); all 11 cases pass.
3. **Frontend import paths wrong** — `app/projects/[id]/page.tsx` and
   `app/clips/[id]/page.tsx` used `../../lib/api` (2 levels up) instead of
   `../../../lib/api`. First `npm run build` failed on this; fixed and
   rebuilt clean.

## Frontend

| Check | Result |
|---|---|
| `npm install` | ✅ PASS |
| `npm run build` (after import fix) | ✅ PASS — "Compiled successfully", 4 routes (`/`, `/projects/[id]`, `/clips/[id]`, `/_not-found`), First Load JS ~97 kB. |
| Dashboard / project / editor pages in a real browser | ⚠️ **NOT TESTED** — no live browser is available in this environment. The build passes and the pages are wired to the real API, but the wavesurfer.js waveform (fetch + decode of clip audio, tap-to-seek) and the upload flow in a phone browser still need a live check by the parent agent. |

## Reuse-sweep components verified

| Component | Result |
|---|---|
| YuNet model download + SHA-256 | ✅ PASS — downloaded from the pinned OpenCV Zoo revision, 232,589 bytes, SHA `8f2383e4…2552fa4` matches the published hash; `cv2.FaceDetectorYN.create()` loads it and `detect()` runs on cv2 5.0.0 (blank frame → no face, as expected). |
| Face tracking in a real pipeline run | ⚠️ PARTIAL — the test video has no face, so the track was empty and both runs used the centre-crop fallback (by design). Face-following on a real talking-head video is **not yet verified** — needs a video with a face. |
| Scene detection (PySceneDetect) | ✅ PASS — ran inside both jobs without error; clip boundaries were snapped (no cuts in the test pattern, so windows were unchanged). |
| stable-ts | ❌ REJECTED (see research §14) — `pip install --dry-run` shows it pulls torch 2.15 + torchaudio + CUDA toolkit. Not installed. |
| faster-whisper standalone | ✅ PASS — 10 s clip transcribed in ~10 s with VAD and ~35 s without VAD (incl. model load), correct text. |

## Performance notes (this VM, 1.5 shared CPUs)

- Cold run (model download): 280 s for a 70 s video. Warm run: 121 s.
  Roughly 1.7× realtime warm — acceptable for a CPU-only dev box, slow for
  long videos. This is why DEPLOYMENT.md warns that free hosting tiers will
  struggle: a 1-hour video would take well over an hour here.
- The first job appeared stuck at 20% for several minutes in live polling;
  that was the first-run model download + inference on a throttled CPU, not
  a deadlock (the job completed; a warm rerun was ~4× faster).

## NOT tested

- Docker builds (`backend/Dockerfile`, `frontend/Dockerfile`) and
  `render.yaml` / Railway deploy — **not run**; no Docker daemon or Render
  account in this environment. They are provided as-is; the first real
  deploy will be the test.
- YouTube Data API with a real key (no key exists yet) — only the
  not-configured path was tested.
- LLM highlight scoring (no OpenAI key) — only the heuristic scorer ran.
- yt-dlp — deliberately not tested with any download (per the testing rule).
- Real talking-head video with a face (face-following path), long videos
  (>10 min), concurrent jobs, and phone-browser usage.
