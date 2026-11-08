"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt } from "@/lib/format";
import { Coins, Flame, Sparkles, ArrowRight, RefreshCw } from "lucide-react";
import clsx from "clsx";


type Commodity = {
  symbol: string;
  display: string;
  category: string;
  ruling_planet: string;
  spot?: number;
  direction: string;
  confidence: number;
  engines: any;
  top_astro_reason: string | null;
};


export default function CommoditiesPage() {
  const router = useRouter();
  const { data: scan, isLoading, mutate } = useSWR<any>(
    "/api/commodities/scan?horizon=SWING&min_confidence=55",
    fetcher,
    { refreshInterval: 300_000, revalidateOnFocus: false },
  );

  return (
    <div className="space-y-4">
      <Panel title="MCX Commodities — GOLD · SILVER · CRUDE · NAT GAS · METALS"
        right={
          <button onClick={() => mutate()} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            {isLoading ? "scanning…" : "rescan"}
          </button>
        }>
        <div className="text-[11px] text-text-secondary">
          Uses traditional <strong>Mundane astrology</strong> — each commodity has a ruling planet
          (Sun = Gold, Moon = Silver, Mars = Crude/NG, Venus = Copper, Saturn = Nickel/Lead, Mercury = Aluminium).
          The astrology score reflects the ruler's status TODAY (direct/retrograde, nakshatra,
          aspect to Sun = demand-cycle proxy).
        </div>
      </Panel>

      {/* Stats */}
      {scan && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard label="Universe scanned" value={scan.scanned} sub={`of ${scan.universe_size}`} />
          <KpiCard label="BUY signals" value={scan.top_buy?.length || 0} color="text-accent-green" sub={`conf ≥ ${scan.min_confidence}%`} />
          <KpiCard label="SELL signals" value={scan.top_sell?.length || 0} color="text-accent-red" />
          <KpiCard label="Categories" value={Object.keys(scan.by_category || {}).length} color="text-accent-amber" />
        </div>
      )}

      {/* Buy + Sell tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <CommodityTable title="BUY Picks" rows={scan?.top_buy || []} dir="BUY"
                         loading={isLoading} onRow={(s) => router.push(`/commodities/${s}`)} />
        <CommodityTable title="SELL Picks" rows={scan?.top_sell || []} dir="SELL"
                         loading={isLoading} onRow={(s) => router.push(`/commodities/${s}`)} />
      </div>

      {/* Category breakdown */}
      {scan?.by_category && (
        <Panel title="By category">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {Object.entries(scan.by_category).map(([category, items]: any) => (
              <div key={category} className="border border-bg-line rounded p-3 bg-card">
                <div className="text-[11px] font-bold text-accent-amber uppercase tracking-wider mb-2">
                  {category === "Precious metals" && <Coins className="w-3 h-3 inline mr-1" />}
                  {category === "Energy" && <Flame className="w-3 h-3 inline mr-1" />}
                  {category}
                </div>
                <div className="space-y-1">
                  {(items as any[]).map((item: any) => (
                    <button key={item.symbol}
                      onClick={() => router.push(`/commodities/${item.symbol}`)}
                      className="w-full flex items-center justify-between text-[11px] hover:bg-bg-base/40 px-1 py-0.5 rounded">
                      <div>
                        <span className="text-text-primary font-semibold">{item.display}</span>
                        <span className="text-text-muted ml-2 text-[10px]">({item.ruling_planet})</span>
                      </div>
                      <span className={clsx("font-bold tabular",
                        item.direction === "BULLISH" ? "text-accent-green"
                        : item.direction === "BEARISH" ? "text-accent-red"
                        : "text-text-muted")}>
                        {item.confidence.toFixed(0)}%
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className="text-[10px] text-text-muted text-center py-2">
        Refreshes every 5 min. Click any commodity to open the full analyzer view (chart, engines, options trade plan, gap forecast).
      </div>
    </div>
  );
}


function KpiCard({ label, value, sub, color }:
                  { label: string; value: number; sub?: string; color?: string }) {
  return (
    <div className="bg-card border border-bg-line rounded p-3 shadow-card">
      <div className="text-[9.5px] uppercase text-text-muted tracking-wider font-semibold">{label}</div>
      <div className={clsx("text-2xl font-bold tabular block mt-1", color || "text-text-primary")}>{value}</div>
      {sub && <div className="text-[10px] text-text-muted">{sub}</div>}
    </div>
  );
}


function CommodityTable({ title, rows, dir, loading, onRow }:
                          { title: string; rows: Commodity[]; dir: "BUY" | "SELL";
                            loading: boolean; onRow: (sym: string) => void }) {
  const color = dir === "BUY" ? "text-accent-green" : "text-accent-red";
  return (
    <Panel title={`${title}  ·  ${rows.length}`} noPad>
      {rows.length === 0 && !loading && (
        <div className="text-text-muted text-[11px] py-6 text-center px-4">
          No qualifying {dir.toLowerCase()} picks.
        </div>
      )}
      <div className="divide-y divide-bg-line/40">
        {rows.map((r) => (
          <button key={r.symbol} onClick={() => onRow(r.symbol)}
            className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-bg-base/40 text-left transition-colors">
            <div className={clsx("w-12 text-center text-[10px] font-bold uppercase rounded py-1",
              dir === "BUY" ? "bg-accent-green/15 text-accent-green border border-accent-green/30"
                            : "bg-accent-red/15 text-accent-red border border-accent-red/30")}>
              {dir}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-text-primary font-semibold text-[13px]">
                {r.display} <span className="text-text-muted text-[10px]">({r.symbol})</span>
              </div>
              <div className="text-[10px] text-text-muted">
                {r.category} · ruler {r.ruling_planet}
              </div>
              {r.top_astro_reason && (
                <div className="text-[9.5px] text-text-muted italic mt-0.5 truncate">
                  {r.top_astro_reason}
                </div>
              )}
            </div>
            <div className="text-right shrink-0 w-16">
              <div className="text-accent-amber font-bold text-[12px] tabular">{r.confidence.toFixed(0)}%</div>
              <div className="text-[9px] text-text-muted">{r.direction}</div>
            </div>
            <ArrowRight className="w-3 h-3 text-text-muted shrink-0" />
          </button>
        ))}
      </div>
    </Panel>
  );
}
