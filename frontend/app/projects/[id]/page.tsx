"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, formatDuration, type Clip, type Highlight, type Job, type Project } from "../../../lib/api";

export default function ProjectPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const [project, setProject] = useState<Project | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getProject(projectId).then(setProject).catch((e) => setError(e.message));
    api.listClips(projectId).then(setClips).catch(() => {});
    api.listHighlights(projectId).then(setHighlights).catch(() => {});
  }, [projectId]);

  // Poll while a job is running.
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    const t = setInterval(() => {
      api
        .getJob(job.id)
        .then((j) => {
          setJob(j);
          if (j.status === "done") {
            api.listClips(projectId).then(setClips);
            api.listHighlights(projectId).then(setHighlights);
            api.getProject(projectId).then(setProject);
          }
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [job, projectId]);

  async function startProcessing() {
    setError(null);
    try {
      const j = await api.processProject(projectId);
      setJob(j);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start processing");
    }
  }

  if (error && !project) {
    return <p className="text-sm text-red-300">{error}</p>;
  }
  if (!project) return <p className="text-sm text-gray-400">Loading…</p>;

  const canProcess = project.source_type === "upload";

  return (
    <div className="space-y-6">
      <Link href="/" className="text-sm text-amber-500">
        ← All projects
      </Link>
      <div>
        <h1 className="text-2xl font-bold text-white">{project.title}</h1>
        <p className="mt-1 text-sm text-gray-400">
          {project.source_type === "upload" ? "Upload" : "YouTube link"} ·{" "}
          {formatDuration(project.duration_sec)} · Status: {project.status}
        </p>
        {project.source_type === "youtube_link" && (
          <p className="mt-2 rounded-lg border border-amber-800 bg-amber-950/50 px-3 py-2 text-sm text-amber-200">
            This project only has metadata from the YouTube link. Upload the
            video file to generate clips — links are never downloaded.
          </p>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      <section className="rounded-xl border border-gray-800 bg-panel p-5">
        <h2 className="font-semibold text-white">Processing</h2>
        {job ? (
          <div className="mt-3">
            <p className="text-sm">
              Status: <strong>{job.status}</strong> · {job.progress}%
            </p>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-800">
              <div
                className="h-full bg-amber-500"
                style={{ width: `${job.progress}%` }}
              />
            </div>
            {job.error && (
              <p className="mt-2 text-sm text-red-300">{job.error}</p>
            )}
          </div>
        ) : (
          <p className="mt-2 text-sm text-gray-400">
            Not processed yet. Processing transcribes the video, scores the
            best moments and renders vertical clips.
          </p>
        )}
        <button
          disabled={!canProcess || (job?.status === "running" || job?.status === "queued")}
          onClick={startProcessing}
          className="mt-4 rounded-lg bg-amber-500 px-4 py-2.5 font-semibold text-black hover:bg-amber-400 disabled:opacity-50"
        >
          {job?.status === "running" || job?.status === "queued"
            ? "Processing…"
            : "Process into clips"}
        </button>
      </section>

      <section>
        <h2 className="text-lg font-semibold text-white">
          Clips ({clips.length})
        </h2>
        {clips.length === 0 ? (
          <p className="mt-2 text-sm text-gray-400">
            No clips yet — process the project first.
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {clips.map((clip) => {
              const hl = highlights.find((h) => h.id === clip.highlight_id);
              return (
                <li
                  key={clip.id}
                  className="rounded-xl border border-gray-800 bg-panel px-4 py-3"
                >
                  <p className="font-medium text-white">{clip.title}</p>
                  <p className="text-xs text-gray-400">
                    {clip.width}×{clip.height} ·{" "}
                    {formatDuration(clip.duration_sec)}
                    {hl ? ` · Virality ${hl.score}/100` : ""}
                    {hl ? ` · Scored by: ${hl.scorer === "llm" ? "LLM" : "Heuristic"}` : ""}
                  </p>
                  {hl && hl.reasons.length > 0 && (
                    <p className="mt-1 text-xs text-gray-400">
                      Why: {hl.reasons.join(" · ")}
                    </p>
                  )}
                  <div className="mt-3 flex gap-2">
                    <Link
                      href={`/clips/${clip.id}`}
                      className="rounded-lg bg-gray-800 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700"
                    >
                      Open in editor
                    </Link>
                    <button
                      onClick={() =>
                        api
                          .downloadClip(clip.id, `${clip.title}.mp4`)
                          .catch((e) => setError(e.message))
                      }
                      className="rounded-lg bg-amber-500 px-3 py-2 text-sm font-semibold text-black hover:bg-amber-400"
                    >
                      Download MP4
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
