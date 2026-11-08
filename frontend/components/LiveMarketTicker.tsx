"use client";

/**
 * LiveMarketTicker — header strip showing live LTP for the four major
 * Indian indices: NIFTY 50, BANK NIFTY, FIN NIFTY, SENSEX.
 *
 * Implementation notes:
 *   • Uses SWR with 10s refresh — gives near-real-time feel without
 *     SSE infrastructure.
 *   • One fetch per index (4 SWR keys) so failures on one don't break others.
 *   • Uses `/api/market/quote/{symbol}` (already auth-aware).
 *   • Graceful: each card shows a skeleton-style placeholder while loading
 *     and falls back to "—" rather than disappearing on errors.
 *
 * Placement: render inside <PortalLayout> just below the header so it's
 * visible across every portal page.
 */

import useSWR from "swr";
import Link from "next/link";
import { authedFetcher as fetcher } from "@/lib/auth";
import { TrendingUp, TrendingDown } from "lucide-react";
import clsx from "clsx";


type Index = { symbol: string; display: string; exchange?: string };

const INDICES: Index[] = [
  { symbol: "NIFTY",     display: "NIFTY 50" },
  { symbol: "BANKNIFTY", display: "BANK NIFTY" },
  { symbol: "FINNIFTY",  display: "FIN NIFTY" },
  { symbol: "SENSEX",    display: "SENSEX",  exchange: "BSE" },
];


export function LiveMarketTicker() {
  // On phones (<sm), use a horizontal scroller — fits 4 indices in a single
  // tight row that the user can swipe through. On tablets+, switch to the
  // standard grid layout. Avoids the awkward 2x2 stack on narrow screens.
  return (
    <div className="bg-bg-surface border-b border-bg-line">
      {/* Mobile: horizontal scroll, no wrap */}
      <div className="sm:hidden overflow-x-auto -mx-2 px-2 py-2 scrollbar-hide">
        <div className="flex gap-3 min-w-max">
          {INDICES.map((idx) => (
            <div key={idx.symbol} className="min-w-[140px]">
              <IndexCard idx={idx} />
            </div>
          ))}
        </div>
      </div>
      {/* Tablet+: standard grid */}
      <div className="hidden sm:grid max-w-6xl mx-auto px-4 sm:px-6 py-2 grid-cols-2 md:grid-cols-4 gap-2">
        {INDICES.map((idx) => (
          <IndexCard key={idx.symbol} idx={idx} />
        ))}
      </div>
    </div>
  );
}


function IndexCard({ idx }: { idx: Index }) {
  const url = `/api/market/quote/${idx.symbol}?exchange=${idx.exchange || "NSE"}`;
  const { data } = useSWR<any>(url, fetcher,
    { refreshInterval: 10_000, shouldRetryOnError: false, dedupingInterval: 5_000 });

  // Backend response shape: { ltp, change, change_pct, ... }
  const ltp = data?.ltp ?? data?.data?.ltp;
  const change = data?.change ?? data?.data?.change;
  const changePct = data?.change_pct ?? data?.data?.change_pct;

  const isUp = (change ?? 0) >= 0;
  const colorClass = isUp ? "text-accent-green" : "text-accent-red";
  const Icon = isUp ? TrendingUp : TrendingDown;

  return (
    <Link href={`/portal/symbol/${idx.symbol}`}
          className="flex items-center justify-between px-2 py-1 rounded hover:bg-bg-base transition-colors">
      <div className="min-w-0">
        <div className="text-[9px] uppercase font-bold tracking-wider text-text-muted truncate">
          {idx.display}
        </div>
        <div className="text-[13px] font-bold tabular text-text-primary truncate">
          {ltp != null ? Number(ltp).toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}
        </div>
      </div>
      <div className={clsx("flex items-center gap-0.5 text-[10px] tabular shrink-0", colorClass)}>
        {ltp != null && <Icon className="w-2.5 h-2.5" />}
        <span className="font-semibold">
          {changePct != null
            ? `${changePct >= 0 ? "+" : ""}${Number(changePct).toFixed(2)}%`
            : "—"}
        </span>
      </div>
    </Link>
  );
}
