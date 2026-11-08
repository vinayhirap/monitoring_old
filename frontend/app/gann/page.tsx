"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { fmt, biasColor } from "@/lib/format";

export default function GannPage() {
  const [price, setPrice] = useState(2950);
  const sq9Url = `/api/gann/score?price=${price}`;
  const { data: gann } = useSWR<any>(sq9Url, fetcher);

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Panel title="Gann Confluence">
          <div className="flex items-center gap-3">
            <label className="text-[11px] text-text-muted uppercase">Price</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(parseFloat(e.target.value) || 0)}
              className="w-40 bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono tabular"
            />
            <span className="text-[10px] text-text-muted">Anchor will default to ~8% below current.</span>
          </div>
        </Panel>
      </div>

      {gann && (
        <>
          <div className="col-span-12 lg:col-span-4">
            <Panel title="Score">
              <div className={`text-3xl font-bold ${biasColor(gann.bias)}`}>
                {gann.bias} {fmt.num(gann.score, 1)}
              </div>
              <div className="text-[11px] text-text-secondary mt-2">
                Nearest support: <span className="text-accent-green tabular">{fmt.num(gann.nearest_support)}</span>
                <span className="text-text-muted"> ({fmt.num(gann.distance_to_support_pct, 2)}% away)</span>
              </div>
              <div className="text-[11px] text-text-secondary">
                Nearest resistance: <span className="text-accent-red tabular">{fmt.num(gann.nearest_resistance)}</span>
                <span className="text-text-muted"> ({fmt.num(gann.distance_to_resistance_pct, 2)}% away)</span>
              </div>
            </Panel>
          </div>

          <div className="col-span-12 lg:col-span-8">
            <Panel title="Reasoning">
              <ul className="text-[12px] text-text-secondary space-y-1 list-disc pl-4">
                {(gann.reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}
              </ul>
            </Panel>
          </div>

          <div className="col-span-12">
            <Panel title="Upcoming Time Cycles">
              <table className="w-full text-[12px] tabular">
                <thead className="text-text-muted text-[10px] uppercase">
                  <tr className="border-b border-bg-line">
                    <th className="text-left py-2 px-2">Cycle (days)</th>
                    <th className="text-left">Projected Date</th>
                    <th className="text-left">Significance</th>
                  </tr>
                </thead>
                <tbody>
                  {(gann.upcoming_cycle_dates || []).map((c: any, i: number) => (
                    <tr key={i} className="border-b border-bg-line/40">
                      <td className="py-1.5 px-2 text-accent-amber tabular">{c.cycle_days}</td>
                      <td className="text-text-primary">{c.projected_date}</td>
                      <td className="text-text-secondary">{c.significance}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
