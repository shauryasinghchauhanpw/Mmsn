const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Project {
  id: number;
  title: string;
  source_type: string;
  source_url: string | null;
  youtube_video_id: string | null;
  thumbnail_url: string | null;
  duration_sec: number | null;
  status: string;
  created_at: string;
}

export interface Job {
  id: number;
  project_id: number;
  kind: string;
  status: string;
  progress: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Clip {
  id: number;
  project_id: number;
  highlight_id: number | null;
  title: string;
  width: number;
  height: number;
  duration_sec: number | null;
  file_size_bytes: number | null;
  status: string;
  created_at: string;
}

export interface Highlight {
  id: number;
  project_id: number;
  start_sec: number;
  end_sec: number;
  score: number;
  reasons: string[];
  title: string | null;
  description: string | null;
  hashtags: string[];
}

async function handle(res: Response) {
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body;
    } catch {
      /* keep statusText */
    }
    const msg =
      typeof detail === "object" && detail !== null && "message" in detail
        ? String((detail as { message: string }).message)
        : typeof detail === "string"
          ? detail
          : JSON.stringify(detail);
    throw new Error(msg || `Request failed (${res.status})`);
  }
  return res.json();
}

export const api = {
  health: () => fetch(`${API_URL}/health`).then(handle),
  listProjects: (): Promise<Project[]> =>
    fetch(`${API_URL}/api/projects`).then(handle),
  getProject: (id: number): Promise<Project> =>
    fetch(`${API_URL}/api/projects/${id}`).then(handle),
  uploadProject: async (file: File): Promise<Project> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/api/projects/upload`, {
      method: "POST",
      body: form,
    });
    return handle(res);
  },
  addYouTubeLink: (url: string): Promise<Project> =>
    fetch(`${API_URL}/api/projects/youtube`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }).then(handle),
  processProject: (id: number): Promise<Job> =>
    fetch(`${API_URL}/api/projects/${id}/process`, { method: "POST" }).then(
      handle
    ),
  getJob: (id: number): Promise<Job> =>
    fetch(`${API_URL}/api/jobs/${id}`).then(handle),
  listClips: (projectId: number): Promise<Clip[]> =>
    fetch(`${API_URL}/api/projects/${projectId}/clips`).then(handle),
  listHighlights: (projectId: number): Promise<Highlight[]> =>
    fetch(`${API_URL}/api/projects/${projectId}/highlights`).then(handle),
  clipDownloadUrl: (clipId: number) => `${API_URL}/api/clips/${clipId}/download`,
};

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
