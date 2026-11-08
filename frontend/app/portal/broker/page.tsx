"use client";

/**
 * Per-user Connect Broker page.
 *
 * The user pastes their own Angel One credentials (API key, client code,
 * TOTP secret, password). The backend validates by attempting a live
 * login, then stores them encrypted via Fernet.
 *
 * After connecting:
 *   • Trade placement uses THIS user's broker account
 *   • Orders/positions/holdings are THEIR data, not the operator's
 *   • Session token auto-refreshes every ~24h from stored credentials
 *
 * Disconnecting wipes the encrypted credentials immediately.
 */

import { useState, useEffect } from "react";
import useSWR, { mutate } from "swr";
import Link from "next/link";
import { authedFetcher as fetcher, authedFetch } from "@/lib/auth";
import {
  ShieldCheck, Plug, AlertTriangle, Eye, EyeOff, RefreshCw, Trash2,
  CheckCircle2, ExternalLink,
} from "lucide-react";
import clsx from "clsx";


export default function BrokerConnectPage() {
  const { data: status, isLoading } = useSWR<any>(
    "/api/broker/me/status", fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false });

  const [apiKey, setApiKey] = useState("");
  const [clientCode, setClientCode] = useState("");
  const [totpSecret, setTotpSecret] = useState("");
  const [password, setPassword] = useState("");
  const [showSecrets, setShowSecrets] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // Pre-fill nothing — credentials are intentionally NEVER returned by the API

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(""); setSuccess("");
    try {
      const res = await authedFetch("/api/broker/me/connect", {
        method: "POST",
        body: JSON.stringify({
          api_key:     apiKey.trim(),
          client_code: clientCode.trim(),
          totp_secret: totpSecret.trim(),
          password:    password.trim(),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || data.message || `HTTP ${res.status}`);
        return;
      }
      setSuccess(data.message || "Broker connected successfully.");
      // Clear sensitive inputs from memory immediately
      setApiKey(""); setClientCode(""); setTotpSecret(""); setPassword("");
      mutate("/api/broker/me/status");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect() {
    if (!confirm("Disconnect your broker? Stored credentials will be wiped. " +
                  "You'll need to enter them again to place future trades.")) return;
    setBusy(true); setError(""); setSuccess("");
    try {
      await authedFetch("/api/broker/me/disconnect", { method: "DELETE" });
      setSuccess("Broker disconnected.");
      mutate("/api/broker/me/status");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const isConnected = status?.connected;

  return (
    <div className="space-y-4 max-w-2xl">
      {/* Header */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <h1 className="text-lg font-bold text-text-primary flex items-center gap-2">
          <Plug className="w-5 h-5 text-accent-amber" />
          Connect Your Broker
        </h1>
        <p className="text-[11px] text-text-muted mt-1">
          Connect YOUR own Angel One account. Live trades are placed against
          your account, your funds, your name. We store your credentials encrypted
          with industry-standard symmetric encryption (Fernet/AES-128-CBC + HMAC).
        </p>
      </div>

      {/* Current status */}
      <div className={clsx("border rounded-lg p-4 flex items-start gap-3",
        isConnected
          ? "bg-accent-green/5 border-accent-green/40"
          : "bg-bg-surface border-bg-line")}>
        {isConnected ? (
          <CheckCircle2 className="w-6 h-6 text-accent-green shrink-0" />
        ) : (
          <ShieldCheck className="w-6 h-6 text-text-muted shrink-0" />
        )}
        <div className="flex-1">
          <div className={clsx("font-bold",
            isConnected ? "text-accent-green" : "text-text-primary")}>
            {isLoading ? "Checking…" : isConnected ? "Broker connected" : "No broker connected"}
          </div>
          {status?.session_expires_at && (
            <div className="text-[11px] text-text-muted mt-0.5">
              Session expires: {new Date(status.session_expires_at).toLocaleString("en-IN")}
            </div>
          )}
          {status?.last_login_error && (
            <div className="text-[11px] text-accent-red mt-1">
              Last login error: {status.last_login_error}
            </div>
          )}
          {isConnected && (
            <button onClick={handleDisconnect} disabled={busy}
              className="mt-2 text-[11px] flex items-center gap-1 text-accent-red hover:underline disabled:opacity-50">
              <Trash2 className="w-3 h-3" /> Disconnect broker
            </button>
          )}
        </div>
      </div>

      {/* Form — shown when not connected */}
      {!isConnected && (
        <form onSubmit={handleConnect} className="bg-bg-surface border border-bg-line rounded-lg p-4 space-y-4">
          <div className="text-[11px] text-text-secondary">
            <a href="https://smartapi.angelone.in/" target="_blank" rel="noopener"
               className="text-accent-amber hover:underline inline-flex items-center gap-1">
              Get your Angel One API key <ExternalLink className="w-3 h-3" />
            </a>
            {" — "}then paste the values from your Angel One developer dashboard below.
          </div>

          <Field label="API Key"
                   value={apiKey} onChange={setApiKey} type="text"
                   placeholder="From smartapi.angelone.in" />

          <Field label="Client Code (Angel One ID)"
                   value={clientCode} onChange={setClientCode} type="text"
                   placeholder="e.g. A123456" />

          <Field label="TOTP Secret (base32)"
                   value={totpSecret} onChange={setTotpSecret}
                   type={showSecrets ? "text" : "password"}
                   placeholder="Scan QR in Angel One app, then 'Manual entry' to reveal" />

          <Field label="Password (your Angel One login PIN, if required)"
                   value={password} onChange={setPassword}
                   type={showSecrets ? "text" : "password"}
                   placeholder="Required only if your account uses PIN+TOTP" />

          <label className="flex items-center gap-2 text-[11px] text-text-muted cursor-pointer">
            <input type="checkbox" checked={showSecrets}
                    onChange={(e) => setShowSecrets(e.target.checked)} />
            {showSecrets
              ? <EyeOff className="w-3 h-3" />
              : <Eye className="w-3 h-3" />}
            Show secrets (only while typing — never logged)
          </label>

          {error && (
            <div className="border border-accent-red/40 bg-accent-red/10 rounded p-3 text-[11px] text-accent-red flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>{error}</div>
            </div>
          )}

          {success && (
            <div className="border border-accent-green/40 bg-accent-green/10 rounded p-3 text-[11px] text-accent-green flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" /> {success}
            </div>
          )}

          <button type="submit" disabled={busy}
            className="w-full bg-accent-amber text-white font-bold py-2 px-4 rounded hover:bg-accent-gold disabled:opacity-50 flex items-center justify-center gap-2">
            {busy ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />}
            {busy ? "Validating with Angel One…" : "Connect"}
          </button>
        </form>
      )}

      {/* Security note */}
      <div className="bg-bg-surface/60 border border-bg-line rounded-lg p-3 text-[11px] text-text-secondary">
        <div className="font-bold text-accent-amber uppercase mb-1 tracking-wider">
          What we do with your credentials
        </div>
        <ul className="space-y-0.5 list-disc list-inside ml-1">
          <li><strong>Encrypted at rest</strong> — Fernet (AES-128 CBC + HMAC SHA256). Even with full DB access, an attacker cannot decrypt without the platform's master key.</li>
          <li><strong>Used only to authenticate with Angel One</strong> on your behalf — for placing/cancelling/modifying YOUR orders, fetching YOUR positions.</li>
          <li><strong>Never logged, never displayed back</strong> — once you submit, the API gives no way to retrieve them in cleartext.</li>
          <li><strong>Auto-refresh</strong> — session tokens expire ~24h; we re-authenticate using your stored credentials.</li>
          <li><strong>Revocation</strong> — clicking "Disconnect" wipes them immediately. You can also rotate your Angel One API key from their dashboard at any time.</li>
        </ul>
      </div>

      <div className="text-center pt-2">
        <Link href="/portal/profile" className="text-[11px] text-text-muted hover:text-accent-amber">
          ← Back to profile
        </Link>
      </div>
    </div>
  );
}


function Field({ label, value, onChange, type = "text", placeholder = "" }:
                 { label: string; value: string; onChange: (v: string) => void;
                   type?: string; placeholder?: string }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase text-text-muted font-semibold tracking-wider mb-1">
        {label}
      </div>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        className="w-full bg-bg-base border border-bg-line rounded px-3 py-2 text-sm text-text-primary focus:border-accent-amber outline-none"
      />
    </label>
  );
}
