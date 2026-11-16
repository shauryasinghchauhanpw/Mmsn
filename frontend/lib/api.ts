// API client — Phase 2, step 1: JWT auth.
// The JWT is stored in localStorage ("mmsn_token") and attached as
// `Authorization: Bearer <token>` to every request. Any 401 clears the
// stored token (logout / expired / invalid). Logout is client-side token
// discard — the server keeps no token list (see backend/app/auth.py).
// NOTE: clip files are fetched with auth too (fetch + blob URL), because a
// plain <a href> / <video src> cannot send an Authorization header.

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const TOKEN_KEY = "mmsn_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

export interface UserMe {
  id: number;
  email: string;
  name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  is_verified: boolean;
}

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
  version: number;
  has_thumbnail: boolean;
  created_at: string;
}

// Single-clip editor detail: Clip plus the highlight window the clip
// was cut from (trim is relative to this window) and stored edit params.
export interface ClipDetail extends Clip {
  highlight_start_sec: number | null;
  highlight_end_sec: number | null;
  highlight_duration_sec: number | null;
  edit_params: Record<string, unknown>;
}

export interface CaptionGroup {
  index: number;
  start_sec: number;
  end_sec: number;
  text: string;
}

export interface CaptionOverride {
  group_index: number;
  text: string;
}

export interface ClipCaptions {
  clip_id: number;
  style: string;
  groups: CaptionGroup[];
  overrides: CaptionOverride[];
  window_start_sec: number;
  window_end_sec: number;
}

export interface ReRenderParams {
  trim_start?: number;
  trim_end?: number;
  caption_overrides?: CaptionOverride[];
  style?: string;
  framing_offset?: number;
  volume?: number;
}

export interface ThumbnailInfo {
  clip_id: number;
  t: number;
  thumbnail_url: string;
}

export interface Highlight {
  id: number;
  project_id: number;
  start_sec: number;
  end_sec: number;
  score: number;
  // "llm" only when an LLM response actually produced this highlight,
  // otherwise "heuristic" — the UI shows exactly this value.
  scorer: string;
  reasons: string[];
  title: string | null;
  description: string | null;
  hashtags: string[];
}

async function handle(res: Response) {
  if (res.status === 401) {
    // Token invalid/expired — drop it so the auth guard sends the user
    // to /login instead of retrying with a dead token.
    clearToken();
  }
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
    const err = new Error(msg || `Request failed (${res.status})`) as Error & {
      status: number;
    };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  health: () => fetch(`${API_URL}/health`).then(handle),

  // ── Auth ──────────────────────────────────────────────────────────────
  register: async (
    email: string,
    password: string,
    name?: string
  ): Promise<UserMe> => {
    const res = await fetch(`${API_URL}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name: name || undefined }),
    });
    return handle(res);
  },
  login: async (email: string, password: string): Promise<string> => {
    // OAuth2 password form: username=<email>&password=<password>
    const form = new URLSearchParams();
    form.append("username", email);
    form.append("password", password);
    const res = await fetch(`${API_URL}/auth/jwt/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    const data = await handle(res);
    setToken(data.access_token);
    return data.access_token as string;
  },
  logout: () => {
    clearToken();
    // Best-effort server logout call (bearer logout is a no-op
    // server-side — the real logout is discarding the token above).
    fetch(`${API_URL}/auth/jwt/logout`, {
      method: "POST",
      headers: authHeaders(),
    }).catch(() => {});
  },
  getMe: (): Promise<UserMe> =>
    fetch(`${API_URL}/users/me`, { headers: authHeaders() }).then(handle),

  // ── Projects / jobs / clips (all authenticated) ───────────────────────
  listProjects: (): Promise<Project[]> =>
    fetch(`${API_URL}/api/projects`, { headers: authHeaders() }).then(handle),
  getProject: (id: number): Promise<Project> =>
    fetch(`${API_URL}/api/projects/${id}`, { headers: authHeaders() }).then(
      handle
    ),
  uploadProject: async (file: File): Promise<Project> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/api/projects/upload`, {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    return handle(res);
  },
  addYouTubeLink: (url: string): Promise<Project> =>
    fetch(`${API_URL}/api/projects/youtube`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ url }),
    }).then(handle),
  processProject: (id: number): Promise<Job> =>
    fetch(`${API_URL}/api/projects/${id}/process`, {
      method: "POST",
      headers: authHeaders(),
    }).then(handle),
  getJob: (id: number): Promise<Job> =>
    fetch(`${API_URL}/api/jobs/${id}`, { headers: authHeaders() }).then(
      handle
    ),
  listClips: (projectId: number): Promise<Clip[]> =>
    fetch(`${API_URL}/api/projects/${projectId}/clips`, {
      headers: authHeaders(),
    }).then(handle),
  listHighlights: (projectId: number): Promise<Highlight[]> =>
    fetch(`${API_URL}/api/projects/${projectId}/highlights`, {
      headers: authHeaders(),
    }).then(handle),

  // ── Editor (Phase 2, step 2) ──────────────────────────────────────────
  getClip: (id: number): Promise<ClipDetail> =>
    fetch(`${API_URL}/api/clips/${id}`, { headers: authHeaders() }).then(
      handle
    ),
  getClipCaptions: (id: number): Promise<ClipCaptions> =>
    fetch(`${API_URL}/api/clips/${id}/captions`, {
      headers: authHeaders(),
    }).then(handle),
  reRenderClip: (id: number, params: ReRenderParams): Promise<Job> =>
    fetch(`${API_URL}/api/clips/${id}/re-render`, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(params),
    }).then(handle),
  regenerateClip: (id: number): Promise<Job> =>
    fetch(`${API_URL}/api/clips/${id}/regenerate`, {
      method: "POST",
      headers: authHeaders(),
    }).then(handle),
  setThumbnail: (id: number, t: number): Promise<ThumbnailInfo> =>
    fetch(`${API_URL}/api/clips/${id}/thumbnail?t=${encodeURIComponent(t)}`, {
      method: "POST",
      headers: authHeaders(),
    }).then(handle),
  // Thumbnail JPEG, fetched with the token and served as a blob URL.
  fetchThumbnailBlobUrl: async (clipId: number): Promise<string> => {
    const res = await fetch(`${API_URL}/api/clips/${clipId}/thumbnail`, {
      headers: authHeaders(),
    });
    if (res.status === 401) clearToken();
    if (!res.ok) {
      throw new Error(`Could not load thumbnail (${res.status})`);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },

  // Clip files need the token, so they are fetched (not plain links) and
  // served to the browser as a blob URL. Callers must revoke the URL
  // (URL.revokeObjectURL) when done with it.
  fetchClipBlobUrl: async (clipId: number): Promise<string> => {
    const res = await fetch(`${API_URL}/api/clips/${clipId}/download`, {
      headers: authHeaders(),
    });
    if (res.status === 401) clearToken();
    if (!res.ok) {
      throw new Error(`Could not load clip (${res.status})`);
    }
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  downloadClip: async (clipId: number, filename?: string): Promise<void> => {
    const url = await api.fetchClipBlobUrl(clipId);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || `mmsn-clip-${clipId}.mp4`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Give the browser a moment to start the download before revoking.
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  },
};

export function formatDuration(sec: number | null | undefined): string {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}
