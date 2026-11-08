"use client";

import useSWR from "swr";
import { useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { authedFetcher, authedFetch } from "@/lib/auth";
import { fetcher } from "@/lib/api";
import {
  TrendingUp, Plus, X, ArrowRight, Activity, Sparkles, Moon,
} from "lucide-react";
import { SentimentGauge } from "@/components/SentimentGauge";
import { PickCardCompact } from "@/components/PickCard";
import { HoraDayTimeline } from "@/components/HoraDayTimeline";
import clsx from "clsx";


export default function PortalHomePage() {
  const router = useRouter();

  // Watchlist (per-user, persisted)
  const { data: wl, mutate: mutateWl } = useSWR<any>("/api/portal/me/watchlist", authedFetcher,
    { refreshInterval: 60_000 });

  // Today's top picks (simplified payload) — auth-gated, must use authedFetcher
  const { data: picks } = useSWR<any>("/api/portal/top-picks?horizon=SWING&min_stars=3&top_n=5",
    authedFetcher, { refreshInterval: 300_000 });

  // Market pulse (clean summary) — auth-gated, must use authedFetcher
  const { data: pulse } = useSWR<any>("/api/portal/market-pulse", authedFetcher,
    { refreshInterval: 60_000 });

  const [adding, setAdding] = useState(false);
  const [newSym, setNewSym] = useState("");

  async function addToWatchlist(e: React.FormEvent) {
    e.preventDefault();
    if (!newSym.trim()) return;
    await authedFetch("/api/portal/me/watchlist", {
      method: "POST",
      body: JSON.stringify({ symbol: newSym.trim().toUpperCase(), exchange: "NSE" }),
    });
    setNewSym("");
    mutateWl();
  }

  async function removeFromWatchlist(symbol: string) {
    await authedFetch(`/api/portal/me/watchlist/${symbol}`, { method: "DELETE" });
    mutateWl();
  }

  // Merge top_buy + top_sell into a single ranked list — power users scan by
  // conviction (stars × confidence), not by direction. Direction is on the card.
  const allPicks = useMemo(() => {
    const buy  = (picks?.top_buy  || []).map((p: any) => ({ ...p, direction: "BULLISH" }));
    const sell = (picks?.top_sell || []).map((p: any) => ({ ...p, direction: "BEARISH" }));
    return [...buy, ...sell].sort((a, b) => {
      const qa = (a.confidence || 0) * 0.7 + (a.stars || 0) * 6;
      const qb = (b.confidence || 0) * 0.7 + (b.stars || 0) * 6;
      return qb - qa;
    }).slice(0, 6);    // top 6 across both directions
  }, [picks]);

  const bullishCount = (picks?.top_buy?.length)  || 0;
  const bearishCount = (picks?.top_sell?.length) || 0;
  // Anything in the universe we scanned but didn't surface = "neutral" (rough proxy)
  const neutralCount = Math.max(0, (picks?.scanned_count || 0) - bullishCount - bearishCount);

  return (
    <div className="space-y-5">
      {/* Hero — cleaner, with bias chip + market context */}
      <div className="bg-gradient-to-r from-accent-amber/10 via-accent-amber/5 to-transparent border border-accent-amber/20 rounded-lg p-5">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-text-primary">Today's picks</h1>
            <p className="text-[13px] text-text-secondary mt-1 max-w-xl">
              {pulse?.headline || "Market analysis updating…"}
            </p>
          </div>
          {pulse && (
            <div className="flex items-center gap-3 text-[11px]">
              <ContextChip icon={Activity} label="Bias"
                value={pulse.market_bias || "—"}
                color={pulse.market_bias === "BULLISH" ? "text-accent-green"
                        : pulse.market_bias === "BEARISH" ? "text-accent-red"
                        : "text-text-secondary"} />
              <ContextChip icon={Sparkles} label={pulse.hora?.ruler || "Hora"}
                value={pulse.hora?.bias || "—"}
                color={pulse.hora?.bias === "bullish" ? "text-accent-green"
                        : pulse.hora?.bias === "bearish" ? "text-accent-red"
                        : "text-text-secondary"} />
              <ContextChip icon={Moon} label="Moon"
                value={pulse.moon?.phase || "—"}
                color="text-text-secondary" />
            </div>
          )}
        </div>
      </div>

      {/* Sentiment gauge — one glance to see if today's tape is bullish or bearish */}
      {(bullishCount + bearishCount + neutralCount) > 0 && (
        <SentimentGauge
          bullish={bullishCount}
          bearish={bearishCount}
          neutral={neutralCount}
          label="Today's pick distribution"
        />
      )}

      {/* Hora day timeline — every planetary window during the NSE session.
          Surfaces WHY the market behaves differently at different times of day,
          not just the "best" entry windows. Refreshes every 60s so the "current
          hora" marker moves through the bar as the session progresses. */}
      <HoraDayTimeline />

      {/* Top picks — unified grid, ranked by conviction */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-bold text-text-primary">Top picks right now</h2>
          <Link href="/portal/recommendations"
                className="text-[11px] text-accent-amber hover:text-accent-gold font-semibold flex items-center gap-1">
            See all <ArrowRight className="w-3 h-3" />
          </Link>
        </div>
        {allPicks.length === 0 ? (
          <div className="py-8 text-center text-text-muted text-sm">
            No qualifying picks right now. The scanner refreshes every 5 minutes.
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {allPicks.map((p: any) => (
              <PickCardCompact key={`${p.symbol}-${p.direction}`} pick={p} />
            ))}
          </div>
        )}
      </div>

      {/* Watchlist */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-text-primary">My Watchlist</h2>
          <span className="text-[11px] text-text-muted">{wl?.count || 0} symbols</span>
        </div>

        {/* Add form */}
        <form onSubmit={addToWatchlist} className="flex gap-2 mb-4">
          <input value={newSym} onChange={(e) => setNewSym(e.target.value)}
            placeholder="Add symbol e.g. RELIANCE, TCS"
            className="flex-1 px-3 py-2 text-sm rounded border border-bg-line bg-bg-base focus:border-accent-amber" />
          <button type="submit"
            className="bg-accent-amber text-white font-bold px-4 py-2 rounded text-sm hover:bg-accent-gold flex items-center gap-1">
            <Plus className="w-4 h-4" /> Add
          </button>
        </form>

        {/* List */}
        {wl?.items?.length === 0 && (
          <p className="text-text-muted text-sm text-center py-6">
            Your watchlist is empty. Add a few symbols above to track.
          </p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {wl?.items?.map((item: any) => (
            <WatchlistTile key={item.id} symbol={item.symbol}
              onOpen={() => router.push(`/portal/symbol/${item.symbol}`)}
              onRemove={() => removeFromWatchlist(item.symbol)} />
          ))}
        </div>
      </div>

      {/* Quick links */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <QuickLinkCard href="/portal/recommendations" icon={TrendingUp} label="Recommendations"
          desc="Ranked F&O picks for today" />
        <QuickLinkCard href="/portal/options" icon={Star} label="F&O Strategy"
          desc="Best option strikes" />
        <QuickLinkCard href="/portal/commodities" icon={Activity} label="Commodities"
          desc="Gold, Silver, Crude" />
        <QuickLinkCard href="/portal/profile" icon={Sparkles} label="My Plan"
          desc="Subscription & settings" />
      </div>
    </div>
  );
}


// ─── Sub-components ──────────────────────────────────────────────────────

function ContextChip({ icon: Icon, label, value, color }:
                      { icon: any; label: string; value: string; color: string }) {
  return (
    <div className="flex items-center gap-1.5 bg-bg-surface/60 border border-bg-line rounded px-2 py-1">
      <Icon className="w-3 h-3 text-accent-amber" />
      <span className="text-text-muted">{label}</span>
      <span className={clsx("font-bold uppercase tracking-tight", color)}>{value}</span>
    </div>
  );
}


function WatchlistTile({ symbol, onOpen, onRemove }:
                        { symbol: string; onOpen: () => void; onRemove: () => void }) {
  const { data } = useSWR<any>(`/api/market/quote/${symbol}?exchange=NSE`, fetcher,
    { refreshInterval: 15_000 });
  const ltp = data?.data?.ltp || data?.ltp;
  const change = data?.data?.netChange || 0;
  const changePct = data?.data?.percentChange || 0;
  const up = change >= 0;

  return (
    <div className="bg-bg-base border border-bg-line rounded p-3 flex items-center justify-between hover:border-accent-amber group">
      <button onClick={onOpen} className="flex-1 min-w-0 text-left">
        <div className="font-bold text-text-primary text-sm truncate">{symbol}</div>
        {ltp ? (
          <>
            <div className="text-base tabular text-text-primary">₹{Number(ltp).toFixed(2)}</div>
            <div className={clsx("text-[10px] font-semibold tabular",
              up ? "text-accent-green" : "text-accent-red")}>
              {up ? "+" : ""}{Number(change).toFixed(2)} ({Number(changePct).toFixed(2)}%)
            </div>
          </>
        ) : (
          <div className="text-[10px] text-text-muted">Loading…</div>
        )}
      </button>
      <button onClick={onRemove}
        className="text-text-muted hover:text-accent-red opacity-0 group-hover:opacity-100 p-1"
        title="Remove from watchlist">
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}


function QuickLinkCard({ href, icon: Icon, label, desc }:
                        { href: string; icon: any; label: string; desc: string }) {
  return (
    <Link href={href}
      className="bg-bg-surface border border-bg-line rounded-lg p-3 hover:border-accent-amber group transition-colors">
      <Icon className="w-5 h-5 text-accent-amber mb-2" />
      <div className="font-bold text-sm text-text-primary group-hover:text-accent-amber">{label}</div>
      <div className="text-[10px] text-text-muted mt-0.5">{desc}</div>
    </Link>
  );
}
