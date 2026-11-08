"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { biasColor, fmt } from "@/lib/format";

export default function OptionsPage() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [spot, setSpot] = useState(22500);
  const url = `/api/options/synthetic/${symbol}?spot=${spot}`;
  const { data } = useSWR<any>(url, fetcher);

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Panel title="Options Chain Analyzer (Paper Mode — synthetic chain)">
          <div className="flex gap-3 items-end">
            <div>
              <div className="text-[10px] text-text-muted uppercase">Symbol</div>
              <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                     className="w-32 bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono" />
            </div>
            <div>
              <div className="text-[10px] text-text-muted uppercase">Spot</div>
              <input type="number" value={spot} onChange={(e) => setSpot(parseFloat(e.target.value) || 0)}
                     className="w-32 bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono tabular" />
            </div>
            <div className="text-[10px] text-text-muted">
              In live mode the chain will pull from broker.
            </div>
          </div>
        </Panel>
      </div>

      {data && (
        <>
          <div className="col-span-12 lg:col-span-4">
            <Panel title="Bias">
              <div className={`text-3xl font-bold ${biasColor(data.analysis.bias)}`}>
                {data.analysis.bias}
              </div>
              <div className="text-text-secondary text-xs mt-2">
                PCR: <span className="text-accent-amber tabular">{data.analysis.pcr}</span>
              </div>
              <div className="text-text-secondary text-xs">
                Max Pain: <span className="text-accent-amber tabular">{data.analysis.max_pain}</span>
              </div>
              <div className="text-text-secondary text-xs">
                Support wall: <span className="text-accent-green tabular">{data.analysis.support_wall}</span>
              </div>
              <div className="text-text-secondary text-xs">
                Resistance wall: <span className="text-accent-red tabular">{data.analysis.resistance_wall}</span>
              </div>
            </Panel>
          </div>

          <div className="col-span-12 lg:col-span-8">
            <Panel title="Strategy">
              <div className="text-accent-amber font-semibold">{data.analysis.suggested_strategy}</div>
              <div className="text-[11px] text-text-secondary mt-2">{data.analysis.institutional_view}</div>
              <div className="mt-3 grid grid-cols-2 gap-3 text-[11px]">
                <div>
                  <div className="text-text-muted uppercase">ATM Call Greeks</div>
                  <pre className="text-text-primary tabular text-[10px]">{JSON.stringify(data.analysis.greeks_atm.call, null, 2)}</pre>
                </div>
                <div>
                  <div className="text-text-muted uppercase">ATM Put Greeks</div>
                  <pre className="text-text-primary tabular text-[10px]">{JSON.stringify(data.analysis.greeks_atm.put, null, 2)}</pre>
                </div>
              </div>
            </Panel>
          </div>

          <div className="col-span-12">
            <Panel title="Synthetic Options Chain">
              <table className="w-full text-[11px] tabular">
                <thead className="text-text-muted text-[10px] uppercase">
                  <tr className="border-b border-bg-line">
                    <th className="text-right">CE OI</th>
                    <th className="text-right">CE LTP</th>
                    <th className="text-right">CE IV</th>
                    <th className="text-center">Strike</th>
                    <th className="text-right">PE IV</th>
                    <th className="text-right">PE LTP</th>
                    <th className="text-right">PE OI</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.chain || []).map((row: any, i: number) => (
                    <tr key={i} className={`border-b border-bg-line/40 ${row.strike === Math.round(spot/50)*50 ? "bg-bg-panel" : ""}`}>
                      <td className="text-right text-accent-green">{fmt.inr(row.ce_oi)}</td>
                      <td className="text-right text-text-primary">{fmt.num(row.ce_ltp)}</td>
                      <td className="text-right text-text-secondary">{fmt.num(row.ce_iv, 1)}</td>
                      <td className="text-center text-accent-amber font-semibold">{row.strike}</td>
                      <td className="text-right text-text-secondary">{fmt.num(row.pe_iv, 1)}</td>
                      <td className="text-right text-text-primary">{fmt.num(row.pe_ltp)}</td>
                      <td className="text-right text-accent-red">{fmt.inr(row.pe_oi)}</td>
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
