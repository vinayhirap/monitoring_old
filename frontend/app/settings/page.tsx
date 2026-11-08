"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { fetcher, api, API_BASE } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { CheckCircle2, XCircle, AlertCircle, Loader2 } from "lucide-react";

export default function SettingsPage() {
  const { data: status, mutate, error: statusError } =
    useSWR<any>("/api/broker/status", fetcher, { errorRetryCount: 1 });

  const [creds, setCreds] = useState({ api_key: "", client_code: "", password: "", totp: "" });
  const [msg, setMsg] = useState<string>("");
  const [busy, setBusy] = useState(false);

  // Connection diagnostic
  const [diag, setDiag] = useState<{ ok: boolean; latency_ms?: number; error?: string } | null>(null);
  async function testConnection() {
    setDiag(null);
    const t0 = performance.now();
    try {
      const r = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      setDiag({ ok: true, latency_ms: Math.round(performance.now() - t0) });
    } catch (e: any) {
      setDiag({ ok: false, error: e.message });
    }
  }
  useEffect(() => { testConnection(); }, []);

  async function login() {
    setBusy(true); setMsg("");
    try {
      // Cleanup: never send fields the user left blank
      const body: any = {};
      if (creds.api_key)     body.api_key = creds.api_key.trim();
      if (creds.client_code) body.client_code = creds.client_code.trim();
      if (creds.password)    body.password = creds.password.trim();
      if (creds.totp)        body.totp = creds.totp.trim();
      const res = await api.brokerLogin(body);
      setMsg(`${res.status.toUpperCase()} — ${res.message}`);
      mutate();
    } catch (e: any) {
      // Detect network/CORS failures and give actionable help
      const isNetwork = /failed to fetch|networkerror|cors|load failed/i.test(e.message || "");
      setMsg(isNetwork
        ? `NETWORK ERROR — the browser couldn't reach the backend at ${API_BASE}. ` +
          `Open ${API_BASE}/health in a new tab; if that fails, the backend isn't reachable from your browser.`
        : `Error: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  // TOTP code length warning (must be 6 digits if entered)
  const totpLooksWrong = creds.totp && !/^\d{6}$/.test(creds.totp.trim());

  return (
    <div className="grid grid-cols-12 gap-4">
      {/* ──────── Connection diagnostic ──────── */}
      <div className="col-span-12">
        <Panel title="Connection Diagnostic"
          right={
            <button onClick={testConnection}
              className="text-[11px] text-accent-amber underline">
              re-test
            </button>
          }
        >
          <div className="space-y-1.5 text-[12px]">
            <div>
              <span className="text-text-muted">Browser is calling backend at:</span>{" "}
              <code className="text-accent-amber">{API_BASE}</code>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-text-muted">/health probe:</span>
              {diag === null && <span className="flex items-center gap-1 text-text-muted">
                <Loader2 className="w-3 h-3 animate-spin" /> testing…
              </span>}
              {diag?.ok && <span className="flex items-center gap-1 text-accent-green">
                <CheckCircle2 className="w-3.5 h-3.5" /> reachable ({diag.latency_ms}ms)
              </span>}
              {diag && !diag.ok && <span className="flex items-center gap-1 text-accent-red">
                <XCircle className="w-3.5 h-3.5" /> {diag.error}
              </span>}
            </div>

            {diag && !diag.ok && (
              <div className="mt-3 p-2 border border-accent-red/40 bg-accent-red/5 rounded text-[11px] text-text-secondary space-y-1">
                <div className="text-accent-red font-semibold">Backend unreachable. Try in order:</div>
                <ol className="list-decimal pl-5 space-y-0.5">
                  <li>Confirm backend is running — terminal should show <code>uvicorn running on http://0.0.0.0:8000</code></li>
                  <li>Open <a href={`${API_BASE.startsWith("http") ? API_BASE : "http://localhost:8000"}/health`}
                              target="_blank" rel="noreferrer"
                              className="text-accent-amber underline">{API_BASE}/health</a> directly in a new browser tab</li>
                  <li>If you're hosting on a remote VM, allow inbound port <code>8000</code> in firewall / security group</li>
                  <li>Set <code>NEXT_PUBLIC_API_BASE</code> in <code>frontend/.env.local</code> to the URL you actually open the backend at, then restart <code>npm run dev</code></li>
                  <li>Confirm backend's <code>CORS_ORIGINS</code> in <code>.env</code> includes the URL you opened this UI at (currently <code>{typeof window !== "undefined" ? window.location.origin : "?"}</code>)</li>
                </ol>
              </div>
            )}
          </div>
        </Panel>
      </div>

      {/* ──────── Angel One login ──────── */}
      <div className="col-span-12 lg:col-span-6">
        <Panel title="Angel One SmartAPI — Login">
          <div className="space-y-2 text-[12px]">
            <Field label="API Key" value={creds.api_key}
              onChange={(v) => setCreds({ ...creds, api_key: v })}
              placeholder="from smartapi.angelbroking.com (or set ANGELONE_API_KEY in .env)" />
            <Field label="Client Code" value={creds.client_code}
              onChange={(v) => setCreds({ ...creds, client_code: v })}
              placeholder="e.g. A123456 (or set ANGELONE_CLIENT_CODE in .env)" />

            {/* MPIN — required by SmartAPI */}
            <div>
              <label className="text-[10px] uppercase text-accent-amber font-bold flex items-center gap-2">
                MPIN (4-digit) — REQUIRED
              </label>
              <input
                type="password"
                inputMode="numeric"
                maxLength={6}
                value={creds.password}
                onChange={(e) => setCreds({ ...creds, password: e.target.value })}
                className="w-full bg-bg-base border border-accent-amber/40 rounded px-3 py-1.5 font-mono tabular"
                placeholder="4-digit trading MPIN (or set ANGELONE_PASSWORD in .env)"
              />
              <div className="text-[10px] text-text-muted mt-1">
                This is the 4-digit MPIN, NOT your website login password. SmartAPI rejects
                login with "Invalid password parameter" if blank.
              </div>
            </div>

            <div>
              <label className="text-[10px] uppercase text-text-muted flex items-center gap-2">
                TOTP <span className="normal-case text-text-muted">— 6-digit code (not the secret!)</span>
              </label>
              <input
                type="text"
                inputMode="numeric"
                maxLength={8}
                value={creds.totp}
                onChange={(e) => setCreds({ ...creds, totp: e.target.value })}
                className="w-full bg-bg-base border border-bg-line rounded px-3 py-1.5 font-mono tabular"
                placeholder="leave blank to auto-generate from ANGELONE_TOTP_SECRET in .env"
              />
              {totpLooksWrong && (
                <div className="mt-1 flex items-start gap-1 text-[11px] text-accent-red">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>That looks like a TOTP <span className="font-bold">secret</span> (base32 string), not a 6-digit code.
                    Put the secret in <code>.env</code> as <code>ANGELONE_TOTP_SECRET</code> and leave this field blank.
                    OR open Google Authenticator and type the 6 digits shown.</span>
                </div>
              )}
            </div>

            <div className="mt-2 p-2 border border-bg-line bg-bg-base/40 rounded text-[10px] text-text-secondary">
              <span className="text-accent-amber">Easiest setup:</span> put all four values in <code>.env</code> at the
              project root, restart the backend, then leave every field above BLANK and click Login.
              The backend will read from <code>.env</code> and auto-generate the TOTP code from the secret.
            </div>

            <button
              onClick={login}
              disabled={busy}
              className="mt-3 w-full px-4 py-2 bg-accent-amber text-black rounded text-sm font-semibold hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Logging in…" : "Login"}
            </button>
            {msg && (
              <div className={`text-[11px] mt-1 ${
                msg.includes("OK") ? "text-accent-green"
                : msg.startsWith("NETWORK") ? "text-accent-red" : "text-accent-amber"
              }`}>
                {msg}
              </div>
            )}
          </div>
        </Panel>
      </div>

      {/* ──────── Connection status ──────── */}
      <div className="col-span-12 lg:col-span-6">
        <Panel title="Broker Connection Status">
          {statusError && (
            <div className="text-accent-red text-[11px] mb-2">
              Couldn't load status — {statusError.message?.slice(0, 200)}
            </div>
          )}
          <pre className="text-[11px] text-text-secondary tabular overflow-auto">
            {JSON.stringify(status || { unavailable: true }, null, 2)}
          </pre>
        </Panel>
      </div>

      {/* ──────── Disclaimer ──────── */}
      <div className="col-span-12">
        <Panel title="Disclaimer">
          <p className="text-[12px] text-text-secondary leading-relaxed">
            MarketLens is for <span className="text-accent-amber">educational and analytical purposes only</span>.
            It is <span className="text-accent-amber">not SEBI-registered</span> investment advice.
            Astrology and numerology layers are positioned as an
            <em> alternative analytical layer / experimental confluence enhancement</em> —
            never as guaranteed predictors of market movement.
          </p>
          <p className="text-[12px] text-text-secondary mt-2">
            Always verify signals against your own technical and fundamental analysis,
            apply strict risk management, and never deploy more capital than you can afford to lose.
            Past performance does not guarantee future results.
          </p>
        </Panel>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }:
                { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label className="text-[10px] uppercase text-text-muted">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full bg-bg-base border border-bg-line rounded px-3 py-1.5 font-mono"
        placeholder={placeholder} />
    </div>
  );
}
