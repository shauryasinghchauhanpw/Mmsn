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

---

# Phase 2, step 1 — real authentication (2026-11-16)

**What changed:** fastapi-users 15.0.0 wired in (`backend/app/auth.py`),
`User` gained `hashed_password`/`is_active`/`is_superuser`/`is_verified`,
every `/api/*` route requires a JWT and is scoped to the signed-in user
(other users' resources return 404), the Phase 1 `get_or_create_dev_user`
is deleted, frontend got `/login` + `/register` pages, a header auth guard
with sign-out, and token-authenticated clip downloads (fetch + blob URL).
Tested live against the real server on :8000 with real HTTP calls
(`httpx` script; no mocks). **No YouTube video was downloaded.**

## Migration (dev DB)

The existing `./mmsn.db` (Phase 1 schema) was migrated **in place** on
server startup — `ALTER TABLE users ADD COLUMN` for the four new columns
(log line: `Auth migration: added missing columns to users:
hashed_password, is_active, is_superuser, is_verified`). No data was
dropped. Consequence, verified: the old `dev@localhost` row has
`hashed_password = NULL` and can never log in, so its 2 Phase 1 test
projects (ids 1–2), 2 jobs and 4 clips are invisible to every real account
(Alice and Bob both got 404 for project 1, clip 1, job 1). The rows still
exist in the DB and the clip files are still on disk under `media/`.

## Results — auth (37/40 checks passed in the final run)

The 3 "failures" in the second run were re-run artefacts: Alice's
registration returned 400 `REGISTER_USER_ALREADY_EXISTS` because the
first run had already created her — the first run recorded register → 201.
All other checks passed in both runs.

| Check | Result |
|---|---|
| Unauthenticated `GET /api/projects`, `GET /api/projects/1`, `POST /api/projects/1/process`, `GET /api/jobs/1`, `GET /api/projects/1/clips`, `/highlights`, `/transcript`, `GET /api/clips/1/download`, `POST /api/projects/youtube`, `GET /users/me` | ✅ PASS — all 10 returned **401** |
| `POST /auth/register` alice@example.com / `<local-test-password>` | ✅ PASS — **201**, `{"id":2,"email":"alice@example.com","name":"Alice","is_active":true,"is_superuser":false,"is_verified":false}` |
| Duplicate register (same email) | ✅ PASS — **400** `REGISTER_USER_ALREADY_EXISTS` |
| Register with 3-char password | ✅ PASS — **400** (min-8 policy) |
| Login with wrong password | ✅ PASS — rejected, **400** `LOGIN_BAD_CREDENTIALS`. Note: fastapi-users returns 400, not 401, for bad credentials — that is its documented behaviour, not a bug. |
| `POST /auth/jwt/login` correct password | ✅ PASS — **200**, JWT returned (157 chars, HS256) |
| `GET /users/me` with token | ✅ PASS — **200**, `alice@example.com` |
| `GET /api/projects` as Alice | ✅ PASS — **200**, `[]` (old dev projects not visible) |
| `POST /api/projects/upload` as Alice (same local FFmpeg test video) | ✅ PASS — **201**, project id 3, `duration_sec: 69.866667` |
| `POST /api/projects/youtube` as Alice, no API key | ✅ PASS — **501** `youtube_api_not_configured` (auth passed, then the not-configured path) |
| `POST /auth/register` bob@example.com | ✅ PASS — **201** |
| Bob `GET` Alice's project 3 | ✅ PASS — **404** |
| Bob `GET /api/projects` | ✅ PASS — **200**, `[]` (Alice's project absent) |
| Bob `POST /api/projects/3/process` | ✅ PASS — **404** |
| Bob `GET /api/projects/3/clips`, `/highlights`, `/transcript` | ✅ PASS — **404** on all three |
| Bob `GET /api/jobs/3` (Alice's job) | ✅ PASS — **404** |
| Alice `POST /api/projects/3/process` + `GET /api/jobs/3` | ✅ PASS — **202** then **200** |
| Full pipeline as Alice (job 3) | ✅ PASS — `done`, 100%, ~80 s of polling (warm model cache), 2 clips (ids 5, 6) |
| Alice `GET /api/projects/3/clips` / `/transcript` / `/highlights` | ✅ PASS — **200**, 2 clips, transcript ~1156 chars, 2 highlights |
| Alice `GET /api/clips/5/download` | ✅ PASS — **200**, **1,743,977 bytes**, `video/mp4` (byte count matches the Phase 1 clip of the same source video) |
| Bob `GET /api/clips/5/download` (Alice's clip) | ✅ PASS — **404** |
| Seed flow: restart with `SEED_EMAIL`/`SEED_PASSWORD` set | ✅ PASS — log `Seed user created (dev only): seed@example.com (id=4)`, login **200**; wrong password **400** |
| Restart without seed vars | ✅ PASS — no seed line in log, no user auto-created; seed user still logs in (**200**) |

## Bugs found by testing (both fixed)

1. **`UserManager.parse_id` missing** — fastapi-users' default raises
   `NotImplementedError`, so every authenticated request (`GET /users/me`,
   any `/api/*` call with a token) returned 500. Fixed by overriding
   `parse_id` in `backend/app/auth.py` (`int(value)` — JWT `sub` is a
   string, user ids are ints). Login itself worked before the fix (it
   does not call `parse_id`); token *use* did not.
2. **Seed crashed startup** — `UserManager.get_by_email` raises
   `UserNotExists` instead of returning `None` when the user is missing,
   so the first seed attempt killed the server at startup. Fixed by
   catching `UserNotExists` in `seed_user_if_configured()`.

## Frontend

| Check | Result |
|---|---|
| `npm run build` | ✅ PASS — "Compiled successfully", 6 routes (`/`, `/login`, `/register`, `/projects/[id]`, `/clips/[id]`, `/_not-found`), First Load JS ~97 kB |
| Login/register pages, auth guard, sign-out, dashboard email, authenticated clip download/preview in a real browser | ⚠️ **NOT TESTED** — no live browser is available in this environment. The build passes and the pages are wired to the real API (token in localStorage, `Authorization: Bearer` on every call, blob-URL clip fetch because `<video src>`/`<a href>` cannot send headers), but the phone-browser sign-up → upload → download flow still needs a live check by the parent agent. |

## Test accounts left in the dev DB

`alice@example.com` / `<local-test-password>` (id 2, project 3, job 3, clips 5–6),
`bob@example.com` / `<local-test-password>` (id 3),
`seed@example.com` / `<local-test-password>` (id 4). The exact passwords
were redacted from this file before pushing to GitHub (they were
throwaway local-only passwords; the dev DB is not in the repo). These are throwaway local-test
accounts in the gitignored dev DB only — delete them (and project 3's rows
and files) before any shared/demo use, and never reuse these passwords.

---

# Phase 2, step 2 — working video editor (2026-11-16)

**What changed:** new editor endpoints (`GET /api/clips/{id}`,
`GET /api/clips/{id}/captions`, `POST /api/clips/{id}/re-render`,
`POST /api/clips/{id}/regenerate`, `POST`+`GET /api/clips/{id}/thumbnail`),
4 real ASS subtitle styles, versioned re-renders via a `kind="rerender"`
background job (`backend/pipeline/rerender.py`), and a rewritten editor
page (draggable trim region via the wavesurfer.js Regions plugin,
caption editor, style picker, framing + volume sliders, job polling).
Clip model gained `edit_params_json` / `version` / `thumbnail_path`,
jobs gained `clip_id`; the dev DB was migrated in place on startup
(log: `Migration: added missing columns to clips: edit_params_json,
version, thumbnail_path` and `... to jobs: clip_id`). Tested live against
the real server on :8000 with real HTTP calls (httpx scripts) and real
FFmpeg output. **No YouTube video was downloaded.** No OCR tool was
available (no `tesseract` binary), so caption visibility was verified by
reading extracted frames as images, not by OCR — stated as the method
below.

## Results — endpoints, validation, auth (27/27 checks passed)

Run against Alice's clip 5 (project 3, highlight 0.00–28.62 s, v1, 28.63 s).

| Check | Result |
|---|---|
| `GET /api/clips/5` | ✅ PASS — 200, highlight window 0.0–28.62 s, `version: 1`, `edit_params: {}`, `has_thumbnail: false` |
| `GET /api/clips/5/captions` | ✅ PASS — 200, style `karaoke`, **29 groups**, window 0.00–28.62 s; group 0 `0.00–1.04 ' Hello everyone,'` |
| Bob `GET /api/clips/5`, `/captions`, `POST re-render`, `POST regenerate`, `POST thumbnail?t=3`, `GET thumbnail` | ✅ PASS — **404** on all six |
| Anonymous (no token) on the same six | ✅ PASS — **401** on all six |
| Bad style `{"style":"nope"}` | ✅ PASS — **400** `Unknown subtitle style 'nope'. Choose one of: bold, highlighted, karaoke, minimal.` |
| `trim_end: 99` (> window) | ✅ PASS — **400** |
| Trim 10–11 s (< 2 s) and 5–5 s | ✅ PASS — **400** on both |
| `volume: 3.0` / `framing_offset: 2` | ✅ PASS — **422** (pydantic range) on both |
| Re-render missing clip 9999 | ✅ PASS — **404** |
| `GET thumbnail` before any is set; `POST thumbnail?t=999` | ✅ PASS — **404** and **400** |

## Results — re-renders (29/29 checks passed, then 14/14 re-test checks)

Clip 5 was edited step by step (each step builds on the stored params of
the previous one); clip 7 (new talking-head project 4, see below) for
framing. Every re-render was a real background job polled to `done`.

| Check | Result |
|---|---|
| Trim `0–15 s` re-render | ✅ PASS — job done, **version 2**, `ffprobe` duration **15.00 s** (was 28.63 s), clip row duration 15.0 s, file `clip_5_v2.mp4`, old v1 file deleted |
| Caption edit: group 0 → `HELLO EDITED WORDS` | ✅ PASS — job done, **version 3**, duration still 15.00 s; edited text present in the ASS rebuilt exactly as the renderer builds it, old text `Hello everyone,` absent; frame at 0.5 s read visually: **"HELLO EDITED WORDS welcome"** with EDITED highlighted yellow — the extra "welcome" was the regrouping bug (fixed below), verified by eye, not OCR |
| Style change to `bold` | ✅ PASS — job done, **version 4**, stored style `bold`; ASS Style lines differ (`Arial,72,…,Outline 4` vs `Arial,88,…,Outline 5, Shadow 2`); frame at t=5 s differs (md5 `04d742e7` vs `198b041f`); read visually: same text "secret about how to", visibly larger/bolder in the bold frame |
| Volume `0.5` | ✅ PASS — job done, **version 5**; `ffmpeg volumedetect`: mean **−15.8 dB → −21.9 dB** (drop **6.10 dB**, expected −6.02 dB for 0.5×), max −4.6 → −10.7 dB |
| Thumbnail `POST ?t=3` + `GET` | ✅ PASS — 200, `{"clip_id":5,"t":3.0,"thumbnail_url":"/api/clips/5/thumbnail"}`; GET 200 `image/jpeg`, **72,507 bytes**; `has_thumbnail: true` |
| Regenerate (stored params) | ✅ PASS — 202, job done, **version 6**, params kept (`bold`, volume 0.5, trim 0–15, override intact), duration still 15.00 s |
| Download after all versions | ✅ PASS — 200, **1,035,507 bytes** |

## Results — framing + regression (first run 7/14, re-test 14/14)

Talking-head project 4 (upload of `test_media/test_talking_head.mp4` as
Alice → process job 9 done in **91 s**, 2 clips, transcript 1156 chars)
is the Phase 1 flow regression: upload/process/clips/transcript all ✅.

| Check | Result |
|---|---|
| Face in talking-head window | ❌ **0/58 YuNet samples found a face** — see note below |
| Framing re-render `offset +0.9` (first run) | ❌ **FAILED** — `Render failed: Clip render failed: [AVFilterGraph] No such filter: '0)'` — the unescaped-comma bug in `vertical_filter()` (Phase 1 latent bug, see ARCHITECTURE.md §9). Clip stayed at v1 with the old file intact (failure handling worked as designed: job failed, clip status back to `ready`) |
| Framing re-render `offset +0.9` (after fix) | ✅ PASS — job 11 done, **version 2**; frame at t=5 differs (md5 `70d651ae` vs `bda6b315`), mean abs pixel diff **148.04** (0–255 scale) |
| Synthetic face track through `render_clip()` (median 0.25, offset 0 vs +0.5) | ✅ PASS — both renders succeed; frames differ (md5 `934acc24` vs `c248ca0c`), mean abs pixel diff **130.00**; face-track render also differs from plain centre crop (mean abs diff **139.27**) |
| Regenerate clip 5 after the caption-grouping fix | ✅ PASS — job done, **version 7**; groups rebuilt as `['HELLO EDITED WORDS', ' welcome back to the', ' channel.']`; frame at 0.5 s read visually: exactly **"HELLO EDITED WORDS"**, EDITED highlighted yellow, no stray "welcome" |

**Note on the talking-head video:** `test_media/test_talking_head.mp4`
contains **no face at all** — the frame at t=5 is the same FFmpeg
`testsrc` colour-bar pattern as the Phase 1 test video, with captions.
YuNet finding 0 faces in 58 samples is correct, not a detector failure.
Consequences: the face-*tracked* framing path could only be verified
with a synthetic face track (above), not with a real detected face;
face-following on a real talking-head video is **still unverified** and
needs a video with an actual face. The API-level framing test verified
the centre+nudge fallback (offset +0.9 moves the crop), and the
synthetic-track test verified the median+nudge math through real FFmpeg.

## Bugs found by testing (both fixed, both re-verified)

1. **Unescaped commas in the face-track crop filter** (`backend/pipeline/
   reframe.py`) — `crop=…:min(max(…,0),iw-…)` failed FFmpeg parsing
   (`No such filter: '0)'`). Latent since Phase 1: no face was ever
   tracked in testing, so the branch never ran. Fixed by escaping commas
   (`\,`); verified by direct FFmpeg crop (centre vs right-edge mean abs
   diff 149.5), the API framing re-test, and synthetic face-track renders.
2. **Caption edit absorbed a neighbouring word** — re-grouping the flat
   word list after an override pulled "welcome" into the edited group
   ("HELLO EDITED WORDS welcome"). Fixed with a `_new_group` boundary
   flag in `apply_caption_overrides()` / `group_words()`; re-verified by
   ASS rebuild + frame (exactly "HELLO EDITED WORDS").

## Frontend

| Check | Result |
|---|---|
| `npm run build` (after the editor rewrite) | ✅ PASS — "Compiled successfully", 6 routes (`/`, `/login`, `/register`, `/projects/[id]`, `/clips/[id]`, `/_not-found`), editor page 5.42 kB / First Load JS ~100 kB. No new dependency: the Regions plugin ships inside wavesurfer.js 7.9.0. |
| Editor page in a real browser (drag region, inputs, sliders, Apply polling, thumbnail button) | ⚠️ **NOT TESTED** — no live browser is available in this environment. The build passes, the API it calls is verified live above, and the page is wired to the real API (token in localStorage, blob-URL video/thumbnail), but the phone-browser interaction still needs a live check by the parent agent. |

## Test state left in the dev DB

Alice's project 3, clip 5 is now at **version 7** (`clip_5_v7.mp4`,
15.00 s, bold style, volume 0.5×, trim 0–15 s, group-0 override
"HELLO EDITED WORDS", thumbnail set from t=3 s). Project 4
(talking-head upload, Alice) has clips 7 (v2, framing +0.9) and 8 (v1).
Jobs 9–12 are the process/re-render jobs from this session. Test
scripts are in `/tmp/test_editor_smoke.py`, `/tmp/test_editor_render.py`,
`/tmp/test_editor_framing.py`, `/tmp/test_editor_retest.py` (not in the
repo — rerun them against a live server to reproduce).

---

# Phase 2, step 3 — LLM scoring verification + full re-test (2026-11-16)

**What changed:** `detect_highlights()` / `score_highlights_llm()` now
return `(highlights, scorer)`; `Highlight` gained a `scorer` column
(`"llm"` | `"heuristic"`, default `"heuristic"`, added by the same
add-only migration in `backend/app/database.py` — startup log:
`Migration: added missing columns to highlights: scorer`); `runner.py`
stores the scorer that actually ran; `HighlightOut` exposes it; the
frontend shows **"Scored by: LLM" / "Scored by: Heuristic"** next to
each clip's virality score on the project page and in the editor's Clip
info (from `GET /api/projects/{id}/highlights`). The UI can never claim
LLM scoring when the heuristic ran — it prints the stored value
verbatim. **No real OpenAI key exists and none was used** — LLM
behaviour below was verified against a local mock server only.

## Results — LLM scoring, local mock (14/14 checks passed)

Script `/tmp/test_llm_mock.py` (not in the repo). A tiny `http.server`
in the test process implements `POST /chat/completions` and returns a
canned JSON highlight array; `detect_highlights()` is called on the
**real transcript segments of project 3** (3 segments, 0–69.4 s,
209 words, read from the dev DB) with a dummy key and
`OPENAI_BASE_URL` pointed at the mock.

| Check | Result |
|---|---|
| Mock success → scorer `"llm"` | ✅ PASS |
| Mock success → 2 highlights, titles `MOCK LLM TITLE ONE` / `MOCK LLM TITLE TWO` | ✅ PASS — the mock's picks, not the heuristic's |
| Mock pick scores 95 / 88 (heuristic would give 81) and window 28.62–57.76 s | ✅ PASS |
| Mock received the transcript text in its request body (`"Hello everyone"`, `TRANSCRIPT`) and the dummy model name `mock-model` | ✅ PASS — exactly 1 request |
| Mock returns HTTP 500 → scorer `"heuristic"`, 2 fallback highlights, first reason `"LLM scoring unavailable — heuristic score"`, scores 81 | ✅ PASS |
| No `llm_config` → scorer `"heuristic"`, same picks as the 500-fallback | ✅ PASS |

**Environment quirk found while testing (not a product bug):** the
first mock run failed with `httpx.InvalidURL: Invalid port: ':1]'` —
`httpx` honours this VM's `HTTP(S)_PROXY` / `NO_PROXY` environment
variables, and the VM's `NO_PROXY` value (which includes `[::1]`)
breaks httpx's localhost URL handling. The 14/14 run above was done
with the proxy variables cleared (`env -u http_proxy -u https_proxy
-u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy -u NO_PROXY
-u no_proxy`). Consequence: in *this* VM, any `OPENAI_BASE_URL`
pointing at localhost would hit the same httpx/proxy failure and fall
back to the heuristic (with the "LLM scoring unavailable" reason) —
the fallback path is what makes that safe. On Render/Railway no such
proxy variables are set, so a real `OPENAI_API_KEY` should call
`api.openai.com` normally — **still untested with a real key**.

## Results — full re-test on the final code (59/61 as-run, 61/61 after re-check)

Script `/tmp/test_phase2_final.py` (not in the repo), against the live
server on :8000 with the final code. Test input: a **new** locally
generated video (`/tmp/final_test_video.mp4`, FFmpeg `testsrc`
1280×720 30 fps + real spoken English via the `flite` filter, new
~200-word script, 77.705 s, 2.4 MB). **No YouTube video was downloaded.**

| Check | Result |
|---|---|
| Anonymous `GET /api/projects`, `GET /api/clips/5`, `POST /api/projects/3/process`, `GET /users/me`, `GET /api/projects/3/clips`, `GET /api/clips/5/download` | ✅ PASS — all 6 returned **401** |
| Login with wrong password | ✅ PASS — **400** `LOGIN_BAD_CREDENTIALS` |
| Bob `GET` Alice's project 3, clip 5, clips/highlights/transcript of project 3, job 3, clip 5 download | ✅ PASS — **404** on all 7 |
| Bob `POST /api/clips/5/re-render` | ⚠️ **422 as-run, re-verified 404** — see note below |
| `GET /api/projects/3/highlights` exposes `scorer`; all 8 pre-existing highlights are `"heuristic"` (migration default) | ✅ PASS |
| Clip 5 state preserved from step 2 | ✅ PASS — still **version 7** |
| Fresh upload (new video) as Alice | ✅ PASS — **201**, project **5**, `duration_sec: 77.705` |
| Fresh process (job 13) | ✅ PASS — `done`, **101 s** (warm model cache), **3 clips** (30.00 s, 29.23 s, 18.53 s — a 3rd clip fit this time because the new script has more usable speech) |
| `ffprobe` on all 3 fresh clips | ✅ PASS — `h264, 1080×1920`, durations match the API |
| `GET /api/clips/{id}/download` for all 3 | ✅ PASS — **byte-identical** to disk: 2,201,468 / 2,147,479 / 1,315,043 bytes |
| Fresh highlights | ✅ PASS — scores **89 / 84 / 76**, all `scorer: "heuristic"` (no LLM key set), reasons present |
| Fresh transcript | ✅ PASS — 3 segments with word timestamps |
| Editor on fresh clip 9 (v1, 30.00 s): `GET captions` | ✅ PASS — **30 groups** |
| Trim `0–15 s` re-render | ✅ PASS — job done, **version 2**, `ffprobe` duration **15.00 s** |
| Caption edit group 0 → `FINAL TEST WORDS` | ✅ PASS — job done, **version 3**, duration still 15.00 s; rebuilt ASS contains FINAL/TEST/WORDS and no "Hello"; frame at 0.5 s read visually: exactly **"FINAL TEST WORDS"** with TEST highlighted yellow (bold style) |
| Style change to `bold` | ✅ PASS — job done, **version 4**; frame at t=5 differs from the karaoke frame (md5 `1bc3e9b3` vs `decf335a`) |
| Framing nudge `+0.9` | ✅ PASS — job done, **version 5**; frame at t=5 differs (md5 `decf335a` vs `a7b52899`) |
| Volume `0.5` | ✅ PASS — job done, **version 6**; `ffmpeg volumedetect`: mean **−18.8 dB → −24.8 dB** (drop **6.0 dB**, expected −6.02 dB for 0.5×) |
| Thumbnail `POST ?t=3` + `GET` | ✅ PASS — 200, `image/jpeg`, **84,177 bytes** |
| Regenerate (stored params) | ✅ PASS — job done, **version 7**, params kept (`bold`, volume 0.5, trim 0–15, override intact, framing +0.9) |
| Bob / anon `POST re-render` on fresh clip 9 | ✅ PASS — **404** / **401** |
| `npm run build` (frontend, after the scorer-label change) | ✅ PASS — "Compiled successfully", 6 routes (`/`, `/login`, `/register`, `/projects/[id]`, `/clips/[id]`, `/_not-found`), editor page 5.51 kB / First Load JS ~100 kB |

**The 2 as-run FAILs were both test-script artefacts, re-verified
above — no product bug:**

1. **Bob re-render 422:** the test called `POST /api/clips/5/re-render`
   with **no body at all**, so FastAPI's body validation (422) fired
   before the endpoint's ownership check. Re-run with an (empty) JSON
   body returns **404** for both clip 5 and clip 9, as designed.
2. **Caption edit "not in rebuilt ASS":** the test looked for the
   contiguous string `"FINAL TEST WORDS"` in the ASS text, but karaoke
   mode emits one Dialogue event per word, so the words never appear
   contiguously. Re-checked properly: the edited word list starts
   `['FINAL', ' TEST', ' WORDS', ...]`, the ASS contains each word,
   "Hello" is gone, and the rendered frame shows "FINAL TEST WORDS".

## Test state left in the dev DB

Alice's project **5** (fresh final-test video, 77.705 s) has clips
9 (**version 7**, 15.00 s, bold, volume 0.5×, trim 0–15 s, group-0
override "FINAL TEST WORDS", framing +0.9, thumbnail set from t=3 s),
10 (v1, 29.23 s) and 11 (v1, 18.53 s); job 13 is the process job.
Project 3 / clip 5 (v7) and project 4 / clips 7–8 are unchanged from
step 2. Test scripts: `/tmp/test_llm_mock.py`,
`/tmp/test_phase2_final.py` (not in the repo).

## NOT tested (unchanged from Phase 1/2, plus step-3 notes)

- Docker builds (`backend/Dockerfile`, `frontend/Dockerfile`) and
  `render.yaml` / Railway deploy — **not run**; no Docker daemon or
  Render account in this environment. They are provided as-is; the
  first real deploy will be the test.
- YouTube Data API with a real key (no key exists yet) — only the
  not-configured path was tested.
- **LLM highlight scoring with a real OpenAI key — not tested.** Only
  the local mock (above) and the heuristic path ran. A real key should
  work the same way (same `POST /chat/completions` call), but no real
  call was ever made.
- yt-dlp — deliberately not tested with any download (per the testing rule).
- Real talking-head video with a face (face-following path), long videos
  (>10 min), concurrent jobs, and phone-browser usage — still not tested.
  The editor / auth / scorer-label UI was verified at the API + build
  level only; no live browser check exists in this environment.

---

# Phase 3 — automated pytest suite (2026-11-16)

**What changed:** the Phase 2 `/tmp` scripts (`test_auth.py`,
`test_editor_smoke.py`, `test_editor_render.py`,
`test_editor_framing.py`, `test_editor_retest.py`,
`test_llm_mock.py`, `test_phase2_final.py`) were converted into a
real pytest suite in the repo under `backend/tests/` and are now
retired as the source of truth — the `/tmp` copies are stale
snapshots, not maintained. No app code was changed for the suite.

**How it runs:** `backend/tests/conftest.py` sets the test
environment *before* importing the app — `DATABASE_URL` points at a
fresh temp SQLite file, `UPLOAD_DIR`/`MEDIA_DIR` are temp dirs, and a
test-only `SECRET_KEY` is used — then the app runs in-process via
`fastapi.testclient.TestClient`. The dev database (`./mmsn.db`) is
never touched, and no test user/project/clip from the suite leaks
into it. The test video is generated locally with FFmpeg
(`testsrc` 1280×720 30 fps + real spoken English via the `flite`
filter, ~210 words, 65.87 s) — the same recipe as the Phase 1/2
manual runs. **No YouTube video was downloaded.** LLM scoring is
tested against a local mock `/chat/completions` server; no real
OpenAI key was used or needed.

**Commands** (from the repo root, in the venv;
`pip install -r backend/requirements-test.txt` first — pytest only,
httpx is already a runtime dependency):

```bash
python -m pytest backend/tests -m "not slow"   # fast suite
python -m pytest backend/tests                  # full suite
```

## Results

| Run | Result | Time |
|---|---|---|
| Fast suite (`-m "not slow"`) — 96 tests | ✅ **96 passed**, 4 deselected | **41.95 s** |
| Full suite — 100 tests | ✅ **100 passed** | **429.39 s (7:09)** |
| Slow-only re-run (`-m slow`) — 4 tests, with `--durations=10` | ✅ **4 passed** | **499.66 s (8:19)** |

**Coordinator re-run (after all three Phase 3 pieces landed, same
code as pushed):** fast suite ✅ **96 passed**, 4 deselected,
**41.35 s**; full suite ✅ **100 passed**, **400.41 s (6:40)**.
This re-run covers the final merged code — including the Postgres /
S3 / Celery hardening and the deploy fixes — not just the suite as
it stood when it was first written.

Tests per file (100 total): `test_auth.py` 25, `test_editor.py` 23,
`test_llm_scoring.py` 5, `test_pipeline_e2e.py` 6,
`test_units.py` 41.

Slow-test timings (from the slow-only re-run; the full-suite run was
faster overall because the shared `processed_project` fixture is
built once):

| Slow test | Time |
|---|---|
| `test_editor_full_chain` — 7 real re-renders, versions 1→7 (trim, caption, style, framing, volume, thumbnail, regenerate), setup = upload + full pipeline run | 274.32 s call + 142.04 s setup |
| `test_framing_rerender_moves_centre_crop` — API framing re-render on a no-face clip | 61.54 s |
| `test_synthetic_face_track_render` — 3 direct `render_clip()` calls with a synthetic face track | 20.85 s |
| `test_full_pipeline_end_to_end` — assertions on the shared fixture's run (pipeline itself is the chain test's 142 s setup) | 0.36 s |

The full end-to-end test passes: upload → process (job `done`,
~142 s warm on this VM) → clips (≥1, `h264, 1080×1920`) →
download byte-identical to disk → transcript with word timestamps
→ highlights with `scorer: "heuristic"` and reasons.

### What the fast suite covers (no full render)

- Auth: 16 unauthenticated endpoints → 401; register/login/me;
  duplicate register, short password, invalid email, wrong password
  (`LOGIN_BAD_CREDENTIALS`), unknown user; per-user ownership (Bob
  gets 404 on Alice's project/clips/highlights/transcript/process);
  YouTube endpoint 501 not-configured / 400 non-YouTube URL;
  `/health` public.
- Upload/process validation: bad extension → 400, non-video file →
  400, missing project → 404, metadata-only YouTube project →
  400, queued-job dedup (re-POST returns the existing job).
- URL parsing: 11 valid YouTube forms + 7 invalid; ISO-8601
  durations (8 cases).
- Editor validation/auth (on DB-seeded clip rows, no pipeline):
  clip detail + captions, 401 anon / 404 other user on all six
  editor endpoints, bad style → 400, trim out-of-range / <2 s /
  start==end / start>end → 400, volume/framing out of range → 422,
  missing clip → 404, thumbnail before set → 404, `t=999` → 400.
- Caption units: `merge_edit_params` defaults/clamps/unknown-style
  fallback, `retime_text` even splits, the group-boundary fix
  (edited group stays exactly "HELLO EDITED WORDS", next group keeps
  its own words), empty-override drops the group, `group_words`
  `_new_group` splits, ASS per-word (karaoke) vs per-group
  (minimal), unknown style falls back to karaoke.
- Heuristic scorer units: deterministic, non-overlapping picks,
  empty transcript → no highlights.
- LLM mock: success → scorer `"llm"` with the mock's titles/scores
  (95/88) and exactly one request carrying transcript text and the
  dummy model name; mock 500 → `"heuristic"` with the
  "LLM scoring unavailable" reason, matching the no-config run;
  empty API key → heuristic with no request sent.

### One conversion bug found (test was wrong, app was right)

During conversion, `test_re_render_trim_validation` expected 400 for
a negative `trim_start`; the app returns **422** because pydantic's
`ge=0` on `ReRenderRequest.trim_start` fires before the endpoint's
own 400 trim check. The test was corrected to 422 with a comment.
No app code changed.

### Warnings (not failures)

The runs emit SQLAlchemy `LegacyAPIWarning`s (`Query.get()` is
legacy in 2.0) and a `datetime.utcnow()` deprecation warning from
the app's existing code, plus FastAPI/Starlette deprecation warnings
from the installed libraries. All pre-existing; none fail a test.

### Still NOT covered by the suite

- Everything in the "NOT tested" lists above that is still open:
  Docker builds and Render/Railway deploy, YouTube Data API with a
  real key, LLM scoring with a real OpenAI key, yt-dlp, a real
  talking-head video with a face (face-following uses a synthetic
  track only), long videos (>10 min), concurrent jobs, and any
  phone-browser / frontend interaction. The suite is API + pipeline
  level only.
- The editor chain test runs against the first clip of the shared
  processed project, and the e2e assertions are written to hold
  whether that clip is at version 1 or version 7 — but if the chain
  test is run on its own (`-k test_editor_full_chain`), it builds
  its own processed project; the two paths share the same fixture.
- Fast-suite runtime (42–84 s across runs on this VM, varying with
  machine load) is dominated by generating the test video with FFmpeg
  (~40 s); the HTTP/unit tests themselves take ~2 s.
