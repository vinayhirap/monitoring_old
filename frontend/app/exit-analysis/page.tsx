"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt } from "@/lib/format";
import clsx from "clsx";

export default function ExitPage() {
  const [form, setForm] = useState({
    symbol: "RELIANCE",
    side: "LONG",
    entry_price: 2900,
    qty: 50,
    entry_date: new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10),
    current_stop: 2850,
    trail_atr_mult: 1.5,
    profit_target_atr_mult: 4.0,
    max_days: 30,
  });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string>("");

  async function run() {
    setBusy(true); setErr(""); setResult(null);
    try {
      const r = await fetch("/api/exit/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!r.ok) throw new Error(await r.text());
      setResult(await r.json());
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-12 lg:col-span-5">
        <Panel title="Position Details">
          <div className="grid grid-cols-2 gap-3 text-[11px]">
            {(["symbol","side","entry_price","qty","entry_date","current_stop","trail_atr_mult","profit_target_atr_mult","max_days"] as const).map((k) => (
              <div key={k}>
                <label className="text-[10px] uppercase text-text-muted">{k.replace(/_/g, " ")}</label>
                {k === "side" ? (
                  <select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value })}
                    className="w-full bg-bg-base border border-bg-line rounded px-2 py-1.5 font-mono">
                    <option>LONG</option><option>SHORT</option>
                  </select>
                ) : (
                  <input
                    type={typeof (form as any)[k] === "number" ? "number" : (k.includes("date") ? "date" : "text")}
                    value={(form as any)[k] ?? ""}
                    onChange={(e) => setForm({ ...form, [k]: typeof (form as any)[k] === "number" ? parseFloat(e.target.value) : e.target.value })}
                    className="w-full bg-bg-base border border-bg-line rounded px-2 py-1.5 font-mono tabular"
                  />
                )}
              </div>
            ))}
          </div>
          <button onClick={run} disabled={busy}
            className="mt-4 w-full py-2 bg-accent-amber text-black rounded font-semibold disabled:opacity-50">
            {busy ? "Analyzing…" : "Evaluate Exit"}
          </button>
          {err && <div className="text-accent-red text-[11px] mt-2">{err}</div>}
        </Panel>
      </div>

      <div className="col-span-12 lg:col-span-7">
        {!result && (
          <Panel title="Decision">
            <div className="text-text-muted text-xs">
              Enter a held position on the left and click "Evaluate Exit" to get a HOLD / TRAIL / PARTIAL / FULL-EXIT recommendation.
              The engine combines technical bias, SMC reversals, profit-in-ATR multiples, time decay, and astrology volatility heads-up.
            </div>
          </Panel>
        )}
        {result && (
          <>
            <Panel title={`Decision: ${result.action}`}>
              <div className="grid grid-cols-3 gap-4">
                <Stat
                  label="Action"
                  value={result.action.replace("_", " ")}
                  color={
                    result.action === "FULL_EXIT" ? "text-accent-red glow-amber"
                    : result.action === "PARTIAL_EXIT" ? "text-accent-amber"
                    : result.action === "TRAIL_STOP" ? "text-accent-blue"
                    : "text-accent-green"
                  }
                />
                <Stat
                  label="Urgency"
                  value={result.urgency}
                  color={result.urgency === "CRITICAL" || result.urgency === "HIGH" ? "text-accent-red" : "text-text-primary"}
                />
                <Stat
                  label="Confidence"
                  value={`${fmt.num(result.confidence, 1)}%`}
                  color="text-accent-amber"
                />
              </div>

              <div className="mt-4 grid grid-cols-2 gap-4 text-[11px]">
                <div>
                  <div className="text-text-muted uppercase">Suggested qty to exit</div>
                  <div className="text-text-primary text-lg tabular">{result.suggested_qty_to_exit} / {result.qty}</div>
                </div>
                <div>
                  <div className="text-text-muted uppercase">P&L</div>
                  <div className={clsx("text-lg tabular", result.pnl_abs >= 0 ? "text-accent-green" : "text-accent-red")}>
                    ₹{fmt.num(result.pnl_abs)}
                    <span className="text-xs ml-2">({fmt.num(result.pnl_pct, 2)}% · {fmt.num(result.pnl_in_atr, 2)}× ATR)</span>
                  </div>
                </div>
                {result.new_stop !== null && (
                  <div>
                    <div className="text-text-muted uppercase">New Stoploss</div>
                    <div className="text-accent-amber text-lg tabular">{fmt.inr(result.new_stop)}</div>
                  </div>
                )}
                {result.new_target !== null && (
                  <div>
                    <div className="text-text-muted uppercase">New Target</div>
                    <div className="text-accent-green text-lg tabular">{fmt.inr(result.new_target)}</div>
                  </div>
                )}
              </div>
            </Panel>

            <div className="mt-4">
              <Panel title="Why">
                <ul className="text-[11px] text-text-secondary space-y-1 list-disc pl-4">
                  {(result.reasons || []).map((r: string, i: number) => <li key={i}>{r}</li>)}
                </ul>
              </Panel>
            </div>

            <div className="mt-4">
              <Panel title="Sub-signals">
                <pre className="text-[10px] text-text-secondary overflow-auto">{JSON.stringify(result.sub_signals, null, 2)}</pre>
              </Panel>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
