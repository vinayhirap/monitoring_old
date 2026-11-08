"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt } from "@/lib/format";
import { Coins, Flame, Sparkles, TrendingUp, TrendingDown, Clock } from "lucide-react";
import clsx from "clsx";


export default function CommodityDetailPage({ params }: { params: { symbol: string } }) {
  const sym = params.symbol.toUpperCase();
  const { data, isLoading, error } = useSWR<any>(`/api/commodities/${sym}`, fetcher,
    { refreshInterval: 30_000 });

  if (isLoading && !data) return <div className="text-text-muted text-sm p-4">Loading {sym}…</div>;
  if (error) return <div className="text-accent-red text-sm p-4">Error: {error.message}</div>;
  if (!data) return null;

  const up = data.direction === "BULLISH";
  const ltpColor = up ? "text-accent-green" : data.direction === "BEARISH" ? "text-accent-red" : "text-text-secondary";

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-8">
          <div className="text-2xl font-bold text-text-primary tracking-wide">
            {data.display}
          </div>
          <div className="text-[11px] text-text-muted uppercase tracking-wider">
            MCX · {data.category} · ruling planet <span className="text-accent-amber font-bold">{data.ruling_planet}</span>
            {data.secondary_planet && <> · secondary {data.secondary_planet}</>}
          </div>
        </div>
        <div className="col-span-12 md:col-span-4 text-right">
          <div className={clsx("text-3xl font-bold tabular", ltpColor)}>
            ₹{fmt.inr(data.ltp.ltp)}
          </div>
          <div className="text-[11px] text-text-muted">
            O {fmt.inr(data.ltp.open)} · H {fmt.inr(data.ltp.high)} · L {fmt.inr(data.ltp.low)}
          </div>
        </div>
      </div>

      {/* Verdict strip */}
      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-12 md:col-span-4">
          <Panel title="Verdict">
            <div className="flex items-baseline justify-between">
              <span className={clsx("text-2xl font-bold", ltpColor)}>{data.direction}</span>
              <span className="text-accent-amber font-bold tabular text-xl">{data.confidence}%</span>
            </div>
            <div className="text-[10px] text-text-muted mt-1">composite confidence</div>
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-4">
          <Panel title="Mundane Astrology">
            <div className="text-text-primary text-sm">
              {data.analyzers.mundane_astro.ruling_planet} —{" "}
              <span className={clsx(
                data.analyzers.mundane_astro.bias === "BULLISH" ? "text-accent-green"
                : data.analyzers.mundane_astro.bias === "BEARISH" ? "text-accent-red"
                : "text-accent-amber"
              )}>{data.analyzers.mundane_astro.bias}</span>
              <span className="text-text-muted ml-2 text-[11px]">
                ({data.analyzers.mundane_astro.score}/100)
              </span>
            </div>
            <ul className="text-[10px] text-text-muted mt-1 space-y-0.5">
              {data.analyzers.mundane_astro.reasons.slice(0, 3).map((r: string, i: number) => (
                <li key={i}>• {r}</li>
              ))}
            </ul>
          </Panel>
        </div>
        <div className="col-span-12 md:col-span-4">
          <Panel title="Current Hora">
            <div className="text-text-primary text-sm">
              {data.context.hora.ruler}
              {" — "}
              <span className={clsx(
                data.context.hora.bias === "bullish" ? "text-accent-green"
                : data.context.hora.bias === "bearish" ? "text-accent-red"
                : "text-text-secondary"
              )}>{data.context.hora.bias}</span>
            </div>
            <div className="text-[10px] text-text-muted mt-1">
              Next: {data.context.hora.next_ruler} in {data.context.hora.next_change_in_minutes}m
            </div>
          </Panel>
        </div>
      </div>

      {/* Analyzers */}
      <Panel title="Multi-Analyzer Verdict">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {Object.entries(data.analyzers).map(([name, a]: any) => (
            <div key={name} className="bg-card border border-bg-line rounded p-2">
              <div className="text-[9px] uppercase text-text-muted tracking-wider">{name.replace("_", " ")}</div>
              <div className="flex items-baseline justify-between mt-1">
                <span className={clsx("text-lg font-bold tabular",
                  a.bias === "BULLISH" ? "text-accent-green"
                  : a.bias === "BEARISH" ? "text-accent-red"
                  : "text-text-secondary")}>{a.score}</span>
                <span className="text-[10px] text-text-muted">{a.bias}</span>
              </div>
            </div>
          ))}
        </div>
      </Panel>

      {/* Strategy */}
      {data.strategy && data.strategy.strategy !== "WAIT" && (
        <Panel title="Recommended Strategy"
          right={<span className="text-[10px] text-accent-amber uppercase font-bold">
            {data.strategy.strategy}
          </span>}>
          <div className="text-[12px] text-text-secondary mb-3">{data.strategy.rationale}</div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-[11px]">
            <Stat label="Entry" value={`₹${fmt.inr(data.strategy.entry)}`} />
            <Stat label="Stop loss" value={`₹${fmt.inr(data.strategy.stoploss)}`} color="text-accent-red" />
            {(data.strategy.targets || []).slice(0, 3).map((t: number, i: number) => (
              <Stat key={i} label={`Target ${i + 1}`} value={`₹${fmt.inr(t)}`} color="text-accent-green" />
            ))}
          </div>
          {data.strategy.timing && data.strategy.timing.entry_time && (
            <div className="text-[10px] text-text-muted mt-3 pt-2 border-t border-bg-line">
              <Clock className="w-3 h-3 inline mr-1" />
              Suggested entry window: {new Date(data.strategy.timing.window_start).toLocaleTimeString()}
              {" — "}{new Date(data.strategy.timing.window_end).toLocaleTimeString()}
              {" · "}{data.strategy.timing.ruler} hora
            </div>
          )}
        </Panel>
      )}

      {/* Gap forecast */}
      {data.gap_forecast && !data.gap_forecast.error && (
        <Panel title={`Next-Session Gap Forecast — ${data.gap_forecast.next_session_date}`}
          right={<span className={clsx("text-[10px] uppercase font-bold px-2 py-0.5 rounded",
            data.gap_forecast.direction === "GAP_UP"   ? "bg-accent-green/20 text-accent-green"
            : data.gap_forecast.direction === "GAP_DOWN" ? "bg-accent-red/20 text-accent-red"
            : "bg-text-muted/20 text-text-muted")}>
            {data.gap_forecast.direction.replace("_", " ")}
          </span>}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
            <Stat label="Expected gap"
                  value={`${data.gap_forecast.expected_gap_pct > 0 ? "+" : ""}${data.gap_forecast.expected_gap_pct}%`}
                  color={data.gap_forecast.expected_gap_pct > 0 ? "text-accent-green" : "text-accent-red"} />
            <Stat label="Expected open" value={`₹${fmt.inr(data.gap_forecast.expected_open_price)}`} />
            <Stat label="Confidence" value={`${data.gap_forecast.confidence_pct}%`} />
            <Stat label="Band" value={`[${data.gap_forecast.confidence_band[0]}%, ${data.gap_forecast.confidence_band[1]}%]`} />
          </div>
        </Panel>
      )}

      <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2">
        MCX commodity — Mundane astrology layer is traditional planetary rulership of commodities.
        Confluence with technical/SMC required before risking capital. Not SEBI-registered advice.
      </div>
    </div>
  );
}
