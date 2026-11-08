"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt, biasColor, signalColor } from "@/lib/format";
import clsx from "clsx";

export default function AdvancedPage() {
  return (
    <div className="space-y-4">
      <MultiTimeframe />
      <SectorHeatmap />
    </div>
  );
}

// ---------------------------------------------------------------------------

function MultiTimeframe() {
  const [symbol, setSymbol] = useState("RELIANCE");
  const [submitted, setSubmitted] = useState("RELIANCE");
  const { data, isLoading } = useSWR<any>(submitted ? `/api/advanced/mtf/${submitted}` : null,
    fetcher);

  return (
    <Panel title="Multi-Timeframe Agreement (Daily / Weekly / Monthly)">
      <form onSubmit={(e) => { e.preventDefault(); setSubmitted(symbol.toUpperCase()); }}
        className="flex gap-2 items-center mb-3">
        <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          className="flex-1 max-w-xs bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono"
          placeholder="Symbol" />
        <button type="submit" className="px-3 py-1.5 bg-accent-amber text-black rounded text-sm font-semibold">
          Analyze
        </button>
        <div className="text-[10px] text-text-muted">
          ALL 3 aligned = institutional-grade · 2/3 aligned = actionable · diverge = wait
        </div>
      </form>

      {isLoading && <div className="text-text-muted text-xs">Analyzing…</div>}

      {data && (
        <>
          <div className="grid grid-cols-4 gap-3 mb-3">
            <Stat label="Direction" value={data.direction}
              color={biasColor(data.direction)} />
            <Stat label="Agreement" value={data.agreement_grade.replace(/_/g, " ")}
              color={data.agreement_count === 3 ? "text-accent-green glow-amber"
                : data.agreement_count === 2 ? "text-accent-amber" : "text-accent-red"} />
            <Stat label="Aligned timeframes" value={`${data.agreement_count}/3`} color="text-accent-amber" />
            <Stat label="MTF confidence" value={fmt.num(data.confidence, 1)} color="text-accent-amber" />
          </div>

          <div className="grid grid-cols-3 gap-3">
            {["daily", "weekly", "monthly"].map((tf) => {
              const t = data.timeframes[tf];
              return (
                <div key={tf} className={`border rounded p-2 ${biasColor(t.bias).includes("green")
                  ? "border-accent-green/40" : biasColor(t.bias).includes("red")
                  ? "border-accent-red/40" : "border-bg-line"}`}>
                  <div className="text-[10px] uppercase text-text-muted mb-1">{t.timeframe}</div>
                  <div className={`text-lg font-bold ${biasColor(t.bias)}`}>{t.bias}</div>
                  <div className="text-[10px] text-text-secondary">Score {fmt.num(t.score, 1)} · RSI {fmt.num(t.rsi, 1)}</div>
                  <div className="text-[10px] text-text-muted mt-1">{t.ema_alignment}</div>
                  <div className="text-[10px] text-text-secondary mt-2">{t.note}</div>
                </div>
              );
            })}
          </div>

          <div className="text-[11px] text-text-secondary mt-3 border-t border-bg-line pt-2">
            {data.summary}
          </div>
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------

function SectorHeatmap() {
  const [run, setRun] = useState(false);
  const { data, isLoading } = useSWR<any>(run ? "/api/advanced/sectors/heatmap" : null, fetcher);

  return (
    <Panel title="Sector Rotation Heatmap"
      right={
        <button onClick={() => setRun(true)}
          className="px-3 py-1 bg-accent-amber text-black rounded text-[11px] font-semibold">
          {isLoading ? "Scanning…" : "Run Scan"}
        </button>
      }
    >
      {!run && (
        <div className="text-text-muted text-xs">
          Scans every constituent in 12 sectors and aggregates bull/bear counts.
          Useful for spotting money rotation (e.g. capital flowing out of IT into Banking).
          Takes ~60-90s.
        </div>
      )}

      {isLoading && <div className="text-accent-amber text-xs">Scanning all sectors in parallel… please wait</div>}

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
          {data.sectors.map((s: any) => {
            const intensity = Math.min(1, Math.abs(s.net_bias) / 8);
            const bg = s.net_bias > 0
              ? `rgba(0, 214, 143, ${0.05 + intensity * 0.25})`
              : s.net_bias < 0
              ? `rgba(255, 59, 105, ${0.05 + intensity * 0.25})`
              : "transparent";
            return (
              <div key={s.sector} className="border border-bg-line rounded p-2"
                   style={{ background: bg }}>
                <div className="flex items-baseline justify-between mb-1">
                  <span className="text-text-primary text-[12px] font-semibold truncate">{s.sector}</span>
                  <span className={clsx("font-bold tabular text-sm",
                    s.net_bias > 0 ? "text-accent-green" : s.net_bias < 0 ? "text-accent-red" : "text-text-secondary")}>
                    {s.net_bias > 0 ? "+" : ""}{s.net_bias}
                  </span>
                </div>
                <div className="text-[10px] text-text-secondary tabular">
                  <span className="text-accent-green">{s.bulls}↑</span>
                  <span className="text-text-muted"> · </span>
                  <span className="text-accent-red">{s.bears}↓</span>
                  <span className="text-text-muted"> · </span>
                  <span>{s.neutral} flat / {s.count} total</span>
                </div>
                <div className="text-[10px] text-accent-amber tabular mt-1">
                  avg conf {s.avg_confidence}
                </div>
                {s.top_3?.length > 0 && (
                  <div className="text-[10px] text-text-muted mt-1 border-t border-bg-line/40 pt-1">
                    Top: {s.top_3.map((t: any, i: number) =>
                      <span key={i} className={signalColor(t.signal)}>
                        {t.symbol}{i < s.top_3.length - 1 ? " · " : ""}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
