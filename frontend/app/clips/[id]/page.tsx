"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import type WaveSurfer from "wavesurfer.js";
import type { Region } from "wavesurfer.js/dist/plugins/regions";
import {
  api,
  type CaptionOverride,
  type ClipCaptions,
  type ClipDetail,
  type Job,
} from "../../../lib/api";

/**
 * Clip editor (Phase 2, step 2) — every control here is wired to the
 * backend and changes the exported MP4:
 *
 *  - Trim: draggable region on the wavesurfer waveform (Regions plugin)
 *    synced with the start/end inputs. Trim is relative to the highlight
 *    window the clip was cut from; the "new duration" preview updates
 *    live. The trim is applied by the re-render, not in the browser.
 *  - Captions: editable caption-group text, plus a subtitle style picker.
 *    Edited words are re-timed proportionally across their group's span
 *    (an approximation — see backend/pipeline/rerender.py).
 *  - Framing: horizontal nudge (-1..1) added to the face-track centre.
 *    There is NO live preview of the crop — it only moves in the
 *    re-rendered file, and the UI says so.
 *  - Volume: multiplier (0.25–2.0) applied with FFmpeg's volume filter.
 *  - Apply & re-render: POSTs the edits, polls the background job, then
 *    reloads the clip (new versioned file) and shows real progress /
 *    errors. Regenerate re-renders with the stored edits. Thumbnail is
 *    picked from the video's current frame.
 *
 * Clip files need the JWT, so video/thumbnail are fetched with auth and
 * served as blob URLs (a plain src URL cannot send an Authorization
 * header).
 */

const STYLES: { id: string; label: string; note: string }[] = [
  { id: "karaoke", label: "Karaoke", note: "current word highlighted yellow" },
  { id: "minimal", label: "Minimal", note: "small clean white text" },
  { id: "bold", label: "Bold creator", note: "very large bold text" },
  {
    id: "highlighted",
    label: "Highlighted keywords",
    note: "long / emphatic words in yellow",
  },
];

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

function fmtT(v: number) {
  return `${v.toFixed(1)}s`;
}

export default function ClipEditorPage({ params }: { params: { id: string } }) {
  const clipId = Number(params.id);
  const [clip, setClip] = useState<ClipDetail | null>(null);
  const [captions, setCaptions] = useState<ClipCaptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waveError, setWaveError] = useState<string | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [thumbUrl, setThumbUrl] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const waveRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionRef = useRef<Region | null>(null);
  const syncingRef = useRef(false); // video <-> waveform playhead sync
  const regionSyncRef = useRef(false); // region <-> inputs sync guard

  // Editor state. Trim is highlight-relative (seconds into the highlight
  // window); trimBase is where the currently loaded rendered clip starts
  // inside that window, so the waveform region (clip-relative) converts
  // as trim = trimBase + region.
  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(0);
  const [trimBase, setTrimBase] = useState(0);
  const [style, setStyle] = useState("karaoke");
  const [framingOffset, setFramingOffset] = useState(0);
  const [volume, setVolume] = useState(1);
  const [editedCaptions, setEditedCaptions] = useState<
    Record<number, string>
  >({});
  const [job, setJob] = useState<Job | null>(null);
  const [jobNote, setJobNote] = useState<string | null>(null);
  // Which scorer picked this clip's highlight ("llm" | "heuristic"),
  // from GET /api/projects/{id}/highlights — shown verbatim, never
  // claimed as LLM when the heuristic ran.
  const [scorer, setScorer] = useState<string | null>(null);

  // Refs mirror the state the wavesurfer callbacks need (they close over
  // the values from the render that created them).
  const trimBaseRef = useRef(0);
  const trimStartRef = useRef(0);
  const trimEndRef = useRef(0);
  trimBaseRef.current = trimBase;
  trimStartRef.current = trimStart;
  trimEndRef.current = trimEnd;

  const hlDuration = clip?.highlight_duration_sec ?? clip?.duration_sec ?? 0;

  const loadClip = useCallback(async () => {
    const c = await api.getClip(clipId);
    setClip(c);
    const p = (c.edit_params ?? {}) as Record<string, unknown>;
    const base = typeof p.trim_start === "number" ? p.trim_start : 0;
    const start = typeof p.trim_start === "number" ? p.trim_start : 0;
    const end =
      typeof p.trim_end === "number"
        ? p.trim_end
        : c.highlight_duration_sec ?? c.duration_sec ?? 0;
    setTrimBase(base);
    setTrimStart(start);
    setTrimEnd(end);
    setStyle(typeof p.style === "string" ? p.style : "karaoke");
    setFramingOffset(
      typeof p.framing_offset === "number" ? p.framing_offset : 0
    );
    setVolume(typeof p.volume === "number" ? p.volume : 1);
    setEditedCaptions({});
    const caps = await api.getClipCaptions(clipId);
    setCaptions(caps);
    // Scorer label for this clip's highlight (best-effort: the editor
    // still works if the highlights call fails).
    try {
      const hls = await api.listHighlights(c.project_id);
      const hl = hls.find((h) => h.id === c.highlight_id);
      setScorer(hl ? hl.scorer : null);
    } catch {
      setScorer(null);
    }
    return c;
  }, [clipId]);

  // Initial load.
  useEffect(() => {
    loadClip().catch((e) => setError(e.message));
  }, [loadClip]);

  // Fetch the clip file with the auth token and expose it as a blob URL.
  useEffect(() => {
    if (!clip) return;
    let url: string | null = null;
    let cancelled = false;
    api
      .fetchClipBlobUrl(clip.id)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        url = u;
        setVideoUrl(u);
      })
      .catch((e) => setError(e.message));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [clip]);

  // Thumbnail preview, if one is set.
  useEffect(() => {
    if (!clip?.has_thumbnail) {
      setThumbUrl(null);
      return;
    }
    let url: string | null = null;
    let cancelled = false;
    api
      .fetchThumbnailBlobUrl(clip.id)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        url = u;
        setThumbUrl(u);
      })
      .catch(() => setThumbUrl(null));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [clip]);

  // wavesurfer.js waveform + draggable trim region: decodes the clip
  // audio, tap-to-seek moves the video playhead, playhead follows
  // playback. The region is the trim window, clip-relative.
  useEffect(() => {
    if (!clip || !videoUrl || !waveRef.current) return;
    let cancelled = false;
    let ws: WaveSurfer | null = null;
    (async () => {
      try {
        const { default: WaveSurferCtor } = await import("wavesurfer.js");
        const { default: RegionsPlugin } = await import(
          "wavesurfer.js/dist/plugins/regions"
        );
        if (cancelled || !waveRef.current) return;
        ws = WaveSurferCtor.create({
          container: waveRef.current,
          url: videoUrl,
          waveColor: "#4b5563",
          progressColor: "#f59e0b",
          height: 80,
        });
        wsRef.current = ws;
        const regions = ws.registerPlugin(RegionsPlugin.create());
        ws.on("error", () => {
          if (!cancelled) {
            setWaveError(
              "Waveform could not load the clip audio (the video player above still works)."
            );
          }
        });
        // Tapping the waveform seeks the video to that point.
        ws.on("seeking", (t: number) => {
          if (syncingRef.current) return;
          const video = videoRef.current;
          if (video) video.currentTime = t;
        });
        ws.on("ready", () => {
          if (cancelled || !ws) return;
          const dur = ws.getDuration() || clip.duration_sec || 0;
          const start = clamp(trimStartRef.current - trimBaseRef.current, 0, dur);
          const end = clamp(trimEndRef.current - trimBaseRef.current, 0, dur);
          const region = regions.addRegion({
            start,
            end: Math.max(end, start + 0.1),
            drag: true,
            resize: true,
            minLength: 2,
            color: "rgba(245, 158, 11, 0.3)",
          });
          regionRef.current = region;
          // Dragging/resizing the region updates the trim inputs.
          region.on("update-end", () => {
            if (regionSyncRef.current) return;
            const base = trimBaseRef.current;
            setTrimStart(Number((base + region.start).toFixed(2)));
            setTrimEnd(Number((base + region.end).toFixed(2)));
          });
        });
      } catch {
        if (!cancelled) {
          setWaveError("Waveform library failed to load — video player still works.");
        }
      }
    })();
    return () => {
      cancelled = true;
      ws?.destroy();
      wsRef.current = null;
      regionRef.current = null;
    };
    // Re-created when the clip file changes (new version after a
    // re-render) so the waveform + region match the new file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip, videoUrl]);

  // Keep the waveform playhead following the video while it plays.
  function handleVideoTimeUpdate() {
    const video = videoRef.current;
    const ws = wsRef.current;
    if (!video || !ws) return;
    syncingRef.current = true;
    try {
      ws.setTime(video.currentTime);
    } catch {
      /* waveform not ready yet */
    }
    syncingRef.current = false;
  }

  // Push the trim inputs into the waveform region (guarded so the
  // region's own update-end event does not echo back).
  function syncRegionToInputs(start: number, end: number) {
    const region = regionRef.current;
    const dur = clip?.duration_sec ?? 0;
    if (!region || !dur) return;
    regionSyncRef.current = true;
    try {
      region.setOptions({
        start: clamp(start - trimBase, 0, dur),
        end: clamp(end - trimBase, 0, dur),
      });
    } finally {
      regionSyncRef.current = false;
    }
  }

  function onTrimInput(which: "start" | "end", value: number) {
    const v = Number.isFinite(value) ? value : 0;
    let start = trimStart;
    let end = trimEnd;
    if (which === "start") start = clamp(v, 0, hlDuration);
    else end = clamp(v, 0, hlDuration);
    // Keep start < end (min 2s is enforced server-side on apply).
    if (start >= end) {
      if (which === "start") end = Math.min(hlDuration, start + 2);
      else start = Math.max(0, end - 2);
    }
    setTrimStart(start);
    setTrimEnd(end);
    syncRegionToInputs(start, end);
  }

  // Poll a job until it finishes, then reload the clip. Returns the
  // final job so callers can show its error.
  async function pollJob(jobId: number): Promise<Job> {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      const j = await api.getJob(jobId);
      setJob(j);
      if (j.status === "done" || j.status === "failed") return j;
    }
  }

  function captionOverrides(): CaptionOverride[] {
    if (!captions) return [];
    const out: CaptionOverride[] = [];
    for (const g of captions.groups) {
      const edited = editedCaptions[g.index];
      if (edited !== undefined && edited !== g.text) {
        out.push({ group_index: g.index, text: edited });
      }
    }
    return out;
  }

  async function handleApply() {
    if (!clip) return;
    setError(null);
    setJobNote("Starting re-render…");
    try {
      const j = await api.reRenderClip(clip.id, {
        trim_start: trimStart,
        trim_end: trimEnd,
        caption_overrides: captionOverrides(),
        style,
        framing_offset: framingOffset,
        volume,
      });
      setJob(j);
      setJobNote(`Re-rendering… ${j.progress}%`);
      const final = await pollJob(j.id);
      if (final.status === "done") {
        setJobNote("Re-render done — reloading the new version…");
        await loadClip();
        setJobNote(null);
        setJob(null);
      } else {
        setJobNote(null);
        setError(`Re-render failed: ${final.error ?? "unknown error"}`);
      }
    } catch (e) {
      setJobNote(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRegenerate() {
    if (!clip) return;
    setError(null);
    setJobNote("Starting clean re-render…");
    try {
      const j = await api.regenerateClip(clip.id);
      setJob(j);
      const final = await pollJob(j.id);
      if (final.status === "done") {
        setJobNote("Regenerated — reloading…");
        await loadClip();
        setJobNote(null);
        setJob(null);
      } else {
        setJobNote(null);
        setError(`Regenerate failed: ${final.error ?? "unknown error"}`);
      }
    } catch (e) {
      setJobNote(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleSetThumbnail() {
    if (!clip) return;
    const video = videoRef.current;
    if (!video) return;
    setError(null);
    try {
      const t = video.currentTime;
      await api.setThumbnail(clip.id, t);
      const url = await api.fetchThumbnailBlobUrl(clip.id);
      setThumbUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return url;
      });
      setClip((c) => (c ? { ...c, has_thumbnail: true } : c));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (error && !clip) return <p className="text-sm text-red-300">{error}</p>;
  if (!clip) return <p className="text-sm text-gray-400">Loading clip…</p>;

  const newDuration = Math.max(0, trimEnd - trimStart);
  const busy = job !== null && (job.status === "queued" || job.status === "running");

  return (
    <div className="space-y-6">
      <Link href={`/projects/${clip.project_id}`} className="text-sm text-amber-500">
        ← Back to project
      </Link>
      <div>
        <h1 className="text-2xl font-bold text-white">{clip.title}</h1>
        <p className="mt-1 text-sm text-gray-400">
          {clip.width}×{clip.height} · {clip.duration_sec?.toFixed(1)}s ·{" "}
          {clip.status} · version {clip.version}
        </p>
      </div>

      {error && (
        <p className="rounded-lg border border-red-900 bg-red-950 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          <video
            ref={videoRef}
            src={videoUrl ?? undefined}
            controls
            playsInline
            onTimeUpdate={handleVideoTimeUpdate}
            className="aspect-[9/16] w-full max-w-xs rounded-xl border border-gray-800 bg-black"
          />
          {thumbUrl && (
            <section className="rounded-xl border border-gray-800 bg-panel p-4">
              <h2 className="text-sm font-semibold text-white">Thumbnail</h2>
              <img
                src={thumbUrl}
                alt="Clip thumbnail"
                className="mt-2 w-full max-w-xs rounded-lg border border-gray-800"
              />
            </section>
          )}
          <section className="rounded-xl border border-gray-800 bg-panel p-4">
            <h2 className="text-sm font-semibold text-white">
              Audio waveform — tap to seek, drag the orange region to trim
            </h2>
            {waveError ? (
              <p className="mt-2 text-xs text-amber-300">{waveError}</p>
            ) : (
              <div ref={waveRef} className="mt-2 w-full" />
            )}
            <p className="mt-2 text-xs text-gray-500">
              The orange region is the trim window. Drag it or its edges, or
              type the times below — they stay in sync. Tapping the waveform
              moves the video playhead; it follows playback while the video
              plays.
            </p>
          </section>
        </div>

        <div className="space-y-4">
          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            <h2 className="font-semibold text-white">Clip info</h2>
            <p className="mt-1 text-sm text-gray-400">
              {clip.width}×{clip.height} · {clip.duration_sec?.toFixed(1)}s ·{" "}
              {clip.status} · version {clip.version}
              {clip.highlight_duration_sec
                ? ` · highlight window ${clip.highlight_duration_sec.toFixed(1)}s`
                : ""}
              {scorer ? ` · Scored by: ${scorer === "llm" ? "LLM" : "Heuristic"}` : ""}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() =>
                  api
                    .downloadClip(clip.id, `${clip.title}.mp4`)
                    .catch((e) => setError(e.message))
                }
                className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-black hover:bg-amber-400"
              >
                Download MP4
              </button>
              <button
                onClick={handleSetThumbnail}
                disabled={busy}
                className="rounded-lg border border-gray-700 px-4 py-2 text-sm font-semibold text-gray-200 hover:border-gray-500 disabled:opacity-50"
              >
                Set thumbnail from current frame
              </button>
              <button
                onClick={handleRegenerate}
                disabled={busy}
                className="rounded-lg border border-gray-700 px-4 py-2 text-sm font-semibold text-gray-200 hover:border-gray-500 disabled:opacity-50"
              >
                Regenerate clip
              </button>
            </div>
            <p className="mt-2 text-xs text-gray-500">
              Thumbnail: pauses the video where you want it and taps the
              button — the frame at that moment becomes the clip thumbnail.
              Regenerate re-renders the same window with the current edits,
              e.g. after a failed render.
            </p>
          </section>

          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            <h2 className="font-semibold text-white">Trim</h2>
            <p className="mt-1 text-xs text-gray-400">
              Times are seconds into the highlight window (
              {hlDuration.toFixed(1)}s). The trim is applied when you
              re-render, not in the browser.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <label className="block text-sm text-gray-300">
                Trim start (s)
                <input
                  type="number"
                  min={0}
                  max={hlDuration}
                  step={0.1}
                  value={trimStart}
                  onChange={(e) => onTrimInput("start", Number(e.target.value))}
                  className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2 text-sm"
                />
              </label>
              <label className="block text-sm text-gray-300">
                Trim end (s)
                <input
                  type="number"
                  min={0}
                  max={hlDuration}
                  step={0.1}
                  value={trimEnd}
                  onChange={(e) => onTrimInput("end", Number(e.target.value))}
                  className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2 text-sm"
                />
              </label>
            </div>
            <p className="mt-2 text-sm text-gray-300">
              New duration:{" "}
              <span className="font-semibold text-white">
                {newDuration.toFixed(1)}s
              </span>{" "}
              <span className="text-gray-500">
                (was {clip.duration_sec?.toFixed(1)}s)
              </span>
            </p>
          </section>

          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            <h2 className="font-semibold text-white">Captions</h2>
            <p className="mt-1 text-xs text-gray-400">
              Edit the words — the re-render burns the new text in. Edited
              words are spread evenly across their group&apos;s time span
              (not re-transcribed). Empty text removes that caption group.
            </p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {STYLES.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setStyle(s.id)}
                  className={`rounded-lg border px-3 py-2 text-left text-sm ${
                    style === s.id
                      ? "border-amber-500 bg-amber-500/10 text-white"
                      : "border-gray-700 text-gray-300 hover:border-gray-500"
                  }`}
                >
                  <span className="block font-semibold">{s.label}</span>
                  <span className="block text-xs text-gray-500">{s.note}</span>
                </button>
              ))}
            </div>
            <div className="mt-4 space-y-3">
              {captions === null && (
                <p className="text-sm text-gray-500">Loading captions…</p>
              )}
              {captions?.groups.map((g) => (
                <label key={g.index} className="block text-sm text-gray-300">
                  <span className="text-xs text-gray-500">
                    {fmtT(g.start_sec)} – {fmtT(g.end_sec)}
                  </span>
                  <input
                    type="text"
                    value={editedCaptions[g.index] ?? g.text}
                    onChange={(e) =>
                      setEditedCaptions((prev) => ({
                        ...prev,
                        [g.index]: e.target.value,
                      }))
                    }
                    className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2 text-sm"
                  />
                </label>
              ))}
              {captions && captions.groups.length === 0 && (
                <p className="text-sm text-gray-500">
                  No caption words in this window.
                </p>
              )}
            </div>
          </section>

          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            <h2 className="font-semibold text-white">Framing &amp; audio</h2>
            <label className="mt-3 block text-sm text-gray-300">
              Framing nudge:{" "}
              <span className="font-semibold text-white">
                {framingOffset === 0
                  ? "centred"
                  : framingOffset > 0
                    ? `+${framingOffset.toFixed(2)} right`
                    : `${framingOffset.toFixed(2)} left`}
              </span>
              <input
                type="range"
                min={-1}
                max={1}
                step={0.05}
                value={framingOffset}
                onChange={(e) => setFramingOffset(Number(e.target.value))}
                className="mt-1 w-full accent-amber-500"
              />
            </label>
            <p className="mt-1 text-xs text-gray-500">
              Shifts the 9:16 crop window sideways from the face-track
              centre (or from centre when no face is found). No live
              preview — the crop only moves in the re-rendered file.
            </p>
            <label className="mt-4 block text-sm text-gray-300">
              Volume:{" "}
              <span className="font-semibold text-white">
                ×{volume.toFixed(2)}
              </span>
              <input
                type="range"
                min={0.25}
                max={2}
                step={0.05}
                value={volume}
                onChange={(e) => setVolume(Number(e.target.value))}
                className="mt-1 w-full accent-amber-500"
              />
            </label>
            <p className="mt-1 text-xs text-gray-500">
              0.25× is much quieter, 2× is twice as loud.
            </p>
          </section>

          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            {jobNote && (
              <p className="mb-3 text-sm text-amber-300">{jobNote}</p>
            )}
            {job && busy && (
              <div className="mb-3">
                <div className="h-2 w-full overflow-hidden rounded-full bg-gray-800">
                  <div
                    className="h-full bg-amber-500 transition-all"
                    style={{ width: `${job.progress}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-gray-400">
                  Job {job.id} · {job.status} · {job.progress}%
                </p>
              </div>
            )}
            <button
              onClick={handleApply}
              disabled={busy}
              className="w-full rounded-lg bg-amber-500 px-4 py-2.5 font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
            >
              Apply &amp; re-render
            </button>
            <p className="mt-2 text-xs text-gray-500">
              Re-renders the clip with the trim, captions, style, framing
              and volume above, and saves it as a new version (v
              {clip.version + 1}). The old version is replaced only once
              the new render succeeds.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
