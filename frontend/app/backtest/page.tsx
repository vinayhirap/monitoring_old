"use client";

import { useState } from "react";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt } from "@/lib/format";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import clsx from "clsx";

export default function BacktestPage() {
  const [symbol, setSymbol] = useState("RELIANCE");
  const [lookback, setLookback] = useState(180);
  const [threshold, setThreshold] = useState(65);
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>("");

  async function run() {
    setBusy(true); setErr(""); setData(null);
    try {
      const url = `/api/backtest/run/${symbol}?lookback_bars=${lookback}&confidence_threshold=${threshold}`;
      setData(await fetcher<any>(url));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12">
        <Panel title="Walk-Forward Backtest — Accuracy Report"
          right={<span className="text-[10px] text-text-muted">
            Honest hit-rate from re-running the engine bar-by-bar
          </span>}>
          <div className="flex flex-wrap gap-3 items-end">
            <div>
              <div className="text-[10px] uppercase text-text-muted">Symbol</div>
              <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                className="w-32 bg-bg-base border border-bg-line rounded px-2 py-1.5 font-mono" />
            </div>
            <div>
              <div className="text-[10px] uppercase text-text-muted">Lookback bars</div>
              <input type="number" value={lookback} onChange={(e) => setLookback(parseInt(e.target.value) || 0)}
                className="w-24 bg-bg-base border border-bg-line rounded px-2 py-1.5 font-mono tabular" />
            </div>
            <div>
              <div className="text-[10px] uppercase text-text-muted">Min confidence</div>
              <input type="number" value={threshold} onChange={(e) => setThreshold(parseInt(e.target.value) || 0)}
                className="w-24 bg-bg-base border border-bg-line rounded px-2 py-1.5 font-mono tabular" />
            </div>
            <button onClick={run} disabled={busy}
              className="px-4 py-1.5 bg-accent-amber text-black rounded text-sm font-semibold disabled:opacity-50">
              {busy ? "Running…" : "Run Backtest"}
            </button>
          </div>
          {err && <div className="text-accent-red text-[11px] mt-2">{err}</div>}
        </Panel>
      </div>

      {data && (
        <>
          {/* Stat strip */}
          <div className="col-span-12 grid grid-cols-6 gap-4">
            <Panel title="Trades">
              <Stat label="Total" value={data.total_trades}
                sub={`${data.wins}W / ${data.losses}L / ${data.timeouts}T`} />
            </Panel>
            <Panel title="Hit Rate">
              <Stat label="Decisive trades" value={`${fmt.num(data.hit_rate, 1)}%`}
                color={data.hit_rate >= 50 ? "text-accent-green" : "text-accent-red"} />
            </Panel>
            <Panel title="Profit Factor">
              <Stat label="Σwin / Σloss" value={fmt.num(data.profit_factor, 2)}
                color={data.profit_factor >= 1.5 ? "text-accent-green" : data.profit_factor >= 1 ? "text-accent-amber" : "text-accent-red"} />
            </Panel>
            <Panel title="Expectancy">
              <Stat label="Avg trade" value={`${fmt.num(data.expectancy_pct, 2)}%`}
                color={data.expectancy_pct >= 0 ? "text-accent-green" : "text-accent-red"} />
            </Panel>
            <Panel title="Total Return">
              <Stat label="Cumulative" value={`${fmt.num(data.total_return_pct, 1)}%`}
                color={data.total_return_pct >= 0 ? "text-accent-green" : "text-accent-red"} />
            </Panel>
            <Panel title="Max Drawdown">
              <Stat label="Peak-to-trough" value={`${fmt.num(data.max_drawdown_pct, 1)}%`}
                color="text-accent-red" />
            </Panel>
          </div>

          {/* Equity curve */}
          {data.equity_curve?.length > 0 && (
            <div className="col-span-12">
              <Panel title="Equity Curve (starting at 100)">
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data.equity_curve}>
                      <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                      <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }} />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }} />
                      <Tooltip
                        contentStyle={{ background: "#ffffff", border: "1px solid #e2e8f0",
                                          fontSize: 11, color: "#0f172a",
                                          boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                        labelStyle={{ color: "#475569" }}
                      />
                      <Line type="monotone" dataKey="equity" stroke="#d97706" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </Panel>
            </div>
          )}

          {/* Trade list */}
          <div className="col-span-12">
            <Panel title="Trade Log">
              <table className="w-full text-[11px] tabular">
                <thead className="text-text-muted text-[10px] uppercase">
                  <tr className="border-b border-bg-line">
                    <th className="text-left py-1.5 px-1">Entry Date</th>
                    <th className="text-left">Exit Date</th>
                    <th className="text-center">Side</th>
                    <th className="text-right">Entry</th>
                    <th className="text-right">Exit</th>
                    <th className="text-right">Bars</th>
                    <th className="text-right">P&L %</th>
                    <th className="text-center">Outcome</th>
                    <th className="text-right">Conf @ entry</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.trades || []).map((t: any, i: number) => (
                    <tr key={i} className="border-b border-bg-line/40 hover:bg-bg-panel">
                      <td className="py-1 px-1">{t.entry_date}</td>
                      <td>{t.exit_date}</td>
                      <td className="text-center">{t.direction}</td>
                      <td className="text-right">{fmt.num(t.entry)}</td>
                      <td className="text-right">{fmt.num(t.exit)}</td>
                      <td className="text-right">{t.bars_held}</td>
                      <td className={clsx("text-right tabular", t.pnl_pct >= 0 ? "text-accent-green" : "text-accent-red")}>
                        {fmt.num(t.pnl_pct, 2)}
                      </td>
                      <td className={clsx("text-center text-[10px] font-bold",
                        t.outcome === "WIN" ? "text-accent-green"
                        : t.outcome === "LOSS" ? "text-accent-red"
                        : "text-text-muted")}>
                        {t.outcome}
                      </td>
                      <td className="text-right text-text-secondary">{fmt.num(t.confidence_at_entry, 1)}</td>
                    </tr>
                  ))}
                  {(data.trades || []).length === 0 && (
                    <tr><td colSpan={9} className="py-4 text-center text-text-muted">
                      No trades qualified at confidence threshold {threshold}.
                    </td></tr>
                  )}
                </tbody>
              </table>
              {data.note && (
                <div className="text-[10px] text-text-muted mt-3 italic border-t border-bg-line pt-2">
                  Note: {data.note}
                </div>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
