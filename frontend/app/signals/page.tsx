"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { SignalCard } from "@/components/SignalCard";

export default function SignalsPage() {
  const [watchlist, setWatchlist] = useState("RELIANCE,TCS,INFY,HDFCBANK,ICICIBANK,SBIN,ITC,LT,AXISBANK,BAJFINANCE,NIFTY,BANKNIFTY");
  const url = `/api/signals/live?symbols=${encodeURIComponent(watchlist)}`;
  const { data, isLoading, mutate } = useSWR<{ signals: any[] }>(url, fetcher, { refreshInterval: 60_000 });

  return (
    <div className="space-y-4">
      <Panel title="Watchlist">
        <div className="flex gap-2 items-center">
          <input
            value={watchlist}
            onChange={(e) => setWatchlist(e.target.value.toUpperCase())}
            className="flex-1 bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono text-text-primary"
            placeholder="Comma-separated symbols (e.g. RELIANCE,TCS,NIFTY)"
          />
          <button
            onClick={() => mutate()}
            className="px-4 py-1.5 bg-accent-amber text-black rounded text-sm font-semibold hover:opacity-90"
          >
            Run
          </button>
        </div>
        <div className="text-[10px] text-text-muted mt-2">
          Auto-refreshes every 60s. Each signal blends Technical + SMC + Options + Astrology + Gann + Numerology with weighted confluence.
        </div>
      </Panel>

      {isLoading && <div className="text-text-secondary text-sm">Running multi-engine analysis…</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-3">
        {(data?.signals || [])
          .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
          .map((s: any) => <SignalCard key={s.symbol} s={s} />)}
      </div>
    </div>
  );
}
