"use client";

import { fmt, signalColor, biasColor } from "@/lib/format";
import { EngineBar } from "./EngineBar";

export function SignalCard({ s }: { s: any }) {
  if (s.error) {
    return (
      <div className="border border-bg-line rounded p-3 bg-bg-panel">
        <div className="text-text-secondary">{s.symbol}</div>
        <div className="text-accent-red text-xs">{s.error}</div>
      </div>
    );
  }
  const eng = s.engines || {};
  return (
    <div className="border border-bg-line rounded bg-panel-grad overflow-hidden">
      <div className="px-3 py-2 border-b border-bg-line flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-text-primary font-semibold">{s.symbol}</span>
          <span className={`text-[10px] px-1.5 py-0.5 rounded border border-bg-line ${biasColor(s.trend)}`}>
            {s.trend}
          </span>
        </div>
        <div className={`font-bold text-sm tracking-wider ${signalColor(s.signal)}`}>
          {s.signal}
        </div>
      </div>

      <div className="p-3 grid grid-cols-4 gap-2 text-[11px]">
        <div>
          <div className="text-text-muted uppercase tracking-wider">Confidence</div>
          <div className="text-accent-amber tabular font-semibold">{fmt.num(s.confidence, 1)}%</div>
        </div>
        <div>
          <div className="text-text-muted uppercase tracking-wider">Entry</div>
          <div className="tabular text-text-primary">{fmt.inr(s.entry)}</div>
        </div>
        <div>
          <div className="text-text-muted uppercase tracking-wider">Stoploss</div>
          <div className="tabular text-accent-red">{fmt.inr(s.stoploss)}</div>
        </div>
        <div>
          <div className="text-text-muted uppercase tracking-wider">R:R</div>
          <div className="tabular text-text-primary">{fmt.num(s.risk_reward, 2)}</div>
        </div>
        <div className="col-span-4">
          <div className="text-text-muted uppercase tracking-wider">Targets</div>
          <div className="flex gap-3 tabular">
            {(s.targets || []).map((t: number, i: number) => (
              <span key={i} className="text-accent-green">T{i + 1}: {fmt.inr(t)}</span>
            ))}
          </div>
        </div>
      </div>

      <div className="px-3 pb-3 space-y-1.5">
        <EngineBar label="Technical"  score={eng.technical?.score ?? 0}  bias={eng.technical?.bias ?? "NEUTRAL"} />
        <EngineBar label="SMC/ICT"    score={eng.smc?.score ?? 0}        bias={eng.smc?.bias ?? "NEUTRAL"} />
        <EngineBar label="Options"    score={eng.options?.score ?? 0}    bias={eng.options?.bias ?? "NEUTRAL"} />
        <EngineBar label="Astrology"  score={eng.astrology?.score ?? 0}  bias={eng.astrology?.bias ?? "NEUTRAL"} />
        <EngineBar label="Gann"       score={eng.gann?.score ?? 0}       bias={eng.gann?.bias ?? "NEUTRAL"} />
        <EngineBar label="Numerology" score={eng.numerology?.score ?? 0} bias={eng.numerology?.bias ?? "NEUTRAL"} />
      </div>

      {s.reasons && (
        <div className="px-3 pb-3 text-[10px] text-text-secondary space-y-0.5">
          {Object.entries(s.reasons).slice(0, 4).map(([k, v]) => (
            <div key={k}>
              <span className="text-text-muted uppercase">{k}:</span> {v as string}
            </div>
          ))}
        </div>
      )}

      <div className="px-3 py-1.5 border-t border-bg-line text-[9px] text-text-muted">
        Suggested allocation: {fmt.num(s.capital_allocation_pct, 2)}% of capital
      </div>
    </div>
  );
}
