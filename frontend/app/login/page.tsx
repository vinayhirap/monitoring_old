"use client";

import { useState, FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { saveSession } from "@/lib/auth";
import { Activity, LogIn, AlertCircle } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // OAuth2 password flow expects form-urlencoded with `username` field
      const body = new URLSearchParams();
      body.set("username", email);
      body.set("password", password);
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      saveSession(data.access_token, data.refresh_token, data.user);
      router.replace(next);
    } catch (e: any) {
      setError(e.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg-base p-4">
      <div className="w-full max-w-md">
        <div className="flex items-center justify-center gap-2 mb-6">
          <Activity className="w-7 h-7 text-accent-amber" />
          <h1 className="text-2xl font-extrabold brand-gradient tracking-wider">MARKETLENS</h1>
        </div>

        <div className="bg-panel-grad rounded p-6 shadow-card">
          <h2 className="text-lg font-semibold text-text-primary mb-1">Sign in</h2>
          <p className="text-[11px] text-text-muted mb-5">
            Access your trading terminal
          </p>

          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-muted block mb-1">
                Email
              </label>
              <input
                type="email" required autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded border border-bg-line bg-bg-surface focus:border-accent-amber"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-muted block mb-1">
                Password
              </label>
              <input
                type="password" required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded border border-bg-line bg-bg-surface focus:border-accent-amber"
              />
            </div>

            {error && (
              <div className="text-[11px] text-accent-red flex items-start gap-2 bg-accent-red/5 border border-accent-red/20 rounded p-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit" disabled={busy}
              className="w-full bg-accent-amber text-white font-bold py-2 rounded hover:bg-accent-gold disabled:opacity-50 flex items-center justify-center gap-2"
            >
              <LogIn className="w-4 h-4" />
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <div className="text-[11px] text-text-muted text-center mt-4 border-t border-bg-line pt-3">
            New here?{" "}
            <Link href="/signup" className="text-accent-amber hover:underline">
              Create an account
            </Link>
          </div>
        </div>

        <p className="text-[10px] text-text-muted text-center mt-4">
          Educational/analytical platform only. Not SEBI-registered advice.
        </p>
      </div>
    </div>
  );
}
