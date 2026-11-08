"use client";

/**
 * Recommendation history — broker-grade outcome table.
 *
 * Shows journaled signals + their realized outcomes. Each row is a past
 * recommendation; the rightmost columns show what actually happened
 * (target hit, SL hit, 5d P&L).
 *
 * Filters: lookback (1/3/7/14d), direction (BUY/SELL), outcome (WIN/LOSS/PENDING),
 * symbol search.
 */

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { fmt } from "@/lib/format";
import {
  History, RefreshCw, Search, ChevronDown, ChevronUp,
  TrendingUp, TrendingDown, CheckCircle2, XCircle, Clock,
} from "lucide-react";
import clsx from "clsx";


type DirFilter = "ALL" | "BULLISH" | "BEARISH";
type OutcomeFilter = "ALL" | "WIN" | "LOSS" | "PENDING";
type SortKey = "emitted_at" | "confidence" | "pnl";


export default function PortalHistoryPage() {
  const router = useRouter();

  const [days, setDays] = useState(14);
  const [dirFilter, setDirFilter] = useState<DirFilter>("ALL");
  const [outcomeFilter, setOutcomeFilter] = useState<OutcomeFilter>("ALL");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("emitted_at");
  const [sortDesc, setSortDesc] = useState(true);

  const url = `/api/portal/history?days=${days}` +
    (search.trim() ? `&symbol=${encodeURIComponent(search.toUpperCase())}` : "");
  const { data, error, isLoading, mutate } = useSWR<any>(url, fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false });

  // Paywall (FREE doesn't have History access)
  if (error instanceof ApiError && error.status === 402) {
    return (
      <div className="space-y-3">
        <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
          <h1 className="text-base font-bold text-text-primary flex items-center gap-2">
            <History className="w-4 h-4 text-accent-amber" /> Recommendation History
          </h1>
        </div>
        <UpgradeRequired error={error} />
      </div>
    );
  }

  // Derive the outcome label from raw row
  function outcomeLabel(r: any): "WIN" | "LOSS" | "PENDING" {
    if (r.outcome_target_hit && r.outcome_target_hit > 0) return "WIN";
    if (r.outcome_stoploss_hit) return "LOSS";
    if (r.outcome_5d_pnl_pct == null) return "PENDING";
    if (r.direction === "BULLISH" && r.outcome_5d_pnl_pct > 1.0) return "WIN";
    if (r.direction === "BEARISH" && r.outcome_5d_pnl_pct < -1.0) return "WIN";
    if (r.outcome_5d_pnl_pct < -1.0 && r.direction === "BULLISH") return "LOSS";
    if (r.outcome_5d_pnl_pct >  1.0 && r.direction === "BEARISH") return "LOSS";
    return "PENDING";
  }

  // Filter + sort
  const rows = useMemo(() => {
    let r = (data?.rows || []) as any[];
    if (dirFilter !== "ALL") r = r.filter((x) => x.direction === dirFilter);
    if (outcomeFilter !== "ALL") r = r.filter((x) => outcomeLabel(x) === outcomeFilter);
    r = [...r].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "emitted_at": {
          const ta = new Date(a.emitted_at || 0).getTime();
          const tb = new Date(b.emitted_at || 0).getTime();
          cmp = ta - tb;
          break;
        }
        case "confidence": cmp = (a.confidence || 0) - (b.confidence || 0); break;
        case "pnl":        cmp = (a.outcome_5d_pnl_pct || 0) - (b.outcome_5d_pnl_pct || 0); break;
      }
      return sortDesc ? -cmp : cmp;
    });
    return r;
  }, [data, dirFilter, outcomeFilter, sortKey, sortDesc]);

  // KPIs
  const stats = useMemo(() => {
    const evaluated = rows.filter((r) => outcomeLabel(r) !== "PENDING");
    const wins = evaluated.filter((r) => outcomeLabel(r) === "WIN").length;
    const total = evaluated.length;
    return {
      total: rows.length,
      evaluated: total,
      wins,
      win_rate: total > 0 ? wins / total : 0,
    };
  }, [rows]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDesc(!sortDesc);
    else { setSortKey(k); setSortDesc(true); }
  };

  return (
    <div className="space-y-3">
      {/* ───── Header + toolbar ───── */}
      <div className="bg-bg-surface border border-bg-line rounded-lg">
        <div className="flex items-center justify-between p-3 border-b border-bg-line">
          <div>
            <h1 className="text-base font-bold text-text-primary flex items-center gap-2">
              <History className="w-4 h-4 text-accent-amber" /> Recommendation History
            </h1>
            <p className="text-[11px] text-text-muted">
              {stats.total} signals · {stats.evaluated} evaluated
              {stats.evaluated > 0 && (
                <span> · win rate <span className={clsx("font-bold",
                  stats.win_rate >= 0.54 ? "text-accent-green" :
                  stats.win_rate >= 0.50 ? "text-accent-amber" : "text-accent-red")}>
                  {(stats.win_rate * 100).toFixed(0)}%
                </span></span>
              )}
            </p>
          </div>
          <button onClick={() => mutate()} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>

        <div className="flex items-center gap-3 p-3 flex-wrap">
          {/* Days */}
          <div className="flex items-center gap-1">
            {[1, 3, 7, 14].map((d) => (
              <button key={d} onClick={() => setDays(d)}
                className={clsx("broker-chip", days === d && "active")}>
                {d}d
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-bg-line mx-1" aria-hidden />

          {/* Direction */}
          <div className="flex items-center gap-1">
            {(["ALL", "BULLISH", "BEARISH"] as DirFilter[]).map((d) => (
              <button key={d} onClick={() => setDirFilter(d)}
                className={clsx("broker-chip", dirFilter === d && "active")}>
                {d === "ALL" ? "ALL" : d === "BULLISH" ? "BUY" : "SELL"}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-bg-line mx-1" aria-hidden />

          {/* Outcome */}
          <div className="flex items-center gap-1">
            {(["ALL", "WIN", "LOSS", "PENDING"] as OutcomeFilter[]).map((o) => (
              <button key={o} onClick={() => setOutcomeFilter(o)}
                className={clsx("broker-chip", outcomeFilter === o && "active")}>
                {o}
              </button>
            ))}
          </div>

          {/* Search */}
          <div className="ml-auto flex items-center gap-1.5 bg-bg-base border border-bg-line rounded px-2 py-1 text-[11px] min-w-[160px]">
            <Search className="w-3 h-3 text-text-muted" />
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search symbol…"
              className="bg-transparent outline-none flex-1 text-text-primary placeholder:text-text-muted/60" />
          </div>
        </div>
      </div>

      {/* ───── Empty / loading ───── */}
      {isLoading && rows.length === 0 && (
        <div className="text-text-muted text-center py-10 text-sm">Loading history…</div>
      )}
      {!isLoading && rows.length === 0 && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <p className="text-text-muted text-sm">No signals in this window. Try widening the date range.</p>
        </div>
      )}

      {/* ───── Table ───── */}
      {rows.length > 0 && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <SortableTH label="When" k="emitted_at" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} />
                <th>Symbol</th>
                <th>Signal</th>
                <SortableTH label="Conf%" k="confidence" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <th className="num">Entry</th>
                <th className="num">SL</th>
                <th className="num">T1</th>
                <th>Outcome</th>
                <SortableTH label="5d P&L%" k="pnl" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const out = outcomeLabel(r);
                const t1 = r.target_1 ?? r.targets?.[0];
                return (
                  <tr key={r.id} className="cursor-pointer"
                       onClick={() => router.push(`/portal/symbol/${r.symbol}`)}>
                    <td className="text-text-muted text-[10px]">
                      {r.emitted_at ? new Date(r.emitted_at).toLocaleString("en-IN", {
                        day: "2-digit", month: "short",
                        hour: "2-digit", minute: "2-digit",
                      }) : "—"}
                    </td>
                    <td className="font-bold">{r.symbol}</td>
                    <td>
                      <span className={clsx("broker-pill",
                        r.direction === "BULLISH" ? "bull" : "bear")}>
                        {r.direction === "BULLISH"
                          ? <TrendingUp className="w-3 h-3" />
                          : <TrendingDown className="w-3 h-3" />}
                        {r.direction === "BULLISH" ? "BUY" : "SELL"}
                      </span>
                    </td>
                    <td className={clsx("num font-bold",
                      (r.confidence || 0) >= 70 ? "text-accent-green" :
                      (r.confidence || 0) >= 55 ? "text-accent-amber" : "text-text-muted")}>
                      {Math.round(r.confidence || 0)}
                    </td>
                    <td className="num">{r.entry ? `₹${fmt.inr(r.entry)}` : "—"}</td>
                    <td className="num text-accent-red">
                      {r.stoploss ? `₹${fmt.inr(r.stoploss)}` : "—"}
                    </td>
                    <td className="num text-accent-green">
                      {t1 ? `₹${fmt.inr(t1)}` : "—"}
                    </td>
                    <td>
                      <OutcomePill outcome={out} targetHit={r.outcome_target_hit} />
                    </td>
                    <td className={clsx("num font-bold",
                      (r.outcome_5d_pnl_pct || 0) > 0 ? "text-accent-green" :
                      (r.outcome_5d_pnl_pct || 0) < 0 ? "text-accent-red" : "text-text-muted")}>
                      {r.outcome_5d_pnl_pct != null
                        ? `${r.outcome_5d_pnl_pct > 0 ? "+" : ""}${r.outcome_5d_pnl_pct.toFixed(2)}%`
                        : "—"}
                    </td>
                    <td>
                      <button className="text-text-muted hover:text-accent-amber text-[11px]">View</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-[10px] text-text-muted text-center italic pt-2">
        14-day retention. Older signals are auto-purged. Past performance ≠ future results.
      </div>
    </div>
  );
}


function OutcomePill({ outcome, targetHit }:
                      { outcome: "WIN" | "LOSS" | "PENDING"; targetHit?: number }) {
  if (outcome === "WIN") {
    return (
      <span className="broker-pill bull">
        <CheckCircle2 className="w-3 h-3" />
        WIN{targetHit ? ` · T${targetHit}` : ""}
      </span>
    );
  }
  if (outcome === "LOSS") {
    return <span className="broker-pill bear"><XCircle className="w-3 h-3" /> LOSS</span>;
  }
  return <span className="broker-pill neut"><Clock className="w-3 h-3" /> PENDING</span>;
}


function SortableTH({ label, k, sortKey, sortDesc, onSort, className }: {
  label: string; k: SortKey; sortKey: SortKey; sortDesc: boolean;
  onSort: (k: SortKey) => void; className?: string;
}) {
  const active = sortKey === k;
  return (
    <th onClick={() => onSort(k)}
        className={clsx("sortable", active && "active", className)}>
      {label}
      <span className="sort-arrow">
        {active
          ? (sortDesc ? <ChevronDown className="w-3 h-3 inline" /> : <ChevronUp className="w-3 h-3 inline" />)
          : <ChevronDown className="w-3 h-3 inline opacity-30" />}
      </span>
    </th>
  );
}
