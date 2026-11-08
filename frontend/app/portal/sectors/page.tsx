"use client";

/**
 * Sectors page — sector-wise BUY/SELL breakdown for the current scan.
 *
 * Three sections:
 *   1. Heatmap strip — every sector colored by net sentiment
 *   2. Top bullish sectors (green cards with top BUY picks)
 *   3. Top bearish sectors (red cards with top SELL picks)
 *
 * Click any pick → drills into the symbol detail page.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { fmt } from "@/lib/format";
import {
  TrendingUp, TrendingDown, Minus, RefreshCw, Grid3x3, ArrowRight, Star,
} from "lucide-react";
import clsx from "clsx";


type Horizon = "INTRADAY" | "SWING" | "POSITIONAL";


export default function PortalSectorsPage() {
  const router = useRouter();
  const [horizon, setHorizon] = useState<Horizon>("SWING");
  const [minStars, setMinStars] = useState(3);

  const url = `/api/portal/sector-picks?horizon=${horizon}&min_stars=${minStars}`;
  const { data, error, isLoading, mutate } = useSWR<any>(url, fetcher,
    { refreshInterval: 300_000, revalidateOnFocus: false, shouldRetryOnError: false });

  // Paywall (FREE/BASIC can only see SWING)
  if (error instanceof ApiError && error.status === 402) {
    return (
      <div className="space-y-3">
        <PageHeader />
        <UpgradeRequired error={error} />
      </div>
    );
  }

  const sectors = (data?.sectors || []) as any[];
  const bullishSectors = sectors.filter((s) => s.bias === "BULLISH").slice(0, 5);
  const bearishSectors = sectors.filter((s) => s.bias === "BEARISH").slice(0, 5);

  return (
    <div className="space-y-3">
      <PageHeader />

      {/* Toolbar */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-3 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1">
          {(["INTRADAY", "SWING", "POSITIONAL"] as Horizon[]).map((h) => (
            <button key={h} onClick={() => setHorizon(h)}
              className={clsx("broker-chip", horizon === h && "active")}>
              {h}
            </button>
          ))}
        </div>
        <div className="w-px h-5 bg-bg-line mx-1" aria-hidden />
        <div className="flex items-center gap-1 text-[11px] text-text-muted">
          Min stars:
          {[2, 3, 4, 5].map((n) => (
            <button key={n} onClick={() => setMinStars(n)}
              className={clsx("broker-chip", minStars === n && "active")}>
              {n}★
            </button>
          ))}
        </div>
        <span className="ml-auto text-[10px] text-text-muted">
          {data?.total_sectors || 0} sectors · {data?.total_picks || 0} picks
        </span>
        <button onClick={() => mutate()} disabled={isLoading}
          className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
          <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {/* Loading + empty states */}
      {isLoading && sectors.length === 0 && (
        <div className="text-text-muted text-center py-10 text-sm">
          Loading sector breakdown…
        </div>
      )}
      {!isLoading && sectors.length === 0 && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <p className="text-text-muted text-sm">
            No picks found. Try lowering the Min stars filter.
          </p>
        </div>
      )}

      {/* ───── Heatmap strip ───── */}
      {sectors.length > 0 && (
        <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
          <div className="text-[10px] uppercase font-bold tracking-wider text-text-muted mb-2 flex items-center gap-1">
            <Grid3x3 className="w-3 h-3" /> Sector heatmap (net sentiment)
          </div>
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-1.5">
            {sectors.map((s) => (
              <SectorHeatTile key={s.sector} s={s} />
            ))}
          </div>
          <div className="flex items-center gap-4 mt-3 text-[10px] text-text-muted justify-center">
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-sm bg-accent-red/40 inline-block" /> Bearish
            </span>
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-sm bg-bg-base border border-bg-line inline-block" /> Mixed
            </span>
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-sm bg-accent-green/40 inline-block" /> Bullish
            </span>
          </div>
        </div>
      )}

      {/* ───── Bullish sectors ───── */}
      {bullishSectors.length > 0 && (
        <SectorList title="Top Bullish Sectors" sectors={bullishSectors} kind="bull" router={router} />
      )}

      {/* ───── Bearish sectors ───── */}
      {bearishSectors.length > 0 && (
        <SectorList title="Top Bearish Sectors" sectors={bearishSectors} kind="bear" router={router} />
      )}

      {/* Footer */}
      {data?.disclaimer && (
        <div className="text-[10px] text-text-muted text-center italic pt-2">
          {data.disclaimer}
        </div>
      )}
    </div>
  );
}


function PageHeader() {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
      <h1 className="text-base font-bold text-text-primary flex items-center gap-2">
        <Grid3x3 className="w-4 h-4 text-accent-amber" />
        Sector-wise Recommendations
      </h1>
      <p className="text-[11px] text-text-muted">
        BUY / SELL signals grouped by sector. Heatmap colours show where the
        most bullish vs bearish conviction sits right now.
      </p>
    </div>
  );
}


function SectorHeatTile({ s }: { s: any }) {
  // Color intensity based on net_sentiment magnitude
  const net = s.net_sentiment;
  let bg = "bg-bg-base border border-bg-line";
  let text = "text-text-secondary";
  if (net >= 3)       { bg = "bg-accent-green/40";  text = "text-accent-green"; }
  else if (net >= 2)  { bg = "bg-accent-green/25";  text = "text-accent-green"; }
  else if (net >= 1)  { bg = "bg-accent-green/15";  text = "text-text-primary"; }
  else if (net <= -3) { bg = "bg-accent-red/40";    text = "text-accent-red"; }
  else if (net <= -2) { bg = "bg-accent-red/25";    text = "text-accent-red"; }
  else if (net <= -1) { bg = "bg-accent-red/15";    text = "text-text-primary"; }

  return (
    <div className={clsx("rounded p-2 text-center", bg)}
         title={`${s.sector}: ${s.bullish_count}↑ ${s.bearish_count}↓`}>
      <div className={clsx("text-[10px] font-bold uppercase tracking-tight truncate", text)}>
        {s.sector}
      </div>
      <div className="text-[10px] tabular mt-0.5 text-text-secondary">
        {s.bullish_count}↑ {s.bearish_count}↓
      </div>
    </div>
  );
}


function SectorList({ title, sectors, kind, router }:
                     { title: string; sectors: any[]; kind: "bull" | "bear"; router: any }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg">
      <div className={clsx("flex items-center justify-between p-3 border-b border-bg-line",
        kind === "bull" ? "text-accent-green" : "text-accent-red")}>
        <h2 className="text-sm font-bold flex items-center gap-2">
          {kind === "bull" ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          {title}
        </h2>
        <span className="text-[10px] text-text-muted">{sectors.length} sectors</span>
      </div>
      <div className="divide-y divide-bg-line">
        {sectors.map((s) => {
          const pick = kind === "bull" ? s.top_buy : s.top_sell;
          return (
            <div key={s.sector}
                 className="p-3 hover:bg-bg-base/40 cursor-pointer flex items-center gap-3"
                 onClick={() => pick && router.push(`/portal/symbol/${pick.symbol}`)}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <div className="font-bold text-text-primary text-sm truncate">{s.sector}</div>
                  <span className={clsx("broker-pill", kind === "bull" ? "bull" : "bear")}>
                    {s.bullish_count}↑ {s.bearish_count}↓
                  </span>
                </div>
                <div className="text-[10px] text-text-muted">
                  Avg confidence {s.avg_confidence?.toFixed?.(0) || s.avg_confidence}%
                </div>
              </div>

              {pick && (
                <div className="text-right">
                  <div className="text-[11px] font-bold text-text-primary">{pick.symbol}</div>
                  <div className="flex items-center gap-1 justify-end mt-0.5">
                    {Array.from({ length: 5 }).map((_, i) => (
                      <Star key={i} className={clsx("w-2.5 h-2.5",
                        i < (pick.stars || 0) ? "fill-accent-amber text-accent-amber" : "text-text-muted/30")} />
                    ))}
                  </div>
                  {pick.entry && (
                    <div className="text-[10px] text-text-muted tabular">
                      ₹{fmt.inr(pick.entry)} · {Math.round(pick.confidence || 0)}%
                    </div>
                  )}
                </div>
              )}

              <ArrowRight className="w-4 h-4 text-text-muted" />
            </div>
          );
        })}
      </div>
    </div>
  );
}
