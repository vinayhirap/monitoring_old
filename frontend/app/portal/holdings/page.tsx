"use client";

/**
 * Holdings page — long-term portfolio (delivery / CNC) pulled directly
 * from the broker via /api/broker/holdings.
 *
 * Distinct from /portal/positions which shows intraday-and-open positions.
 * Holdings are settled DEMAT shares held overnight. P&L here is computed
 * vs the user's actual buy-average (broker-reported), not the platform's
 * suggested entry.
 *
 * Read-only — to exit a holding, place a SELL order via the broker's
 * Holdings → Sell flow (we don't wrap that yet to avoid edge cases like
 * SLB and pledged shares).
 */

import useSWR, { mutate } from "swr";
import Link from "next/link";
import { authedFetcher as fetcher } from "@/lib/auth";
import { fmt } from "@/lib/format";
import {
  Briefcase, RefreshCw, TrendingUp, TrendingDown, ArrowRight,
} from "lucide-react";
import clsx from "clsx";


export default function PortalHoldingsPage() {
  const url = "/api/broker/holdings";
  const { data, isLoading } = useSWR<any>(url, fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false });

  const holdings = (data?.holdings || data?.data || []) as any[];

  // Aggregate stats
  const totalInvested  = holdings.reduce((s, h) => s + (h.avgprice ?? h.avg_price ?? 0) * (h.quantity ?? 0), 0);
  const totalCurrent   = holdings.reduce((s, h) => s + (h.ltp ?? h.last_price ?? 0) * (h.quantity ?? 0), 0);
  const totalPnl       = totalCurrent - totalInvested;
  const totalPnlPct    = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  return (
    <div className="space-y-3">
      <div className="bg-bg-surface border border-bg-line rounded-lg">
        <div className="flex items-center justify-between p-3 border-b border-bg-line">
          <div>
            <h1 className="text-base font-bold text-text-primary flex items-center gap-2">
              <Briefcase className="w-4 h-4 text-accent-amber" />
              Holdings
            </h1>
            <p className="text-[11px] text-text-muted">
              Long-term DEMAT positions held overnight. Pulled from your broker — not editable here.
            </p>
          </div>
          <button onClick={() => mutate(url)} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary */}
      {holdings.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="Invested" value={`₹${fmt.inr(totalInvested)}`} />
          <Stat label="Current value" value={`₹${fmt.inr(totalCurrent)}`} />
          <Stat label="Overall P&L"
                value={`${totalPnl >= 0 ? "+" : ""}₹${fmt.inr(Math.abs(totalPnl))}`}
                color={totalPnl >= 0 ? "text-accent-green" : "text-accent-red"} />
          <Stat label="P&L %"
                value={`${totalPnlPct >= 0 ? "+" : ""}${totalPnlPct.toFixed(2)}%`}
                color={totalPnlPct >= 0 ? "text-accent-green" : "text-accent-red"} />
        </div>
      )}

      {/* Empty / loading */}
      {isLoading && !data && (
        <div className="text-text-muted text-center py-10 text-sm">Loading holdings…</div>
      )}
      {!isLoading && holdings.length === 0 && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <Briefcase className="w-10 h-10 text-text-muted mx-auto mb-2" />
          <p className="text-text-muted text-sm">
            No holdings found. Either you have no overnight positions, or your
            broker connection is down.
            <Link href="/portal/recommendations" className="text-accent-amber hover:underline ml-1">
              Browse recommendations →
            </Link>
          </p>
        </div>
      )}

      {/* Table */}
      {holdings.length > 0 && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="num">Qty</th>
                <th className="num">Avg cost</th>
                <th className="num">LTP</th>
                <th className="num">Invested</th>
                <th className="num">Current</th>
                <th className="num">P&L (₹)</th>
                <th className="num">P&L %</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h: any, i: number) => {
                const qty       = Number(h.quantity || 0);
                const avg       = Number(h.avgprice ?? h.avg_price ?? 0);
                const ltp       = Number(h.ltp ?? h.last_price ?? 0);
                const invested  = avg * qty;
                const current   = ltp * qty;
                const pnl       = current - invested;
                const pnlPct    = invested > 0 ? (pnl / invested) * 100 : 0;
                const symbol    = h.symbol || h.tradingsymbol || h.tradingSymbol || "—";
                return (
                  <tr key={`${symbol}-${i}`}>
                    <td>
                      <Link href={`/portal/symbol/${symbol}`}
                            className="font-bold text-text-primary hover:text-accent-amber">
                        {symbol}
                      </Link>
                      {h.isin && (
                        <div className="text-[9px] text-text-muted">{h.isin}</div>
                      )}
                    </td>
                    <td className="num">{qty}</td>
                    <td className="num">₹{fmt.inr(avg)}</td>
                    <td className="num">₹{fmt.inr(ltp)}</td>
                    <td className="num">₹{fmt.inr(invested)}</td>
                    <td className="num">₹{fmt.inr(current)}</td>
                    <td className={clsx("num font-bold",
                      pnl >= 0 ? "text-accent-green" : "text-accent-red")}>
                      {pnl >= 0 ? "+" : ""}₹{fmt.inr(Math.abs(pnl))}
                    </td>
                    <td className={clsx("num",
                      pnlPct >= 0 ? "text-accent-green" : "text-accent-red")}>
                      {pnlPct >= 0 ? <TrendingUp className="w-3 h-3 inline" />
                                    : <TrendingDown className="w-3 h-3 inline" />}
                      {" "}{pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%
                    </td>
                    <td>
                      <ArrowRight className="w-3.5 h-3.5 text-text-muted" />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-[10px] text-text-muted text-center italic pt-2">
        To sell a holding, use your broker's Holdings → Sell flow.
        Order placement via this platform is for fresh entries only.
      </div>
    </div>
  );
}


function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
      <div className="text-[9px] uppercase text-text-muted tracking-wider font-semibold">{label}</div>
      <div className={clsx("text-xl font-bold tabular mt-1", color || "text-text-primary")}>{value}</div>
    </div>
  );
}
