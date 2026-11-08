"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel } from "@/components/Panel";
import { fmt } from "@/lib/format";

export default function PortfolioPage() {
  const { data: pos } = useSWR<any>("/api/broker/positions", fetcher, { refreshInterval: 15_000 });
  const { data: hold } = useSWR<any>("/api/broker/holdings", fetcher, { refreshInterval: 60_000 });

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Panel title="Open Positions">
          <table className="w-full text-[12px] tabular">
            <thead className="text-text-muted text-[10px] uppercase">
              <tr className="border-b border-bg-line">
                <th className="text-left py-2 px-2">Symbol</th>
                <th className="text-left">Exch</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Avg Price</th>
                <th className="text-right">LTP</th>
                <th className="text-right">P&amp;L</th>
                <th className="text-center">Mode</th>
              </tr>
            </thead>
            <tbody>
              {(pos?.positions || []).map((p: any, i: number) => (
                <tr key={i} className="border-b border-bg-line/40">
                  <td className="py-1.5 px-2 text-text-primary font-semibold">{p.tradingsymbol}</td>
                  <td className="text-text-secondary">{p.exchange}</td>
                  <td className="text-right text-text-primary">{p.netqty}</td>
                  <td className="text-right text-text-secondary">{fmt.num(p.avgnetprice)}</td>
                  <td className="text-right text-text-secondary">{fmt.num(p.ltp)}</td>
                  <td className={`text-right tabular ${p.pnl >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                    {fmt.num(p.pnl)}
                  </td>
                  <td className="text-center text-[10px] text-accent-amber">
                    {p.paper ? "PAPER" : "LIVE"}
                  </td>
                </tr>
              ))}
              {(!pos?.positions?.length) && (
                <tr><td colSpan={7} className="text-text-muted py-3 text-center">No open positions</td></tr>
              )}
            </tbody>
          </table>
        </Panel>
      </div>

      <div className="col-span-12">
        <Panel title="Holdings">
          <pre className="text-[11px] text-text-secondary overflow-auto max-h-96">
            {JSON.stringify(hold?.holdings || [], null, 2)}
          </pre>
        </Panel>
      </div>
    </div>
  );
}
