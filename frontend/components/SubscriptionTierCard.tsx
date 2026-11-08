"use client";

/**
 * Side-by-side tier comparison + Razorpay checkout.
 *
 * Renders all four tiers (FREE/BASIC/INTERMEDIATE/ADVANCED) as columns
 * with price, feature checklist, and an "Upgrade" CTA. Clicking Upgrade
 * server-creates a Razorpay subscription and opens Razorpay Checkout.
 *
 * Self-contained — drop it anywhere. Optionally pass `currentTier` to
 * highlight the user's plan; otherwise it reads from /api/portal/me/subscription.
 *
 * Falls back gracefully when Razorpay is not configured (config endpoint
 * returns configured=false): renders the tiers but replaces "Upgrade" with
 * a "Contact admin" CTA so the page still tells a coherent story.
 */

import useSWR from "swr";
import { useState, useEffect, useCallback } from "react";
import { authedFetcher, authedFetch, getUser } from "@/lib/auth";
import { Crown, Sparkles, Star, CheckCircle2, XCircle, Loader2, AlertCircle } from "lucide-react";
import clsx from "clsx";


const TIERS = ["FREE", "BASIC", "INTERMEDIATE", "ADVANCED"] as const;
type Tier = typeof TIERS[number];

const TIER_RANK: Record<Tier, number> = { FREE: 0, BASIC: 1, INTERMEDIATE: 2, ADVANCED: 3 };


type RazorpayConfig = {
  configured: boolean;
  key_id: string | null;
  plans: Record<string, { plan_id: string; price_inr: number }>;
  currency: string;
};

type Subscription = {
  tier: string;
  is_active: boolean;
  valid_until: string | null;
  features: any;
};

type StartSubscriptionResponse = {
  subscription_id: string;
  short_url: string;
  key_id: string;
  tier: string;
  amount_inr: number;
  user_email: string;
  user_name: string;
};


// Razorpay checkout.js loader — idempotent, returns once script is ready.
function loadRazorpayCheckout(): Promise<boolean> {
  return new Promise((resolve) => {
    if (typeof window === "undefined") return resolve(false);
    if ((window as any).Razorpay) return resolve(true);
    const existing = document.getElementById("razorpay-checkout-js");
    if (existing) {
      existing.addEventListener("load",  () => resolve(true));
      existing.addEventListener("error", () => resolve(false));
      return;
    }
    const s = document.createElement("script");
    s.id = "razorpay-checkout-js";
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.async = true;
    s.onload  = () => resolve(true);
    s.onerror = () => resolve(false);
    document.head.appendChild(s);
  });
}


export function SubscriptionTierCard({
  currentTier: currentTierProp,
  onUpgradeStarted,
  highlightTier,
  hideTiers = [],
}: {
  currentTier?: Tier;
  /** Fires once the user has been handed off to Razorpay Checkout. */
  onUpgradeStarted?: (tier: Tier) => void;
  /** A tier to visually highlight (e.g. the one a 402 said is required). */
  highlightTier?: Tier;
  /** Tiers to omit entirely (e.g. inside an UpgradeModal hide FREE). */
  hideTiers?: Tier[];
}) {
  const user = getUser();
  const { data: cfg } = useSWR<RazorpayConfig>("/api/payments/razorpay/config", authedFetcher);
  const { data: sub } = useSWR<Subscription>(
    currentTierProp ? null : "/api/portal/me/subscription",
    authedFetcher
  );

  const currentTier: Tier = (currentTierProp || (sub?.tier as Tier) || "FREE");
  const [busy, setBusy]   = useState<Tier | null>(null);
  const [err, setErr]     = useState<string | null>(null);

  const startCheckout = useCallback(async (tier: Tier) => {
    setErr(null);
    setBusy(tier);
    try {
      // Step 1 — server-create a subscription (also handles "not configured" 503)
      const res = await authedFetch("/api/payments/razorpay/start-subscription", {
        method: "POST",
        body: JSON.stringify({ tier }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || data?.message || "Failed to start subscription");
      }
      const sub_resp = data as StartSubscriptionResponse;

      // Step 2 — load Razorpay Checkout.js (cached after first load)
      const ok = await loadRazorpayCheckout();
      if (!ok) {
        // Fallback: open Razorpay's hosted short_url so the user can still pay
        if (sub_resp.short_url) {
          window.open(sub_resp.short_url, "_blank", "noopener,noreferrer");
          onUpgradeStarted?.(tier);
          return;
        }
        throw new Error("Could not load Razorpay Checkout. Check your network.");
      }

      // Step 3 — open Razorpay Checkout bound to this subscription
      const rzp = new (window as any).Razorpay({
        key:             sub_resp.key_id,
        subscription_id: sub_resp.subscription_id,
        name:            "MarketLens",
        description:     `${tier} subscription — ₹${sub_resp.amount_inr}/month`,
        image:           "/favicon.ico",
        prefill: {
          email: sub_resp.user_email,
          name:  sub_resp.user_name,
        },
        notes: { tier, user_email: sub_resp.user_email },
        theme: { color: "#f59e0b" },   // accent-amber
        handler: function () {
          // Razorpay fired the webhook server-side — show a friendly message
          // and reload the profile so the new tier appears.
          window.location.reload();
        },
        modal: {
          ondismiss: () => { setBusy(null); },
        },
      });
      rzp.on("payment.failed", (resp: any) => {
        setErr(resp?.error?.description || "Payment failed. Please try again.");
        setBusy(null);
      });
      rzp.open();
      onUpgradeStarted?.(tier);
    } catch (e: any) {
      setErr(e.message || String(e));
      setBusy(null);
    }
  }, [onUpgradeStarted]);

  if (!user) return null;

  const visibleTiers = TIERS.filter((t) => !hideTiers.includes(t));

  return (
    <div className="space-y-3">
      {err && (
        <div className="bg-accent-red/10 border border-accent-red/40 rounded p-2.5 text-[11px] text-accent-red flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{err}</span>
        </div>
      )}

      {cfg && !cfg.configured && (
        <div className="bg-accent-amber/5 border border-accent-amber/30 rounded p-2.5 text-[11px] text-text-secondary">
          <strong className="text-accent-amber">Online payment not yet enabled.</strong>{" "}
          Contact admin (or your assigned account manager) to upgrade — they can set your tier manually.
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {visibleTiers.map((tier) => {
          const isCurrent    = tier === currentTier;
          const isHighlight  = tier === highlightTier;
          const isUpgrade    = TIER_RANK[tier] > TIER_RANK[currentTier];
          const isDowngrade  = TIER_RANK[tier] < TIER_RANK[currentTier];
          const price        = cfg?.plans?.[tier]?.price_inr ?? FALLBACK_PRICES[tier];

          return (
            <div key={tier}
                  className={clsx(
                    "rounded-lg border p-4 flex flex-col",
                    isHighlight && "border-accent-amber ring-2 ring-accent-amber/30",
                    !isHighlight && isCurrent && "border-accent-green/50 bg-accent-green/5",
                    !isHighlight && !isCurrent && "border-bg-line bg-bg-surface",
                  )}>
              <TierHeader tier={tier} isCurrent={isCurrent} />

              <div className="mt-3 mb-3">
                <div className="text-2xl font-bold text-text-primary tabular">
                  {price === 0 ? "Free" : <>₹{price.toLocaleString("en-IN")}</>}
                </div>
                {price > 0 && <div className="text-[10px] text-text-muted">per month · GST inclusive</div>}
                {price === 0 && <div className="text-[10px] text-text-muted">forever</div>}
              </div>

              <ul className="space-y-1.5 text-[11px] flex-1">
                {FEATURES_BY_TIER[tier].map((f) => (
                  <li key={f.label} className="flex items-start gap-1.5">
                    {f.ok
                      ? <CheckCircle2 className="w-3.5 h-3.5 text-accent-green shrink-0 mt-0.5" />
                      : <XCircle className="w-3.5 h-3.5 text-text-muted/40 shrink-0 mt-0.5" />}
                    <span className={f.ok ? "text-text-primary" : "text-text-muted line-through"}>
                      {f.label}
                    </span>
                  </li>
                ))}
              </ul>

              <div className="mt-4">
                {isCurrent ? (
                  <button disabled
                          className="w-full py-2 rounded text-[11px] font-bold uppercase tracking-wider bg-accent-green/10 text-accent-green border border-accent-green/30 cursor-default">
                    Current plan
                  </button>
                ) : isDowngrade ? (
                  <button disabled
                          className="w-full py-2 rounded text-[11px] font-semibold text-text-muted border border-bg-line cursor-not-allowed"
                          title="Already at higher tier">
                    Included
                  </button>
                ) : tier === "FREE" ? (
                  <button disabled
                          className="w-full py-2 rounded text-[11px] font-semibold text-text-muted border border-bg-line cursor-not-allowed">
                    Default
                  </button>
                ) : cfg?.configured ? (
                  <button onClick={() => startCheckout(tier)}
                          disabled={busy !== null}
                          className="w-full py-2 rounded text-[11px] font-bold uppercase tracking-wider bg-accent-amber text-white hover:opacity-90 disabled:opacity-50 flex items-center justify-center gap-1.5">
                    {busy === tier ? (
                      <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Opening…</>
                    ) : (
                      <>Upgrade to {tier}</>
                    )}
                  </button>
                ) : (
                  <button disabled className="w-full py-2 rounded text-[11px] font-semibold text-text-muted border border-bg-line cursor-not-allowed">Not available</button>
                )}
                {isUpgrade && cfg?.configured && busy !== tier && (
                  <p className="text-[9px] text-text-muted text-center mt-1.5">
                    Cancel anytime. Auto-renews monthly.
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Tier metadata — shown when /razorpay/config doesn't include a price yet
// (e.g. Razorpay disabled). Keep in sync with TIER_PRICING_INR on the backend.
// ---------------------------------------------------------------------------

const FALLBACK_PRICES: Record<Tier, number> = {
  FREE: 0, BASIC: 499, INTERMEDIATE: 1499, ADVANCED: 2999,
};

const FEATURES_BY_TIER: Record<Tier, { label: string; ok: boolean }[]> = {
  FREE: [
    { label: "5 picks/day",                  ok: true  },
    { label: "Swing horizon only",           ok: true  },
    { label: "15-min delayed signals",       ok: true  },
    { label: "F&O recommendations",          ok: false },
    { label: "Intraday signals",             ok: false },
    { label: "Telegram channel",             ok: false },
  ],
  BASIC: [
    { label: "20 picks/day",                 ok: true  },
    { label: "Swing horizon",                ok: true  },
    { label: "5-min delayed signals",        ok: true  },
    { label: "Equity Telegram channel",      ok: true  },
    { label: "F&O recommendations",          ok: false },
    { label: "Intraday signals",             ok: false },
  ],
  INTERMEDIATE: [
    { label: "50 picks/day",                 ok: true  },
    { label: "All horizons (intraday/swing)",ok: true  },
    { label: "Real-time signals",            ok: true  },
    { label: "F&O recommendations",          ok: true  },
    { label: "MCX commodities",              ok: true  },
    { label: "Live options strategy",        ok: true  },
  ],
  ADVANCED: [
    { label: "Unlimited picks",              ok: true  },
    { label: "All horizons",                 ok: true  },
    { label: "Real-time signals",            ok: true  },
    { label: "F&O + intraday options",       ok: true  },
    { label: "Priority Telegram channel",    ok: true  },
    { label: "Direct analyst access",        ok: true  },
  ],
};


function TierHeader({ tier, isCurrent }: { tier: Tier; isCurrent: boolean }) {
  const cfg = {
    FREE:         { icon: Star,     color: "text-text-secondary",   border: "border-text-muted/30" },
    BASIC:        { icon: Star,     color: "text-accent-blue",      border: "border-accent-blue/40" },
    INTERMEDIATE: { icon: Sparkles, color: "text-accent-violet",    border: "border-accent-violet/40" },
    ADVANCED:    { icon: Crown,    color: "text-accent-amber",     border: "border-accent-amber/40" },
  }[tier];
  const Icon = cfg.icon;
  return (
    <div className="flex items-center justify-between">
      <div className={clsx("inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", cfg.color, cfg.border)}>
        <Icon className="w-3 h-3" />
        {tier}
      </div>
      {isCurrent && (
        <span className="text-[9px] uppercase font-bold text-accent-green tracking-wider">
          Active
        </span>
      )}
    </div>
  );
}
