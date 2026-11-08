"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { biasColor, fmt } from "@/lib/format";

export default function SymbolCyclesPage() {
  const [symbol, setSymbol] = useState("RELIANCE");
  const { data } = useSWR<any>(`/api/numerology/symbol/${symbol}`, fetcher);

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Panel title="What this page measures">
          <p className="text-[11px] text-text-secondary leading-relaxed">
            <span className="text-accent-amber">Calendar–symbol compatibility scoring</span>. Reduces the trading symbol
            and today's calendar date to single-digit numerological roots (Pythagorean + Chaldean systems) and scores
            their compatibility. This is a <em>secondary confluence layer</em> with low weight (6%) in the decision
            pipeline — it nudges, it doesn't decide. Useful for spotting days where a stock's symbol-root matches the
            day-root and historically retail flow concentrates on that symbol.
          </p>
        </Panel>
      </div>

      <div className="col-span-12">
        <Panel title="Symbol Lookup">
          <div className="flex gap-2">
            <input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              className="flex-1 max-w-xs bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono"
              placeholder="Stock symbol (e.g. RELIANCE)"
            />
          </div>
        </Panel>
      </div>

      {data && (
        <>
          <div className="col-span-12 lg:col-span-4">
            <Panel title={`${data.symbol} — Composite`}>
              <div className={`text-3xl font-bold ${biasColor(data.bias)}`}>
                {data.bias} {fmt.num(data.score, 1)}
              </div>
              <div className="text-text-secondary text-xs mt-1">
                Today compatibility: <span className="text-accent-amber">{fmt.num(data.compatibility_with_today, 0)}%</span>
              </div>
              <div className="text-text-secondary text-[11px] mt-3">
                Planetary ruler: <span className="text-accent-violet">{data.planetary_ruler}</span>
              </div>
              <div className="text-text-muted text-[11px] mt-1">{data.interpretation}</div>
            </Panel>
          </div>

          <div className="col-span-12 lg:col-span-4">
            <Panel title="Pythagorean System (A=1..Z=8)">
              <div className="space-y-1 text-[12px]">
                <div className="flex justify-between"><span className="text-text-muted">Compound</span><span className="text-text-primary tabular">{data.pythagorean.compound}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Root</span><span className="text-accent-amber tabular text-lg">{data.pythagorean.root}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Ruler</span><span className="text-accent-violet">{data.pythagorean.ruler}</span></div>
              </div>
              <div className="text-[11px] text-text-secondary mt-3 border-t border-bg-line pt-2">
                {data.pythagorean.interpretation}
              </div>
            </Panel>
          </div>

          <div className="col-span-12 lg:col-span-4">
            <Panel title="Chaldean System (no 9)">
              <div className="space-y-1 text-[12px]">
                <div className="flex justify-between"><span className="text-text-muted">Compound</span><span className="text-text-primary tabular">{data.chaldean.compound}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Root</span><span className="text-accent-amber tabular text-lg">{data.chaldean.root}</span></div>
                <div className="flex justify-between"><span className="text-text-muted">Ruler</span><span className="text-accent-violet">{data.chaldean.ruler}</span></div>
              </div>
              <div className="text-[11px] text-text-secondary mt-3 border-t border-bg-line pt-2">
                {data.chaldean.interpretation}
              </div>
            </Panel>
          </div>

          <div className="col-span-12">
            <Panel title="Scoring Breakdown">
              <ul className="text-[12px] text-text-secondary space-y-1 list-disc pl-4">
                {(data.reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
              <div className="mt-3 text-[10px] text-text-muted">
                Today's date root: <span className="text-accent-amber tabular">{data.today_date_number}</span>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
