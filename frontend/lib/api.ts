// Thin client for the FastAPI backend.
//
// IMPORTANT — we use SAME-ORIGIN relative URLs (`/api/...`).
//   Next.js's rewrite (see `next.config.js`) proxies `/api/*` to the
//   FastAPI backend on the SAME machine (localhost:8000).
//
// Why this matters operationally:
//   • Only port 3000 (Next.js) needs to be open in the VM firewall.
//   • No CORS configuration needed — calls are same-origin from the browser's
//     perspective.
//   • Works identically on localhost, on a public IP, behind nginx, or behind
//     a custom domain — without changing a single env var.
//
// If you ever want to bypass the proxy (e.g. when the frontend and backend
// run on different hosts), set NEXT_PUBLIC_API_BASE in frontend/.env.local.

function resolveApiBase(): string {
  // Explicit override (rare — only when frontend/backend are on different hosts)
  if (process.env.NEXT_PUBLIC_API_BASE) return process.env.NEXT_PUBLIC_API_BASE;
  // Default: same-origin. Browser hits the Next.js server which proxies to backend.
  return "";
}

export const API_BASE = resolveApiBase();

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  fullAnalysis: (body: { symbol: string; exchange?: string; horizon?: string; capital?: number; timeframe?: string }) =>
    req<any>("/api/analysis/full", { method: "POST", body: JSON.stringify(body) }),

  liveSignals: (symbols?: string) =>
    req<any>(`/api/signals/live${symbols ? `?symbols=${encodeURIComponent(symbols)}` : ""}`),

  recentSignals: () => req<any>("/api/signals/recent?limit=20"),

  transits: () => req<any>("/api/astrology/transits"),
  marketSentiment: () => req<any>("/api/astrology/market-sentiment"),
  moonPhase: () => req<any>("/api/astrology/moon-phase"),

  symbolNumerology: (symbol: string) => req<any>(`/api/numerology/symbol/${symbol}`),

  square9: (price: number, levels = 8) =>
    req<any>("/api/gann/square9", { method: "POST", body: JSON.stringify({ price, levels }) }),

  timeCycles: (anchor_date: string) =>
    req<any>("/api/gann/time-cycles", { method: "POST", body: JSON.stringify({ anchor_date }) }),

  syntheticOptions: (symbol: string, spot: number) =>
    req<any>(`/api/options/synthetic/${symbol}?spot=${spot}`),

  brokerStatus: () => req<any>("/api/broker/status"),

  brokerLogin: (body: any = {}) =>
    req<any>("/api/broker/login", { method: "POST", body: JSON.stringify(body) }),

  placeOrder: (body: any) =>
    req<any>("/api/broker/order", { method: "POST", body: JSON.stringify(body) }),
};

export const fetcher = <T,>(url: string) => req<T>(url);
