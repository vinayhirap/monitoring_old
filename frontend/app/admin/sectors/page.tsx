"use client";

/**
 * Admin sectors view — full sector analytics including stats the user
 * portal hides. Same `/api/portal/sector-picks` endpoint (admins bypass
 * the tier gate via the `require_tier` ADMIN_ROLES exemption).
 *
 * Differences from the user-portal version:
 *   • Shows ALL sectors regardless of bias (not just top bullish + top bearish)
 *   • Full table with every pick per sector
 *   • Sortable columns
 *   • No "Educational only" disclaimer — admin already knows
 */

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { authedFetcher as fetcher } from "@/lib/auth";
import { fmt } from "@/lib/format";
import {
  TrendingUp, TrendingDown, Minus, RefreshCw, Grid3x3,
  ChevronDown, ChevronUp, ArrowRight,
} from "lucide-react";
import clsx from "clsx";


type Horizon = "INTRADAY" | "SWING" | "POSITIONAL";
type SortKey = "net" | "bullish" | "bearish" | "confidence" | "name";


export default function AdminSectorsPage() {
  const router = useRouter();
  const [horizon, setHorizon] = useState<Horizon>("SWING");
  const [minStars, setMinStars] = useState(3);
  const [sortKey, setSortKey] = useState<SortKey>("net");
  const [sortDesc, setSortDesc] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const url = `/api/portal/sector-picks?horizon=${horizon}&min_stars=${minStars}`;
  const { data, isLoading, mutate } = useSWR<any>(url, fetcher,
    { refreshInterval: 300_000, shouldRetryOnError: false });

  const sectors = useMemo(() => {
    const rows = (data?.sectors || []) as any[];
    return [...rows].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "net":         cmp = a.net_sentiment - b.net_sentiment; break;
        case "bullish":     cmp = a.bullish_count - b.bullish_count; break;
        case "bearish":     cmp = a.bearish_count - b.bearish_count; break;
        case "confidence":  cmp = a.avg_confidence - b.avg_confidence; break;
        case "name":        cmp = a.sector.localeCompare(b.sector); break;
      }
      return sortDesc ? -cmp : cmp;
    });
  }, [data, sortKey, sortDesc]);

  const toggleSort = (k: SortKey) => {
    if (sortKey === k) setSortDesc(!sortDesc);
    else { setSortKey(k); setSortDesc(true); }
  };

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="bg-bg-surface border border-bg-line rounded-lg">
        <div className="flex items-center justify-between p-3 border-b border-bg-line">
          <div>
            <h1 className="text-base font-bold text-text-primary flex items-center gap-2">
              <Grid3x3 className="w-4 h-4 text-accent-amber" />
              Sector Analytics
            </h1>
            <p className="text-[11px] text-text-muted">
              {data?.total_sectors || 0} sectors · {data?.total_picks || 0} picks · admin view
            </p>
          </div>
          <button onClick={() => mutate()} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            Refresh
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 p-3 flex-wrap">
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
        </div>
      </div>

      {/* Empty state */}
      {!isLoading && sectors.length === 0 && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <p className="text-text-muted text-sm">No sector data. Lower the Min stars filter.</p>
        </div>
      )}

      {/* Full sortable table */}
      {sectors.length > 0 && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <SortableTH label="Sector" k="name" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} />
                <th>Bias</th>
                <SortableTH label="Bullish" k="bullish" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <SortableTH label="Bearish" k="bearish" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <SortableTH label="Net" k="net" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <SortableTH label="Avg Conf%" k="confidence" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <th>Top BUY</th>
                <th>Top SELL</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sectors.map((s) => (
                <>
                  <tr key={s.sector} className="cursor-pointer"
                       onClick={() => setExpanded(expanded === s.sector ? null : s.sector)}>
                    <td className="font-bold">{s.sector}</td>
                    <td>
                      <span className={clsx("broker-pill",
                        s.bias === "BULLISH" ? "bull" :
                        s.bias === "BEARISH" ? "bear" : "neut")}>
                        {s.bias === "BULLISH" ? <TrendingUp className="w-3 h-3" /> :
                         s.bias === "BEARISH" ? <TrendingDown className="w-3 h-3" /> :
                                                  <Minus className="w-3 h-3" />}
                        {s.bias}
                      </span>
                    </td>
                    <td className="num text-accent-green font-bold">{s.bullish_count}</td>
                    <td className="num text-accent-red font-bold">{s.bearish_count}</td>
                    <td className={clsx("num font-bold",
                      s.net_sentiment > 0 ? "text-accent-green" :
                      s.net_sentiment < 0 ? "text-accent-red" : "text-text-muted")}>
                      {s.net_sentiment > 0 ? "+" : ""}{s.net_sentiment}
                    </td>
                    <td className="num">{s.avg_confidence?.toFixed?.(1) || s.avg_confidence}</td>
                    <td>
                      {s.top_buy
                        ? <span className="text-accent-green font-semibold">{s.top_buy.symbol}</span>
                        : <span className="text-text-muted">—</span>}
                    </td>
                    <td>
                      {s.top_sell
                        ? <span className="text-accent-red font-semibold">{s.top_sell.symbol}</span>
                        : <span className="text-text-muted">—</span>}
                    </td>
                    <td>
                      {expanded === s.sector
                        ? <ChevronUp className="w-3.5 h-3.5 text-text-muted" />
                        : <ChevronDown className="w-3.5 h-3.5 text-text-muted" />}
                    </td>
                  </tr>
                  {expanded === s.sector && (
                    <tr key={`${s.sector}-exp`}>
                      <td colSpan={9} className="bg-bg-base/30">
                        <div className="p-2">
                          <div className="text-[10px] uppercase font-bold text-text-muted mb-2">
                            All picks in {s.sector}
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                            {(s.all_picks || []).map((p: any) => (
                              <div key={`${s.sector}-${p.symbol}-${p.direction}`}
                                   onClick={() => router.push(`/symbol/${p.symbol}`)}
                                   className="bg-bg-surface border border-bg-line rounded p-2 flex items-center justify-between cursor-pointer hover:border-accent-amber">
                                <div>
                                  <div className="font-bold text-text-primary text-sm">{p.symbol}</div>
                                  <div className="text-[10px] text-text-muted">
                                    {Math.round(p.confidence || 0)}% · {p.stars || 0}★
                                  </div>
                                </div>
                                <span className={clsx("broker-pill",
                                  p.direction === "BULLISH" ? "bull" : "bear")}>
                                  {p.direction === "BULLISH" ? "BUY" : "SELL"}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
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
