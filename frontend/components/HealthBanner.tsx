"use client";

import useSWR from "swr";
import { fetcher, API_BASE } from "@/lib/api";
import { AlertCircle, ShieldAlert } from "lucide-react";

/**
 * Two banners stacked:
 *   • Red "Backend unreachable" when /health fails (Next.js can't reach FastAPI)
 *   • Amber "LIVE blocked" when LIVE_ONLY=true and broker isn't authenticated
 */
export function HealthBanner() {
  const { data: health, error: healthErr } = useSWR<{ status: string }>(
    "/api/health", fetcher,
    { refreshInterval: 5_000, shouldRetryOnError: true, errorRetryInterval: 3_000 }
  );
  const { data: brokerStatus } = useSWR<any>(
    "/api/broker/status", fetcher,
    { refreshInterval: 15_000 }
  );

  const backendOk = health?.status === "ok";

  return (
    <>
      {!backendOk && (
        <div className="bg-accent-red/15 border-b border-accent-red text-accent-red px-4 py-2 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span className="font-semibold">Backend unreachable</span>
          <span className="text-text-secondary">
            — every panel will show "—" until this clears. Open <a href="/settings"
              className="underline text-accent-amber">Settings → Connection Diagnostic</a>{" "}
            for a fix checklist. Frontend tried:{" "}
            <code className="text-accent-amber">{API_BASE || "(same-origin /api proxy)"}</code>
          </span>
          {healthErr && <span className="text-text-muted">{`(${String(healthErr.message).slice(0, 100)})`}</span>}
        </div>
      )}

      {backendOk && brokerStatus?.live_blocked && (
        <div className="bg-accent-amber/15 border-b border-accent-amber text-accent-amber px-4 py-2 text-xs flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span className="font-semibold">LIVE_ONLY mode — Angel One login required</span>
          <span className="text-text-secondary">
            — market-data endpoints are returning 503 until login succeeds. Auto-retry every 5 minutes.
            Open <a href="/settings" className="underline text-accent-amber">Settings</a>{" "}
            and click "Diagnose" to see why login failed.
          </span>
          {brokerStatus.last_login_error && (
            <span className="text-text-muted ml-auto truncate max-w-[400px]"
                  title={brokerStatus.last_login_error}>
              {brokerStatus.last_login_error.slice(0, 80)}…
            </span>
          )}
        </div>
      )}
    </>
  );
}
