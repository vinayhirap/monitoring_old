// Frontend auth: token storage + an authed fetcher that auto-attaches the
// Authorization header. Replaces the plain `fetcher` from lib/api.ts for any
// SWR call that needs auth.

const ACCESS_KEY  = "marketlens_access";
const REFRESH_KEY = "marketlens_refresh";
const USER_KEY    = "marketlens_user";

export type User = {
  id: number;
  email: string;
  full_name: string | null;
  role?: "OWNER" | "ADMIN" | "ANALYST" | "USER";
  is_superuser: boolean;     // deprecated — prefer role
};

// Single source of truth for "is this user an admin?" Backend now derives
// is_superuser from role, but historic localStorage payloads may have
// is_superuser=true with role=USER (the privilege-escalation hole we closed).
// Trust role when present; fall back to the boolean only when role is missing.
const ADMIN_ROLES = new Set(["OWNER", "ADMIN", "ANALYST"]);

export function isAdmin(user: User | null): boolean {
  if (!user) return false;
  if (user.role) return ADMIN_ROLES.has(user.role);
  return Boolean(user.is_superuser);
}

export function saveSession(access: string, refresh: string, user: User) {
  if (typeof window === "undefined") return;
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  if (typeof window === "undefined") return;
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? JSON.parse(raw) : null;
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}

// ---------------------------------------------------------------------------
// Authed fetch — attaches Bearer token, attempts refresh on 401 once
// ---------------------------------------------------------------------------

async function refreshIfPossible(): Promise<string | null> {
  const rt = getRefreshToken();
  if (!rt) return null;
  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    saveSession(data.access_token, data.refresh_token, data.user);
    return data.access_token;
  } catch {
    return null;
  }
}

export async function authedFetch(path: string, init: RequestInit = {}) {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res = await fetch(path, { ...init, headers, cache: "no-store" });
  if (res.status === 401 && token) {
    const fresh = await refreshIfPossible();
    if (fresh) {
      headers["Authorization"] = `Bearer ${fresh}`;
      res = await fetch(path, { ...init, headers, cache: "no-store" });
    } else {
      clearSession();
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
  }
  return res;
}

/**
 * Error thrown by `authedFetcher` when the backend returns a non-2xx response.
 * Pages can check `err.status` (especially 402) to render upgrade prompts
 * instead of generic error states.
 *
 * `body` is the parsed response JSON when available — the backend's structured
 * 402 payload is `{ message, current_tier, required_tier, upgrade_url }`.
 */
export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, statusText: string, body: any) {
    const text = typeof body === "string"
      ? body
      : (body?.detail?.message || body?.message || JSON.stringify(body));
    super(`${status} ${statusText} — ${text}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export const authedFetcher = async <T,>(path: string): Promise<T> => {
  const res = await authedFetch(path);
  if (!res.ok) {
    // Try to parse JSON body for structured error info; fall back to text.
    let body: any;
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      try { body = await res.json(); } catch { body = await res.text(); }
    } else {
      body = await res.text();
    }
    // For 402 (tier-gated endpoint), fire a global event so the mounted
    // UpgradeModal can pop up automatically. Each page that uses authedFetcher
    // also gets the thrown error and can render its own contextual message —
    // the modal is a fallback so users never see a raw "402 — upgrade required"
    // error message and wonder what to do.
    if (res.status === 402 && typeof window !== "undefined") {
      // Backend shape: { detail: { message, current_tier, required_tier, upgrade_url } }
      // OR sometimes flat: { message, current_tier, required_tier, upgrade_url }
      const detail = body?.detail && typeof body.detail === "object" ? body.detail : body;
      window.dispatchEvent(new CustomEvent("marketlens:upgrade-required", { detail: detail || {} }));
    }
    throw new ApiError(res.status, res.statusText, body);
  }
  return res.json();
};
