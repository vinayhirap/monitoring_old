"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { ErrorState, LoadingSkeleton, InfoBanner } from "@/components/States";
import {
  Calendar, TrendingUp, TrendingDown, Minus, ChevronLeft, Search,
  Clock, AlertTriangle, CheckCircle2,
} from "lucide-react";
import clsx from "clsx";


/**
 * 14-day pure-astrology forecast view.
 *
 * Renders the per-day grid: date, bias (BULLISH/BEARISH/NEUTRAL), expected
 * intraday range, best entry/exit windows. No engine internals, no nakshatra
 * names visible unless the user opens the "Why" expander.
 */
export default function PortalForecastPage({ params }: { params: { ticker: string } }) {
  const router = useRouter();
  const sym = params.ticker.toUpperCase();
  const [sym2, setSym2] = useState(sym);
  const { data, error, isLoading, mutate } = useSWR<any>(
    `/api/portal/daily-forecast/${sym}?days=14`,
    fetcher, { refreshInterval: 600_000, shouldRetryOnError: false }
  );

  const isPaywall = error instanceof ApiError && error.status === 402;

  function jumpTo() {
    if (sym2 && sym2.toUpperCase() !== sym) {
      router.push(`/portal/forecast/${sym2.toUpperCase()}`);
    }
  }

  return (
    <div className="space-y-4">
      <Link href="/portal" className="inline-flex items-center text-[12px] text-text-muted hover:text-accent-amber gap-1">
        <ChevronLeft className="w-3.5 h-3.5" /> Back to dashboard
      </Link>

      <div className="bg-gradient-to-r from-accent-amber/10 to-accent-violet/5 border border-accent-amber/30 rounded-lg p-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
              <Calendar className="w-5 h-5 text-accent-amber" />
              14-Day Forecast — {sym}
            </h1>
            <p className="text-[11px] text-text-muted mt-1">
              Per-day bias, expected range, and best entry/exit windows for the next 14 calendar days.
            </p>
          </div>
          <div className="flex gap-2 items-center">
            <Search className="w-4 h-4 text-text-muted" />
            <input value={sym2} onChange={(e) => setSym2(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && jumpTo()}
              placeholder="Symbol e.g. NIFTY"
              className="px-3 py-1.5 text-sm rounded border border-bg-line bg-bg-base focus:border-accent-amber w-40" />
            <button onClick={jumpTo}
              className="bg-accent-amber text-white font-bold px-3 py-1.5 text-sm rounded hover:bg-accent-gold">
              Load
            </button>
          </div>
        </div>
      </div>

      {isPaywall && <UpgradeRequired error={error} />}
      {error && !isPaywall && <ErrorState message={String(error.message)} onRetry={() => mutate()} />}
      {isLoading && !data && <LoadingSkeleton lines={8} />}

      {data && (
        <>
          {/* Summary KPIs */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <KPICard label="Trading days"
              value={data.trading_days} color="text-text-primary" />
            <KPICard label="Bullish days"
              value={data.summary?.bullish_days || 0}
              color="text-accent-green" />
            <KPICard label="Bearish days"
              value={data.summary?.bearish_days || 0}
              color="text-accent-red" />
            <KPICard label="Best BUY day"
              value={data.summary?.best_buy_day || "—"}
              sub={data.summary?.best_buy_score != null ? `score ${data.summary.best_buy_score}` : undefined}
              color="text-accent-green" />
            <KPICard label="Best SELL day"
              value={data.summary?.best_sell_day || "—"}
              sub={data.summary?.best_sell_score != null ? `score ${data.summary.best_sell_score}` : undefined}
              color="text-accent-red" />
          </div>

          {/* Per-day grid — like the screenshot you shared */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-7 gap-2">
            {data.days?.slice(0, 7).map((d: any) => (
              <DayCard key={d.date} day={d} />
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-7 gap-2">
            {data.days?.slice(7, 14).map((d: any) => (
              <DayCard key={d.date} day={d} />
            ))}
          </div>

          {data.disclaimer && (
            <InfoBanner type="warning">
              {data.disclaimer}
            </InfoBanner>
          )}
        </>
      )}
    </div>
  );
}


function KPICard({ label, value, sub, color }:
                  { label: string; value: any; sub?: string; color?: string }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
      <div className="text-[9px] uppercase text-text-muted tracking-wider font-semibold">{label}</div>
      <div className={clsx("text-base font-bold tabular mt-1 truncate", color || "text-text-primary")}>
        {value}
      </div>
      {sub && <div className="text-[9px] text-text-muted truncate">{sub}</div>}
    </div>
  );
}


function DayCard({ day }: { day: any }) {
  if (!day.is_market_open) {
    return (
      <div className="bg-bg-base/40 border border-bg-line rounded p-3 text-center">
        <div className="text-[10px] uppercase font-bold text-text-muted">
          {day.weekday.slice(0, 3)}
        </div>
        <div className="text-[11px] tabular">{day.date.slice(5)}</div>
        <div className="text-[10px] text-text-muted mt-1">Market closed</div>
      </div>
    );
  }

  const biasColor = day.bias === "BULLISH" ? "border-accent-green/40 bg-accent-green/5 text-accent-green"
                    : day.bias === "BEARISH" ? "border-accent-red/40 bg-accent-red/5 text-accent-red"
                    : "border-bg-line bg-bg-base/40 text-text-secondary";
  const Icon = day.bias === "BULLISH" ? TrendingUp :
                day.bias === "BEARISH" ? TrendingDown : Minus;

  return (
    <div className={clsx("border rounded-lg p-3 transition-colors hover:shadow-card", biasColor)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-[10px] uppercase font-bold tracking-wider">{day.weekday.slice(0, 3)}</div>
          <div className="text-[11px] tabular text-text-primary">{day.date.slice(5)}</div>
        </div>
        <div className={clsx("p-1 rounded border", biasColor)}>
          <Icon className="w-3.5 h-3.5" />
        </div>
      </div>

      {/* Bias + score — handles both views:
            USER role → `confidence`, ADMIN role → `astro_score` */}
      <div className="text-center my-2">
        <div className={clsx("text-base font-bold uppercase", biasColor.split(" ")[2])}>
          {day.bias}
        </div>
        <div className="text-[10px] text-text-muted">
          Strength {day.confidence ?? day.astro_score}/100
        </div>
      </div>

      {/* Range */}
      <div className="text-[10px] text-text-muted text-center mb-2">
        Expected range: <strong className="text-text-primary">±{day.expected_range_pct}%</strong>
      </div>

      {/* Best entry windows */}
      {day.best_entry_windows?.length > 0 && (
        <div className="border-t border-bg-line pt-2 mt-2">
          <div className="text-[9px] uppercase text-text-muted font-bold mb-1 flex items-center gap-1">
            <Clock className="w-2.5 h-2.5" /> Best entry
          </div>
          {day.best_entry_windows.map((w: any, i: number) => (
            <div key={i} className="text-[10px] tabular text-accent-green">
              {w.from} – {w.to}
            </div>
          ))}
        </div>
      )}

      {/* Events */}
      {day.events?.length > 0 && (
        <div className="border-t border-bg-line pt-2 mt-2">
          {day.events.slice(0, 2).map((e: string, i: number) => (
            <div key={i} className="text-[9px] text-accent-amber flex items-start gap-1 mb-0.5">
              <AlertTriangle className="w-2 h-2 shrink-0 mt-0.5" />
              <span className="truncate" title={e}>{e}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
