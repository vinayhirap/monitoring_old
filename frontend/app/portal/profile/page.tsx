"use client";

import useSWR from "swr";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { authedFetcher, authedFetch, getUser, clearSession, isAdmin } from "@/lib/auth";
import {
  ShieldCheck, Star, MessageCircle, LogOut, Sparkles, CheckCircle2, XCircle, Crown,
} from "lucide-react";
import { SubscriptionTierCard } from "@/components/SubscriptionTierCard";
import clsx from "clsx";


type Subscription = {
  tier: string;
  is_active: boolean;
  valid_until: string | null;
  started_at: string;
  telegram_username: string | null;
  features: any;
};


export default function PortalProfilePage() {
  const router = useRouter();
  const user = getUser();
  const { data: sub, mutate } = useSWR<Subscription>("/api/portal/me/subscription", authedFetcher);

  const [tg, setTg] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function saveTelegram(e: React.FormEvent) {
    e.preventDefault();
    if (!tg.trim()) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await authedFetch("/api/portal/me/telegram", {
        method: "POST",
        body: JSON.stringify({ telegram_username: tg.trim().replace(/^@/, "") }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "save failed");
      setMsg(data.message || "Saved");
      mutate();
    } catch (e: any) {
      setMsg(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  function logout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="space-y-4 max-w-3xl">
      {/* Profile header */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-text-primary">
              {user?.full_name || user?.email?.split("@")[0]}
            </h1>
            <p className="text-[12px] text-text-muted">{user?.email}</p>
          </div>
          {isAdmin(user) && (
            <span className="inline-flex items-center gap-1 text-[10px] uppercase font-bold text-accent-amber border border-accent-amber/40 rounded px-2 py-1 bg-accent-amber/10">
              <ShieldCheck className="w-3 h-3" />
              Admin
            </span>
          )}
        </div>
      </div>

      {/* Subscription tier */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-bold text-text-primary flex items-center gap-2">
            <Crown className="w-4 h-4 text-accent-amber" />
            My Plan
          </h2>
          {sub && (
            <TierBadge tier={sub.tier} />
          )}
        </div>

        {sub && (
          <>
            {/* Plan summary */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-[11px]">
              <Field label="Active" value={sub.is_active ? "Yes" : "No"}
                color={sub.is_active ? "text-accent-green" : "text-accent-red"} />
              <Field label="Valid until"
                value={sub.valid_until ? new Date(sub.valid_until).toLocaleDateString() : "No expiry"} />
              <Field label="Started"
                value={new Date(sub.started_at).toLocaleDateString()} />
            </div>

            {/* Feature breakdown */}
            <div className="mt-4 pt-4 border-t border-bg-line">
              <h3 className="text-[10px] uppercase text-text-muted font-bold tracking-wider mb-2">
                What's included
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
                <FeatureRow ok={sub.features.fno_recommendations} label="F&O recommendations" />
                <FeatureRow ok={sub.features.commodities} label="MCX commodities" />
                <FeatureRow ok={sub.features.intraday_signals} label="Intraday signals" />
                <FeatureRow ok={sub.features.live_options_strategy} label="Live options strategy" />
                <FeatureRow ok={sub.features.max_picks_per_day === -1 || sub.features.max_picks_per_day > 20}
                  label={`${sub.features.max_picks_per_day === -1 ? "Unlimited" : sub.features.max_picks_per_day} picks/day`} />
                <FeatureRow ok={sub.features.delay_minutes === 0} label={
                  sub.features.delay_minutes === 0 ? "Real-time signals" : `${sub.features.delay_minutes}-min delayed`
                } />
              </div>
            </div>

            {/* Telegram channel */}
            {sub.features.telegram_channel && (
              <div className="mt-4 pt-4 border-t border-bg-line">
                <h3 className="text-[10px] uppercase text-text-muted font-bold tracking-wider mb-2 flex items-center gap-1.5">
                  <MessageCircle className="w-3 h-3 text-accent-amber" />
                  Telegram channel access
                </h3>
                {sub.telegram_username ? (
                  <div className="text-[11px] text-text-secondary">
                    Registered: <strong>@{sub.telegram_username}</strong>
                    {" — "}<span className="text-text-muted">
                      Admin will add you to the {sub.features.telegram_channel} channel shortly.
                    </span>
                  </div>
                ) : (
                  <form onSubmit={saveTelegram} className="flex gap-2 items-end">
                    <div className="flex-1">
                      <label className="text-[10px] uppercase text-text-muted block mb-1">
                        Your Telegram username (e.g. @trader123)
                      </label>
                      <input value={tg} onChange={(e) => setTg(e.target.value)}
                        placeholder="@yourusername"
                        className="w-full px-3 py-2 text-sm rounded border border-bg-line bg-bg-base focus:border-accent-amber" />
                    </div>
                    <button type="submit" disabled={saving || !tg.trim()}
                      className="bg-accent-amber text-white font-bold px-4 py-2 rounded text-sm hover:bg-accent-gold disabled:opacity-50">
                      {saving ? "Saving…" : "Register"}
                    </button>
                  </form>
                )}
                {msg && <p className="text-[11px] text-text-muted mt-2">{msg}</p>}
              </div>
            )}
          </>
        )}
      </div>

      {/* Tier ladder + Razorpay checkout — works in either mode:
            • Razorpay configured → "Upgrade" buttons open Razorpay Checkout
            • Razorpay not configured → falls back to "Contact admin" CTA */}
      {sub && (
        <div className="bg-bg-surface border border-bg-line rounded-lg p-5">
          <h2 className="font-bold text-text-primary flex items-center gap-2 mb-1">
            <Sparkles className="w-4 h-4 text-accent-amber" />
            Plans &amp; pricing
          </h2>
          <p className="text-[11px] text-text-muted mb-4">
            Higher tiers unlock more picks, F&amp;O recommendations, MCX commodities,
            real-time signals, and the corresponding Telegram channel.
          </p>
          <SubscriptionTierCard currentTier={sub.tier as any} />
        </div>
      )}

      {/* Sign out */}
      <div className="text-center pt-6">
        <button onClick={logout}
          className="text-[12px] text-accent-red hover:underline flex items-center gap-1.5 mx-auto">
          <LogOut className="w-3.5 h-3.5" /> Sign out
        </button>
      </div>
    </div>
  );
}


function TierBadge({ tier }: { tier: string }) {
  const cfg: any = {
    FREE:         { color: "bg-text-muted/15 text-text-secondary border-text-muted/30", icon: Star, stars: 1 },
    BASIC:        { color: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",   icon: Star, stars: 2 },
    INTERMEDIATE: { color: "bg-accent-violet/15 text-accent-violet border-accent-violet/30", icon: Sparkles, stars: 3 },
    ADVANCED:    { color: "bg-accent-amber/15 text-accent-amber border-accent-amber/40", icon: Crown, stars: 5 },
  }[tier] || { color: "bg-text-muted/15 text-text-muted border-text-muted/30", icon: Star, stars: 1 };
  const Icon = cfg.icon;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 px-3 py-1 rounded-full border font-bold text-[11px] uppercase tracking-wider", cfg.color)}>
      <Icon className="w-3.5 h-3.5" />
      {tier}
    </span>
  );
}

function Field({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div className="text-[9px] uppercase text-text-muted tracking-wider">{label}</div>
      <div className={clsx("font-semibold tabular", color || "text-text-primary")}>{value}</div>
    </div>
  );
}

function FeatureRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {ok
        ? <CheckCircle2 className="w-3.5 h-3.5 text-accent-green shrink-0" />
        : <XCircle className="w-3.5 h-3.5 text-text-muted/50 shrink-0" />}
      <span className={ok ? "text-text-primary" : "text-text-muted line-through"}>{label}</span>
    </div>
  );
}

