"use client";

/**
 * Intraday F&O setups page — today's bias-aligned picks with the specific
 * option strike + futures level for each.
 *
 * Top strip shows the day's overall bias (BULLISH/BEARISH/NEUTRAL) +
 * confidence + best entry windows. Picks below it are filtered to align
 * with that direction.
 *
 * Each row shows BOTH the stock setup (entry/SL/T1) AND the F&O suggestion
 * (CE/PE strike, premium, SL/T1 in premium terms, notional, lot size).
 *
 * Tier-gated to INTERMEDIATE+ (intraday + F&O are tier features).
 */

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { HoraDayTimeline } from "@/components/HoraDayTimeline";
import { fmt } from "@/lib/format";
import {
  TrendingUp, TrendingDown, Minus, RefreshCw, Clock, Target,
  Zap, Star, ArrowRight, Activity,
} from "lucide-react";
import clsx from "clsx";


export default function AstroFnoPage() {
  const router = useRouter();
  const url = "/api/portal/astro-intraday-fno?min_stars=3&top_n=10";
  const { data, error, isLoading, mutate } = useSWR<any>(url, fetcher,
    { refreshInterval: 300_000, shouldRetryOnError: false });

  // Paywall (FREE/BASIC can't access intraday + F&O)
  if (error instanceof ApiError && error.status === 402) {
    return (
      <div className="space-y-3">
        <PageHeader />
        <UpgradeRequired error={error} />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <PageHeader />

      {/* Today's bias strip */}
      {data && data.day_bias && (
        <DayBiasStrip data={data} isLoading={isLoading} onRefresh={() => mutate()} />
      )}

      {/* Full intraday hora timeline — shows every planetary window with bias.
          On the F&O page this is load-bearing: a CE BUY entered during Mercury
          (bullish) but held through Saturn (bearish) is a different trade than
          one entered in Jupiter (most-bullish) and exited before Mars. */}
      <HoraDayTimeline />

      {/* Loading state */}
      {isLoading && !data && (
        <div className="text-text-muted text-center py-10 text-sm">
          Loading intraday setups…
        </div>
      )}

      {/* Closed market */}
      {data?.day_bias === "MARKET_CLOSED" && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <p className="text-text-secondary text-sm">{data.message}</p>
        </div>
      )}

      {/* Empty results */}
      {data && data.intraday_picks?.length === 0 && data.day_bias !== "MARKET_CLOSED" && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <p className="text-text-muted text-sm">
            No high-conviction intraday setups aligned with today's bias right now.
            Check back during market hours.
          </p>
        </div>
      )}

      {/* Picks table */}
      {data?.intraday_picks?.length > 0 && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Signal</th>
                <th className="num">★</th>
                <th className="num">Conf%</th>
                <th className="num">Entry</th>
                <th className="num">SL</th>
                <th className="num">T1</th>
                <th>Option</th>
                <th className="num">Strike</th>
                <th className="num">Premium</th>
                <th className="num">Lot</th>
                <th className="num">Notional</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.intraday_picks.map((p: any) => (
                <tr key={p.symbol} className="cursor-pointer"
                     onClick={() => router.push(`/portal/symbol/${p.symbol}`)}>
                  <td>
                    <div className="font-bold text-text-primary">{p.symbol}</div>
                    {p.sector && (
                      <div className="text-[9px] text-text-muted uppercase tracking-tight">
                        {p.sector}
                      </div>
                    )}
                  </td>
                  <td>
                    <span className={clsx("broker-pill",
                      p.direction === "BULLISH" ? "bull" : "bear")}>
                      {p.direction === "BULLISH"
                        ? <TrendingUp className="w-3 h-3" />
                        : <TrendingDown className="w-3 h-3" />}
                      {p.direction === "BULLISH" ? "BUY" : "SELL"}
                    </span>
                  </td>
                  <td className="num">
                    <div className="inline-flex">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Star key={i} className={clsx("w-3 h-3",
                          i < (p.stars || 0) ? "fill-accent-amber text-accent-amber" : "text-text-muted/30")} />
                      ))}
                    </div>
                  </td>
                  <td className={clsx("num font-bold",
                    (p.confidence || 0) >= 70 ? "text-accent-green" :
                    (p.confidence || 0) >= 55 ? "text-accent-amber" : "text-text-muted")}>
                    {Math.round(p.confidence || 0)}
                  </td>
                  <td className="num">{p.entry ? `₹${fmt.inr(p.entry)}` : "—"}</td>
                  <td className="num text-accent-red">{p.stoploss ? `₹${fmt.inr(p.stoploss)}` : "—"}</td>
                  <td className="num text-accent-green">
                    {p.targets?.[0] ? `₹${fmt.inr(p.targets[0])}` : "—"}
                  </td>
                  {/* F&O columns — degrade gracefully if fno is null */}
                  {p.fno ? (
                    <>
                      <td>
                        <span className={clsx("broker-pill",
                          p.fno.leg === "CE" ? "bull" : "bear")}>
                          {p.fno.leg}
                        </span>
                      </td>
                      <td className="num font-bold">{p.fno.strike}</td>
                      <td className="num">₹{p.fno.premium}</td>
                      <td className="num">{p.fno.lot_size}</td>
                      <td className="num text-accent-amber">
                        {p.fno.notional ? `₹${fmt.inr(p.fno.notional)}` : "—"}
                      </td>
                    </>
                  ) : (
                    <>
                      <td colSpan={5} className="text-[10px] text-text-muted italic">
                        F&O chain unavailable
                      </td>
                    </>
                  )}
                  <td>
                    <ArrowRight className="w-3.5 h-3.5 text-text-muted" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Premium SL/T legend */}
      {data?.intraday_picks?.length > 0 && (
        <div className="bg-bg-surface/60 border border-bg-line rounded p-3 text-[10px] text-text-secondary">
          <div className="font-bold text-accent-amber uppercase mb-1.5">How to read the F&O suggestion</div>
          <ul className="space-y-0.5">
            <li>• <span className="font-semibold text-accent-green">CE</span> = Call option (used for BUY/BULLISH plays). <span className="font-semibold text-accent-red">PE</span> = Put option (for SELL/BEARISH).</li>
            <li>• <strong>Strike</strong> is the nearest at-the-money price level. <strong>Premium</strong> is the current option cost per share.</li>
            <li>• <strong>Notional</strong> = premium × lot size. That's the cash you'd actually pay to buy 1 lot.</li>
            <li>• Recommended exits (set in your broker as fixed orders): SL at 50% of premium loss, Target at +50% / +100% premium gain.</li>
            <li>• Click any row for the full per-symbol analysis (options chain, greeks, max pain, etc).</li>
          </ul>
        </div>
      )}

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
        <Zap className="w-4 h-4 text-accent-amber" />
        Intraday F&O Setups
      </h1>
      <p className="text-[11px] text-text-muted">
        Today's intraday picks aligned with the daily market bias, each with the
        specific option strike and lot-level notional. Stock + option in one view.
      </p>
    </div>
  );
}


function DayBiasStrip({ data, isLoading, onRefresh }:
                       { data: any; isLoading: boolean; onRefresh: () => void }) {
  const isBull = data.day_bias === "BULLISH";
  const isBear = data.day_bias === "BEARISH";
  const Icon = isBull ? TrendingUp : isBear ? TrendingDown : Minus;
  const colorClass = isBull ? "text-accent-green border-accent-green/40 bg-accent-green/5"
                    : isBear ? "text-accent-red border-accent-red/40 bg-accent-red/5"
                    : "text-text-secondary border-bg-line bg-bg-base/40";

  return (
    <div className={clsx("border rounded-lg p-3", colorClass)}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <Icon className="w-8 h-8" />
          <div>
            <div className="text-[10px] uppercase font-bold tracking-wider opacity-80">
              Today's market bias
            </div>
            <div className="text-2xl font-black uppercase tracking-tight">
              {data.day_bias}
            </div>
            <div className="text-[11px] opacity-80">
              Strength {data.day_strength}/100
              {data.expected_range_pct && (
                <span> · Expected range ±{data.expected_range_pct}%</span>
              )}
            </div>
          </div>
        </div>

        {/* Best entry windows */}
        {data.best_entry_windows?.length > 0 && (
          <div className="bg-bg-surface/70 border border-bg-line rounded p-2 text-[11px]">
            <div className="flex items-center gap-1 text-[10px] uppercase font-bold text-text-muted tracking-wider mb-1">
              <Clock className="w-3 h-3" /> Best entry windows
            </div>
            {data.best_entry_windows.map((w: any, i: number) => (
              <div key={i} className="font-bold tabular text-text-primary">
                {w.from} – {w.to}
              </div>
            ))}
          </div>
        )}

        <button onClick={onRefresh} disabled={isLoading}
          className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50 self-start">
          <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {data.contrarian_count > 0 && (
        <div className="mt-2 pt-2 border-t border-current/20 text-[10px] opacity-80">
          {data.contrarian_count} contrarian setups (against today's bias) hidden from this view.
          Use the main Recommendations page to see those.
        </div>
      )}
    </div>
  );
}
