"use client";

import { useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { saveSession } from "@/lib/auth";
import { Activity, UserPlus, AlertCircle } from "lucide-react";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, full_name: fullName || null }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      // Auto-login after signup
      const body = new URLSearchParams();
      body.set("username", email);
      body.set("password", password);
      const loginRes = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });
      if (!loginRes.ok) throw new Error("Signup succeeded but auto-login failed — try logging in manually");
      const data = await loginRes.json();
      saveSession(data.access_token, data.refresh_token, data.user);
      router.replace("/");
    } catch (e: any) {
      setError(e.message || "Signup failed");
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
          <h2 className="text-lg font-semibold text-text-primary mb-1">Create account</h2>
          <p className="text-[11px] text-text-muted mb-5">
            The first account becomes the admin automatically.
          </p>

          <form onSubmit={onSubmit} className="space-y-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-muted block mb-1">
                Full name (optional)
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded border border-bg-line bg-bg-surface focus:border-accent-amber"
                placeholder="Mahesh Chauthe"
              />
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-muted block mb-1">
                Email
              </label>
              <input
                type="email" required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded border border-bg-line bg-bg-surface focus:border-accent-amber"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-muted block mb-1">
                Password (min 6 chars)
              </label>
              <input
                type="password" required minLength={6}
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
              <UserPlus className="w-4 h-4" />
              {busy ? "Creating…" : "Create account"}
            </button>
          </form>

          <div className="text-[11px] text-text-muted text-center mt-4 border-t border-bg-line pt-3">
            Already have an account?{" "}
            <Link href="/login" className="text-accent-amber hover:underline">
              Sign in
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
