"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt } from "@/lib/format";
import { AnimatedNumber } from "@/components/animated";
import {
  TrendingUp, TrendingDown, ArrowRight, RefreshCw, Filter,
  ChevronDown, ChevronUp, Star, Target, Shield, Clock,
} from "lucide-react";
import clsx from "clsx";


// ─────────────────────────────────────────────────────────────────────────────
// Professional Grade panel — uses /api/recommend/professional
// ─────────────────────────────────────────────────────────────────────────────

function ProfessionalGradeSection({ horizon, minStars, quick }:
                                    { horizon: string; minStars: number; quick: boolean }) {
  const router = useRouter();
  const url = `/api/recommend/professional?horizon=${horizon}&min_stars=${minStars}&top_n=8&quick=${quick}&apply_stability=true`;
  const { data, isLoading } = useSWR<any>(url, fetcher,
    { refreshInterval: 300_000, revalidateOnFocus: false, dedupingInterval: 30_000 });

  return (
    <Panel title={`Professional Grade — ${horizon}  (min ${minStars}★)`}
      right={<span className="text-[10px] text-text-muted">
        {isLoading ? "computing…" : `${(data?.top_buy?.length || 0) + (data?.top_sell?.length || 0)} qualified`}
      </span>}>
      {isLoading && !data && (
        <div className="text-text-muted text-[11px] py-6 text-center">Grading universe…</div>
      )}
      {data && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {[...(data.top_buy || []), ...(data.top_sell || [])].map((pick: any) => (
            <ProGradeCard key={pick.symbol} pick={pick}
                          onClick={() => router.push(`/symbol/${pick.symbol}`)} />
          ))}
          {(data.top_buy?.length || 0) + (data.top_sell?.length || 0) === 0 && (
            <div className="col-span-full text-text-muted text-[11px] py-6 text-center">
              No picks meet the {minStars}★ minimum. Lower the threshold or try a different horizon.
            </div>
          )}
        </div>
      )}
      {data?.disclaimer && (
        <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2 mt-3">
          {data.disclaimer}
        </div>
      )}
    </Panel>
  );
}


function ProGradeCard({ pick, onClick }: { pick: any; onClick: () => void }) {
  const g = pick.grade;
  const dirColor = g.direction === "BULLISH" ? "text-accent-green"
                   : g.direction === "BEARISH" ? "text-accent-red"
                   : "text-text-secondary";
  const labelColor = g.conviction_label.startsWith("STRONG_BUY") || g.conviction_label === "BUY"
                      ? "bg-accent-green/15 text-accent-green border-accent-green/40"
                      : g.conviction_label.startsWith("STRONG_SELL") || g.conviction_label === "SELL"
                      ? "bg-accent-red/15 text-accent-red border-accent-red/40"
                      : "bg-accent-amber/15 text-accent-amber border-accent-amber/40";
  const topInst = g.instrument_ranking?.[0];

  return (
    <button onClick={onClick}
      className="text-left bg-card border border-bg-line rounded-md p-3 hover:border-accent-amber transition-colors w-full">
      {/* Header */}
      <div className="flex items-baseline justify-between mb-2">
        <div>
          <div className="text-text-primary font-bold text-sm">{pick.symbol}</div>
          <div className="text-[10px] text-text-muted">{pick.sector}</div>
        </div>
        <div className="text-right">
          <div className={clsx("inline-block px-1.5 py-0.5 rounded text-[10px] uppercase font-bold border", labelColor)}>
            {g.conviction_label.replace("_", " ")}
          </div>
          <div className="flex justify-end gap-0.5 mt-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <Star key={i} className={clsx("w-3 h-3",
                i < g.stars ? "fill-accent-amber text-accent-amber" : "text-text-muted/30")} />
            ))}
          </div>
        </div>
      </div>

      {/* Confidence + agreement */}
      <div className="grid grid-cols-3 gap-2 text-[10px] mb-2">
        <div>
          <div className="text-text-muted uppercase tracking-wider">Conf</div>
          <div className={clsx("font-bold tabular", dirColor)}>{g.confidence.toFixed(1)}%</div>
        </div>
        <div>
          <div className="text-text-muted uppercase tracking-wider">Agreement</div>
          <div className="font-bold tabular text-text-primary">{g.engine_agreement_pct}%</div>
        </div>
        <div>
          <div className="text-text-muted uppercase tracking-wider">Direction</div>
          <div className={clsx("font-bold uppercase", dirColor)}>{g.direction}</div>
        </div>
      </div>

      {/* Instrument suitability ranking — top 3 */}
      <div className="border-t border-bg-line pt-2 mb-2">
        <div className="text-[9px] uppercase tracking-wider text-text-muted mb-1 font-semibold">
          Best instrument fit
        </div>
        <div className="space-y-0.5">
          {g.instrument_ranking?.slice(0, 3).map((inst: any) => (
            <div key={inst.instrument} className="flex items-center justify-between text-[10px]">
              <div className="flex items-center gap-1.5">
                <span className={clsx("font-bold w-12",
                  inst.recommended ? "text-accent-amber" : "text-text-muted")}>
                  {inst.instrument}
                </span>
                <span className="text-text-secondary truncate max-w-[160px]">{inst.subtype}</span>
              </div>
              <span className={clsx("font-bold tabular",
                inst.score >= 70 ? "text-accent-green"
                : inst.score >= 50 ? "text-accent-amber"
                : "text-text-muted")}>
                {inst.score}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Risk variants — moderate sizing */}
      {g.risk_variants?.MODERATE && (
        <div className="grid grid-cols-3 gap-2 text-[10px] border-t border-bg-line pt-2">
          <div>
            <div className="text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Shield className="w-2.5 h-2.5" />Size
            </div>
            <div className="font-bold tabular">{g.risk_variants.MODERATE.allocation_pct}%</div>
          </div>
          <div>
            <div className="text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Target className="w-2.5 h-2.5" />Qty
            </div>
            <div className="font-bold tabular">{g.risk_variants.MODERATE.suggested_qty}</div>
          </div>
          <div>
            <div className="text-text-muted uppercase tracking-wider flex items-center gap-1">
              <Clock className="w-2.5 h-2.5" />Horizon
            </div>
            <div className="font-bold uppercase">{g.horizon}</div>
          </div>
        </div>
      )}

      {/* Stability badge */}
      {g.stability && (
        <div className="text-[9px] text-text-muted mt-2 pt-2 border-t border-bg-line italic">
          Stability: <span className={clsx(
            g.stability.stability_score >= 75 ? "text-accent-green"
            : g.stability.stability_score >= 50 ? "text-accent-amber"
            : "text-accent-red")}>
            {g.stability.stability_score.toFixed(0)}/100
          </span>
          {" · "}{g.stability.minutes_since_last_change.toFixed(0)}m since last change
        </div>
      )}
    </button>
  );
}

type Horizon = "INTRADAY" | "SWING" | "POSITIONAL";

export default function RecommendationsPage() {
  const router = useRouter();
  const [horizon, setHorizon] = useState<Horizon>("SWING");
  const [minConf, setMinConf] = useState(60);
  const [quick, setQuick] = useState(true);
  const [advanced, setAdvanced] = useState(false);

  const url = `/api/recommend/scan?horizon=${horizon}&min_confidence=${minConf}&top_n=20&quick=${quick}`;
  const { data, isLoading, mutate } = useSWR<any>(url, fetcher, {
    refreshInterval: 300_000, revalidateOnFocus: false, dedupingInterval: 30_000,
  });

  return (
    <div className="space-y-4">
      {/* Compact filter bar */}
      <Panel title="Today's Recommendations" noPad
        right={
          <button onClick={() => mutate()} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            {isLoading ? "scanning…" : "rescan"}
          </button>
        }>
        <div className="px-3.5 py-2.5 flex flex-wrap items-center gap-3 border-b border-bg-line bg-bg-base/30">
          <div className="flex gap-1">
            {(["INTRADAY", "SWING", "POSITIONAL"] as Horizon[]).map((h) => (
              <button key={h} onClick={() => setHorizon(h)}
                className={clsx("text-[10.5px] px-2.5 py-1 rounded font-semibold uppercase tracking-wider",
                  horizon === h
                    ? "bg-accent-amber text-black"
                    : "bg-bg-panel text-text-secondary hover:bg-bg-line")}>
                {h}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-1 ml-2">
            <span className="text-[10px] text-text-muted uppercase">Min conf</span>
            <input type="number" value={minConf}
              onChange={(e) => setMinConf(parseInt(e.target.value) || 0)}
              className="w-14 bg-bg-base border border-bg-line rounded px-2 py-0.5 text-[11px] tabular" />
            <span className="text-[10px] text-text-muted">%</span>
          </div>

          <button onClick={() => setQuick(!quick)}
            className={clsx("text-[10px] px-2 py-1 rounded border font-bold uppercase tracking-wider",
              quick ? "border-accent-green/40 text-accent-green bg-accent-green/5"
                    : "border-accent-amber/40 text-accent-amber bg-accent-amber/5")}>
            {quick ? "Quick (top 50)" : "Full (~180)"}
          </button>

          <button onClick={() => setAdvanced(!advanced)}
            className="ml-auto text-[10px] text-text-muted hover:text-accent-amber flex items-center gap-1">
            <Filter className="w-3 h-3" /> Advanced filters
            {advanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>

        {advanced && (
          <div className="px-3.5 py-2 border-b border-bg-line bg-bg-base/20 text-[10px] text-text-muted">
            For full control (esoteric threshold, consistency mode, DIAMOND-only filter, etc.),
            use the <a href="/pipeline" className="text-accent-amber underline">advanced Pipeline page</a>.
          </div>
        )}
      </Panel>

      {/* ─── Professional Grade panel — conviction stars + best instrument + risk variants ─── */}
      <ProfessionalGradeSection horizon={horizon} minStars={3} quick={quick} />

      {/* Stats strip */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiCard label="Universe scanned" value={data.scanned} sub={`of ${data.universe_size}`} />
          <KpiCard label="BUY picks" value={data.top_buy?.length || 0}
            sub={`min conf ${data.min_confidence}%`} color="text-accent-green" />
          <KpiCard label="SELL picks" value={data.top_sell?.length || 0}
            sub={`min conf ${data.min_confidence}%`} color="text-accent-red" />
          <KpiCard label="Sectors covered" value={Object.keys(data.by_sector || {}).length}
            sub="bullish vs bearish" color="text-accent-amber" />
        </div>
      )}

      {/* Buy + Sell tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <RecoTable title="BUY Picks" rows={data?.top_buy || []} dir="BUY"
          loading={isLoading} onRow={(s) => router.push(`/symbol/${s}`)} />
        <RecoTable title="SELL Picks" rows={data?.top_sell || []} dir="SELL"
          loading={isLoading} onRow={(s) => router.push(`/symbol/${s}`)} />
      </div>

      {/* Sector heatmap */}
      {data?.by_sector && (
        <Panel title="Sector Pulse (bullish − bearish stocks per sector)">
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
            {Object.values(data.by_sector)
              .sort((a: any, b: any) => (b.bullish - b.bearish) - (a.bullish - a.bearish))
              .map((s: any) => {
                const net = s.bullish - s.bearish;
                const intensity = Math.min(1, Math.abs(net) / 6);
                const bg = net > 0 ? `rgba(0, 214, 143, ${0.05 + intensity * 0.25})`
                           : net < 0 ? `rgba(255, 59, 105, ${0.05 + intensity * 0.25})`
                           : "transparent";
                return (
                  <div key={s.sector} className="border border-bg-line rounded p-2.5"
                       style={{ background: bg }}>
                    <div className="flex justify-between items-baseline">
                      <span className="text-text-primary text-[11.5px] font-semibold truncate">{s.sector}</span>
                      <span className={clsx("text-[14px] font-bold tabular",
                        net > 0 ? "text-accent-green" : net < 0 ? "text-accent-red" : "text-text-secondary")}>
                        {net > 0 ? "+" : ""}{net}
                      </span>
                    </div>
                    <div className="text-[10px] text-text-secondary tabular mt-0.5">
                      <span className="text-accent-green">{s.bulls}↑</span>
                      <span className="text-text-muted"> · </span>
                      <span className="text-accent-red">{s.bears}↓</span>
                      <span className="text-text-muted"> · </span>
                      <span>{s.count} total</span>
                    </div>
                  </div>
                );
              })}
          </div>
        </Panel>
      )}

      <div className="text-[10px] text-text-muted text-center py-2">
        Recommendations refresh every 5 min. Click any row to open the full analyzer view for that symbol.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color }:
                  { label: string; value: number; sub?: string; color?: string }) {
  return (
    <div className="bg-card border border-bg-line rounded-md p-3 shadow-card">
      <div className="text-[9.5px] uppercase text-text-muted tracking-wider font-semibold">{label}</div>
      <AnimatedNumber value={value} decimals={0}
        className={clsx("text-2xl font-bold tabular block mt-1", color || "text-text-primary")} />
      {sub && <div className="text-[10px] text-text-muted">{sub}</div>}
    </div>
  );
}

function RecoTable({ title, rows, dir, loading, onRow }:
                    { title: string; rows: any[]; dir: "BUY" | "SELL";
                      loading: boolean; onRow: (sym: string) => void }) {
  const color = dir === "BUY" ? "text-accent-green" : "text-accent-red";
  return (
    <Panel title={`${title}  ·  ${rows.length}`} noPad>
      {rows.length === 0 && !loading && (
        <div className="text-text-muted text-[11px] py-6 text-center px-4">
          No qualifying {dir.toLowerCase()} picks at the current confidence threshold.
        </div>
      )}
      {loading && rows.length === 0 && (
        <div className="text-text-muted text-[11px] py-6 text-center">Scanning…</div>
      )}
      <div className="divide-y divide-bg-line/40 max-h-[480px] overflow-y-auto">
        {rows.map((r: any) => (
          <button key={r.symbol} onClick={() => onRow(r.symbol)}
            className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-bg-base/40 text-left group transition-colors">
            <div className={clsx(
              "w-12 text-center text-[10px] font-bold uppercase rounded py-1 shrink-0",
              dir === "BUY" ? "bg-accent-green/15 text-accent-green border border-accent-green/30"
                            : "bg-accent-red/15 text-accent-red border border-accent-red/30"
            )}>
              {r.signal?.includes("STRONG") ? "★" : ""}{dir}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-text-primary font-semibold text-[13px]">{r.symbol}</div>
              <div className="text-[10px] text-text-muted">{r.sector}</div>
            </div>
            {/* Entry + SL + T1/T2/T3 inline */}
            <div className="text-right shrink-0 hidden md:block min-w-[200px]">
              <div className="text-[9px] text-text-muted uppercase tracking-wider">
                Entry · SL · T1·T2·T3
              </div>
              <div className="text-[10.5px] tabular leading-tight">
                <span className="text-text-secondary">₹{fmt.inr(r.entry)}</span>
                {" · "}
                <span className="text-accent-red">₹{fmt.inr(r.stoploss)}</span>
              </div>
              <div className="text-[10px] tabular leading-tight space-x-1">
                {(r.targets || []).slice(0, 3).map((t: number, i: number) => (
                  <span key={i} className={clsx(color, "font-semibold")}>
                    T{i + 1}:₹{fmt.inr(t)}
                  </span>
                ))}
              </div>
            </div>
            <div className="text-right shrink-0 w-16">
              <div className="text-accent-amber font-bold text-[12px] tabular">{fmt.num(r.confidence, 0)}%</div>
              <div className="text-[9px] text-text-muted">R:R {fmt.num(r.risk_reward, 1)}</div>
              {r.capital_allocation_pct > 0 && (
                <div className="text-[9px] text-text-muted">{fmt.num(r.capital_allocation_pct, 1)}% cap</div>
              )}
            </div>
            <ArrowRight className="w-3 h-3 text-text-muted group-hover:text-accent-amber transition-colors shrink-0" />
          </button>
        ))}
      </div>
    </Panel>
  );
}
