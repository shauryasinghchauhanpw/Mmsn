"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { api, formatDuration, type Project } from "../lib/api";

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = () => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e) => setError(e.message));
  };

  useEffect(refresh, []);

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const project = await api.uploadProject(file);
      setNotice(`Uploaded “${project.title}”. Open it to process it into clips.`);
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleYouTube() {
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const project = await api.addYouTubeLink(url.trim());
      setNotice(
        `Saved metadata for “${project.title}”. A link alone cannot make clips — upload the video file to process it.`
      );
      setUrl("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not fetch metadata");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-bold text-white">
          Turn a long video into Shorts
        </h1>
        <p className="mt-1 text-sm text-gray-400">
          Upload your own video — the AI transcribes it, finds the best
          moments, and renders vertical 1080×1920 clips with captions.
        </p>
      </section>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-emerald-800 bg-emerald-950/60 px-4 py-3 text-sm text-emerald-200">
          {notice}
        </div>
      )}

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-gray-800 bg-panel p-5">
          <h2 className="font-semibold text-white">📤 Upload a video</h2>
          <p className="mt-1 text-xs text-gray-400">
            MP4 / MOV / MKV / WebM, up to 2 GB. This is the primary path.
          </p>
          <input
            ref={fileRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => handleUpload(e.target.files?.[0])}
          />
          <button
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            className="mt-4 w-full rounded-lg bg-amber-500 px-4 py-3 font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
          >
            {busy ? "Working…" : "Choose video file"}
          </button>
        </div>

        <div className="rounded-xl border border-gray-800 bg-panel p-5">
          <h2 className="font-semibold text-white">🔗 Paste a YouTube link</h2>
          <p className="mt-1 text-xs text-gray-400">
            Fetches title, duration and thumbnail only (YouTube Data API).
            A link alone cannot make clips — no video is downloaded.
          </p>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=…"
            className="mt-4 w-full rounded-lg border border-gray-700 bg-ink px-3 py-2 text-sm text-white placeholder-gray-500"
          />
          <button
            disabled={busy || !url.trim()}
            onClick={handleYouTube}
            className="mt-3 w-full rounded-lg border border-gray-600 px-4 py-2.5 font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
          >
            {busy ? "Working…" : "Fetch metadata"}
          </button>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white">Your projects</h2>
        {projects.length === 0 ? (
          <p className="mt-2 text-sm text-gray-400">
            No projects yet — upload a video to start.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {projects.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-gray-800 bg-panel px-4 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-white">{p.title}</p>
                  <p className="text-xs text-gray-400">
                    {p.source_type === "upload" ? "Upload" : "YouTube link"} ·{" "}
                    {formatDuration(p.duration_sec)} · {p.status}
                  </p>
                </div>
                <Link
                  href={`/projects/${p.id}`}
                  className="shrink-0 rounded-lg bg-gray-800 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700"
                >
                  Open →
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
