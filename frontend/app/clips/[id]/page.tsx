"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type WaveSurfer from "wavesurfer.js";
import { api, type Clip } from "../../../lib/api";

/**
 * Editor page skeleton, wired to real clip data.
 * The wavesurfer.js waveform below is REAL: it decodes the clip's audio,
 * renders the waveform, tapping it seeks the video, and it follows video
 * playback. Trimming / caption-style controls are NOT implemented yet —
 * they are shown disabled and labelled "Coming soon" rather than
 * pretending to work.
 */
export default function ClipEditorPage({ params }: { params: { id: string } }) {
  const clipId = Number(params.id);
  const [clip, setClip] = useState<Clip | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waveError, setWaveError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const waveRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const syncingRef = useRef(false);

  useEffect(() => {
    // The clip list endpoint is per-project; find the clip via its project
    // by scanning projects. Simple and honest for Phase 1.
    api
      .listProjects()
      .then(async (projects) => {
        for (const p of projects) {
          const clips = await api.listClips(p.id);
          const found = clips.find((c) => c.id === clipId);
          if (found) {
            setClip(found);
            return;
          }
        }
        setError("Clip not found.");
      })
      .catch((e) => setError(e.message));
  }, [clipId]);

  // wavesurfer.js waveform: decodes the clip audio (backend must allow
  // CORS from this origin), tap-to-seek the video, follows playback.
  useEffect(() => {
    if (!clip || !waveRef.current) return;
    let cancelled = false;
    let ws: WaveSurfer | null = null;
    (async () => {
      try {
        const { default: WaveSurferCtor } = await import("wavesurfer.js");
        if (cancelled || !waveRef.current) return;
        ws = WaveSurferCtor.create({
          container: waveRef.current,
          url: api.clipDownloadUrl(clip.id),
          waveColor: "#4b5563",
          progressColor: "#f59e0b",
          height: 80,
        });
        wsRef.current = ws;
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
    };
  }, [clip]);

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

  if (error) return <p className="text-sm text-red-300">{error}</p>;
  if (!clip) return <p className="text-sm text-gray-400">Loading clip…</p>;

  return (
    <div className="space-y-6">
      <Link href={`/projects/${clip.project_id}`} className="text-sm text-amber-500">
        ← Back to project
      </Link>
      <h1 className="text-2xl font-bold text-white">{clip.title}</h1>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          <video
            ref={videoRef}
            src={api.clipDownloadUrl(clip.id)}
            controls
            playsInline
            onTimeUpdate={handleVideoTimeUpdate}
            className="aspect-[9/16] w-full max-w-xs rounded-xl border border-gray-800 bg-black"
          />
          <section className="rounded-xl border border-gray-800 bg-panel p-4">
            <h2 className="text-sm font-semibold text-white">
              Audio waveform — tap to seek
            </h2>
            {waveError ? (
              <p className="mt-2 text-xs text-amber-300">{waveError}</p>
            ) : (
              <div ref={waveRef} className="mt-2 w-full" />
            )}
            <p className="mt-2 text-xs text-gray-500">
              Powered by wavesurfer.js. Tapping the waveform moves the video
              playhead; it follows playback while the video plays.
            </p>
          </section>
        </div>
        <div className="space-y-4">
          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            <h2 className="font-semibold text-white">Clip info</h2>
            <p className="mt-1 text-sm text-gray-400">
              {clip.width}×{clip.height} · {clip.duration_sec?.toFixed(1)}s ·{" "}
              {clip.status}
            </p>
            <a
              href={api.clipDownloadUrl(clip.id)}
              download
              className="mt-3 inline-block rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-black hover:bg-amber-400"
            >
              Download MP4
            </a>
          </section>

          <section className="rounded-xl border border-gray-800 bg-panel p-5">
            <h2 className="font-semibold text-white">Editor</h2>
            <p className="mt-1 text-xs text-gray-400">
              The editor is a skeleton in Phase 1. Controls below are not
              wired yet.
            </p>
            <label className="mt-4 block text-sm text-gray-300">
              Trim start (seconds)
              <input
                type="number"
                disabled
                placeholder="Coming soon"
                className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2 text-sm disabled:opacity-50"
              />
            </label>
            <label className="mt-3 block text-sm text-gray-300">
              Trim end (seconds)
              <input
                type="number"
                disabled
                placeholder="Coming soon"
                className="mt-1 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2 text-sm disabled:opacity-50"
              />
            </label>
            <label className="mt-3 flex items-center gap-2 text-sm text-gray-300">
              <input type="checkbox" disabled /> Captions on (Coming soon)
            </label>
            <button
              disabled
              className="mt-4 w-full rounded-lg bg-gray-700 px-4 py-2.5 font-semibold text-gray-300 disabled:opacity-50"
            >
              Apply trim — Coming soon
            </button>
          </section>
        </div>
      </div>
    </div>
  );
}
