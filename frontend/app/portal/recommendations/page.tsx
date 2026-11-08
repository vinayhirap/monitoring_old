"use client";

/**
 * Recommendations page — broker-grade table (KingResearch / Zerodha Kite style).
 *
 * Layout:
 *   • Top toolbar: tabs (All / Intraday / Swing / Positional) + direction
 *     pills + min-stars filter + search + rescan
 *   • Sticky-header sortable table: Symbol · Sector · Signal · Stars ·
 *     Confidence · Entry · SL · T1 · RR · Instrument · Action
 *   • Rows clickable to drill into the full symbol view
 *
 * No engine internals exposed (USER role). Astrology jargon removed.
 */

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import { fmt } from "@/lib/format";
import {
  Search, RefreshCw, Star, TrendingUp, TrendingDown,
  ChevronUp, ChevronDown, ArrowRight, Filter, LayoutGrid, List,
} from "lucide-react";
import { PickCardExpanded } from "@/components/PickCard";
import clsx from "clsx";


type Horizon = "ALL" | "INTRADAY" | "SWING" | "POSITIONAL";
type Direction = "ALL" | "BUY" | "SELL";
type SortKey = "stars" | "confidence" | "rr" | "symbol";
type ViewMode = "cards" | "table";


export default function PortalRecommendationsPage() {
  const router = useRouter();

  // ----- Filters -----
  const [horizon, setHorizon] = useState<Horizon>("ALL");
  const [direction, setDirection] = useState<Direction>("ALL");
  const [minStars, setMinStars] = useState(3);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [sortDesc, setSortDesc] = useState(true);
  // View toggle — Cards is the new default (cleaner, more readable);
  // Table preserved for power users who want dense rows + sorting.
  const [viewMode, setViewMode] = useState<ViewMode>("cards");

  // The backend exposes one horizon per call. When ALL is selected, fan
  // out to all three and merge. SWR de-dupes if the same key is requested
  // from multiple components.
  const horizons: Exclude<Horizon, "ALL">[] = horizon === "ALL"
    ? ["INTRADAY", "SWING", "POSITIONAL"]
    : [horizon];

  // Single SWR key per horizon to enable cache reuse across tab switches
  const swing = useSWR<any>(
    horizons.includes("SWING")
      ? `/api/portal/top-picks?horizon=SWING&min_stars=${minStars}&top_n=20`
      : null,
    fetcher,
    { refreshInterval: 300_000, revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const intraday = useSWR<any>(
    horizons.includes("INTRADAY")
      ? `/api/portal/top-picks?horizon=INTRADAY&min_stars=${minStars}&top_n=20`
      : null,
    fetcher,
    { refreshInterval: 300_000, revalidateOnFocus: false, shouldRetryOnError: false },
  );
  const positional = useSWR<any>(
    horizons.includes("POSITIONAL")
      ? `/api/portal/top-picks?horizon=POSITIONAL&min_stars=${minStars}&top_n=20`
      : null,
    fetcher,
    { refreshInterval: 300_000, revalidateOnFocus: false, shouldRetryOnError: false },
  );

  // Paywall (402) detection — INTRADAY/POSITIONAL require INTERMEDIATE+
  const paywallError =
    [swing.error, intraday.error, positional.error]
      .find((e) => e instanceof ApiError && e.status === 402);
  if (paywallError) return <UpgradeRequired error={paywallError} />;

  // ----- Merge + normalize -----
  type Row = {
    symbol: string;
    sector?: string;
    direction: "BULLISH" | "BEARISH";
    stars: number;
    confidence: number;
    entry: number;
    stoploss: number;
    target_1: number;
    target_2?: number;
    target_3?: number;
    rr: number;
    horizon: string;
    best_instrument?: string;
    // Live tape fields (added by backend tape_consistency enrichment)
    day_change_pct?: number | null;
    live_ltp?: number | null;
    tape_status?: string;
    hora_conflict?: boolean;
    live_verdict?: string;
    live_label?: string;
    live_reasons?: string[];
  };

  const rows: Row[] = useMemo(() => {
    const all: Row[] = [];
    const sources: Array<[any, string]> = [
      [swing.data, "SWING"],
      [intraday.data, "INTRADAY"],
      [positional.data, "POSITIONAL"],
    ];
    for (const [data, hz] of sources) {
      if (!data) continue;
      const both = [
        ...(data.top_buy || []).map((p: any) => ({ ...p, direction: "BULLISH" })),
        ...(data.top_sell || []).map((p: any) => ({ ...p, direction: "BEARISH" })),
      ];
      for (const p of both) {
        const entry = p.entry ?? 0;
        const sl    = p.stoploss ?? 0;
        const t1    = (p.targets && p.targets[0]) ?? 0;
        const risk  = Math.abs(entry - sl);
        const rew   = Math.abs(t1 - entry);
        const rr    = risk > 0 ? rew / risk : 0;
        all.push({
          symbol: p.symbol,
          sector: p.sector,
          direction: p.direction,
          stars: p.stars ?? 0,
          confidence: p.confidence ?? 0,
          entry, stoploss: sl,
          target_1: t1,
          target_2: p.targets?.[1],
          target_3: p.targets?.[2],
          rr,
          horizon: hz,
          best_instrument: p.best_instrument,
          // Pass through live tape fields so PickCardExpanded + table both show them
          day_change_pct: p.day_change_pct,
          live_ltp:       p.live_ltp,
          tape_status:    p.tape_status,
          hora_conflict:  p.hora_conflict,
          live_verdict:   p.live_verdict,
          live_label:     p.live_label,
          live_reasons:   p.live_reasons,
        });
      }
    }
    return all;
  }, [swing.data, intraday.data, positional.data]);

  // Filter + sort
  const filtered = useMemo(() => {
    let r = rows;
    if (direction !== "ALL") {
      r = r.filter((x) => (direction === "BUY"
        ? x.direction === "BULLISH" : x.direction === "BEARISH"));
    }
    if (search.trim()) {
      const q = search.toUpperCase();
      r = r.filter((x) => x.symbol.includes(q) || (x.sector || "").toUpperCase().includes(q));
    }
    r = [...r].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "stars":      cmp = a.stars - b.stars; break;
        case "confidence": cmp = a.confidence - b.confidence; break;
        case "rr":         cmp = a.rr - b.rr; break;
        case "symbol":     cmp = a.symbol.localeCompare(b.symbol); break;
      }
      return sortDesc ? -cmp : cmp;
    });
    return r;
  }, [rows, direction, search, sortKey, sortDesc]);

  const isLoading = swing.isLoading || intraday.isLoading || positional.isLoading;

  const rescan = () => {
    swing.mutate(); intraday.mutate(); positional.mutate();
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDesc(!sortDesc);
    else { setSortKey(key); setSortDesc(true); }
  };

  return (
    <div className="space-y-3">
      {/* ───── Header + toolbar ───── */}
      <div className="bg-bg-surface border border-bg-line rounded-lg">
        {/* Title row */}
        <div className="flex items-center justify-between p-3 border-b border-bg-line">
          <div>
            <h1 className="text-base font-bold text-text-primary">Recommendations</h1>
            <p className="text-[11px] text-text-muted">
              {filtered.length} picks · auto-refresh every 5 min
            </p>
          </div>
          <button onClick={rescan} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            Rescan
          </button>
        </div>

        {/* Filter strip */}
        <div className="flex items-center gap-3 p-3 flex-wrap border-b border-bg-line">
          {/* Horizon tabs */}
          <div className="flex items-center gap-1">
            {(["ALL", "INTRADAY", "SWING", "POSITIONAL"] as Horizon[]).map((h) => (
              <button key={h} onClick={() => setHorizon(h)}
                className={clsx("broker-chip", horizon === h && "active")}>
                {h}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-bg-line mx-1" aria-hidden />

          {/* Direction */}
          <div className="flex items-center gap-1">
            {(["ALL", "BUY", "SELL"] as Direction[]).map((d) => (
              <button key={d} onClick={() => setDirection(d)}
                className={clsx("broker-chip", direction === d && "active")}>
                {d}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-bg-line mx-1" aria-hidden />

          {/* Min stars */}
          <div className="flex items-center gap-1 text-[11px] text-text-muted">
            <Filter className="w-3 h-3" /> Min stars:
            {[2, 3, 4, 5].map((n) => (
              <button key={n} onClick={() => setMinStars(n)}
                className={clsx("broker-chip", minStars === n && "active")}>
                {n}★
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

          {/* View mode toggle — Cards (default) or Table */}
          <div className="flex bg-bg-base border border-bg-line rounded p-0.5"
                title="Switch between card and table view">
            <button onClick={() => setViewMode("cards")}
              className={clsx("flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold",
                viewMode === "cards"
                  ? "bg-accent-amber text-white"
                  : "text-text-secondary hover:text-text-primary")}>
              <LayoutGrid className="w-3 h-3" /> Cards
            </button>
            <button onClick={() => setViewMode("table")}
              className={clsx("flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold",
                viewMode === "table"
                  ? "bg-accent-amber text-white"
                  : "text-text-secondary hover:text-text-primary")}>
              <List className="w-3 h-3" /> Table
            </button>
          </div>
        </div>
      </div>

      {/* ───── Empty / loading states ───── */}
      {isLoading && filtered.length === 0 && (
        <div className="text-text-muted text-center py-10 text-sm">
          Scanning the market for high-conviction picks…
        </div>
      )}
      {!isLoading && filtered.length === 0 && (
        <div className="bg-bg-surface border border-bg-line rounded p-8 text-center">
          <p className="text-text-muted text-sm">
            No picks match your filters. Try lowering Min stars or selecting "ALL" horizon.
          </p>
        </div>
      )}

      {/* ───── Cards view (default) ───── */}
      {filtered.length > 0 && viewMode === "cards" && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {filtered.map((r) => (
            <PickCardExpanded
              key={`${r.symbol}-${r.horizon}-${r.direction}`}
              pick={{
                symbol: r.symbol,
                sector: r.sector,
                direction: r.direction,
                stars: r.stars,
                confidence: r.confidence,
                entry: r.entry,
                stoploss: r.stoploss,
                targets: [r.target_1, r.target_2, r.target_3].filter((t): t is number => t != null),
                horizon: r.horizon,
                best_instrument: r.best_instrument,
                // Live tape fields → PickCardExpanded renders day-change pill +
                // tape-conflict banner so users see "AXISBANK down -0.98% today,
                // tape contradicts BULLISH" at a glance.
                day_change_pct: r.day_change_pct,
                live_ltp:       r.live_ltp,
                tape_status:    r.tape_status as any,
                hora_conflict:  r.hora_conflict,
                live_verdict:   r.live_verdict as any,
                live_label:     r.live_label,
                live_reasons:   r.live_reasons,
              }}
            />
          ))}
        </div>
      )}

      {/* ───── Table view (power users) ───── */}
      {filtered.length > 0 && viewMode === "table" && (
        <div className="broker-table-wrap">
          <table className="broker-table">
            <thead>
              <tr>
                <SortableTH label="Symbol" k="symbol" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} />
                <th>Sector</th>
                <th>Signal</th>
                <th>Horizon</th>
                <SortableTH label="Stars" k="stars" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <SortableTH label="Conf%" k="confidence" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <th className="num">Day %</th>
                <th className="num">Entry</th>
                <th className="num">SL</th>
                <th className="num">T1</th>
                <SortableTH label="R:R" k="rr" sortKey={sortKey} sortDesc={sortDesc} onSort={toggleSort} className="num" />
                <th>Type</th>
                <th>Tape</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={`${r.symbol}-${r.horizon}-${r.direction}`}
                    className="cursor-pointer"
                    onClick={() => router.push(`/portal/symbol/${r.symbol}`)}>
                  <td className="font-bold">{r.symbol}</td>
                  <td className="text-text-muted text-[10px]">{r.sector || "—"}</td>
                  <td>
                    <span className={clsx("broker-pill",
                      r.direction === "BULLISH" ? "bull" : "bear")}>
                      {r.direction === "BULLISH"
                        ? <TrendingUp className="w-3 h-3" />
                        : <TrendingDown className="w-3 h-3" />}
                      {r.direction === "BULLISH" ? "BUY" : "SELL"}
                    </span>
                  </td>
                  <td className="text-[10px] text-text-secondary">{r.horizon}</td>
                  <td className="num">
                    <span className="inline-flex">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <Star key={i} className={clsx("w-3 h-3",
                          i < r.stars ? "fill-accent-amber text-accent-amber" : "text-text-muted/30")} />
                      ))}
                    </span>
                  </td>
                  <td className={clsx("num font-bold",
                    r.confidence >= 70 ? "text-accent-green" :
                    r.confidence >= 55 ? "text-accent-amber" : "text-text-muted")}>
                    {Math.round(r.confidence)}
                  </td>
                  {/* Day % — colored by SIGN of move, not by direction.
                      A BULLISH pick in red day-% column = visual contradiction. */}
                  <td className={clsx("num font-bold tabular",
                    r.day_change_pct == null ? "text-text-muted" :
                    r.day_change_pct > 0 ? "text-accent-green" :
                    r.day_change_pct < -0.05 ? "text-accent-red" : "text-text-muted")}>
                    {r.day_change_pct == null ? "—"
                      : `${r.day_change_pct > 0 ? "+" : ""}${r.day_change_pct.toFixed(2)}%`}
                  </td>
                  <td className="num">₹{fmt.inr(r.entry)}</td>
                  <td className="num text-accent-red">₹{fmt.inr(r.stoploss)}</td>
                  <td className="num text-accent-green">₹{fmt.inr(r.target_1)}</td>
                  <td className={clsx("num font-bold",
                    r.rr >= 2 ? "text-accent-green" :
                    r.rr >= 1.5 ? "text-accent-amber" : "text-accent-red")}>
                    {r.rr.toFixed(2)}
                  </td>
                  <td className="text-[10px] text-text-secondary">{r.best_instrument || "EQ"}</td>
                  {/* Tape-consistency cell — shows ALIGN / CONFLICT / WAIT badge */}
                  <td>
                    {r.live_verdict === "AVOID_NOW" ? (
                      <span className="text-[9px] uppercase font-bold tracking-wider text-accent-red bg-accent-red/10 border border-accent-red/30 rounded px-1.5 py-0.5"
                            title={r.live_reasons?.[0] || "Tape contradicts direction"}>
                        Conflict
                      </span>
                    ) : r.live_verdict === "WAIT" ? (
                      <span className="text-[9px] uppercase font-bold tracking-wider text-accent-amber bg-accent-amber/10 border border-accent-amber/30 rounded px-1.5 py-0.5"
                            title={r.live_reasons?.[0] || "Wait for confirmation"}>
                        Wait
                      </span>
                    ) : r.tape_status === "ALIGNED" ? (
                      <span className="text-[9px] uppercase font-bold tracking-wider text-accent-green bg-accent-green/10 border border-accent-green/30 rounded px-1.5 py-0.5"
                            title="Tape confirms direction">
                        Aligned
                      </span>
                    ) : (
                      <span className="text-[9px] uppercase text-text-muted">—</span>
                    )}
                  </td>
                  <td>
                    <ArrowRight className="w-3.5 h-3.5 text-text-muted" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ───── Footer disclaimer ───── */}
      <div className="text-[10px] text-text-muted text-center italic pt-2">
        Educational/analytical only. Verify every recommendation before risking capital.
      </div>
    </div>
  );
}


/** Sortable table header cell — clicks toggle direction; shows arrow when active. */
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
