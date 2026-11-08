"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { fmt } from "@/lib/format";
import clsx from "clsx";

export default function RiskPage() {
  const { data, isLoading } = useSWR<any>("/api/risk/snapshot?capital=100000",
    fetcher, { refreshInterval: 5_000 });

  if (isLoading || !data) return <div className="text-text-secondary text-sm">Loading risk snapshot…</div>;

  const pnlColor = data.total_pnl_today >= 0 ? "text-accent-green" : "text-accent-red";
  const expColor = data.exposure_pct >= data.exposure_pct_limit ? "text-accent-red"
                   : data.exposure_pct >= data.exposure_pct_limit * 0.7 ? "text-accent-amber"
                   : "text-text-primary";

  return (
    <div className="space-y-4">
      {data.daily_loss_breached && (
        <div className="bg-accent-red/15 border border-accent-red rounded p-3 text-accent-red text-sm font-semibold">
          ⚠ DAILY LOSS LIMIT BREACHED — risk gate has blocked new entries.
        </div>
      )}

      <div className="grid grid-cols-6 gap-4">
        <Panel title="Capital">
          <Stat label="Account" value={`₹${fmt.inr(data.capital)}`} />
        </Panel>
        <Panel title="Exposure">
          <Stat
            label={`${fmt.num(data.exposure_pct, 1)}% / ${fmt.num(data.exposure_pct_limit, 1)}% max`}
            value={`₹${fmt.inr(data.exposure_inr)}`}
            color={expColor}
          />
        </Panel>
        <Panel title="Today's P&L">
          <Stat
            label={`${fmt.num(data.total_pnl_pct_today, 2)}% · ${data.trade_count_today} trades`}
            value={`₹${fmt.inr(data.total_pnl_today)}`}
            color={pnlColor}
          />
        </Panel>
        <Panel title="Unrealized">
          <Stat
            label="Open positions"
            value={`₹${fmt.inr(data.unrealized_pnl)}`}
            color={data.unrealized_pnl >= 0 ? "text-accent-green" : "text-accent-red"}
          />
        </Panel>
        <Panel title="Realized">
          <Stat
            label="Today (booked)"
            value={`₹${fmt.inr(data.realized_pnl_today)}`}
            color={data.realized_pnl_today >= 0 ? "text-accent-green" : "text-accent-red"}
          />
        </Panel>
        <Panel title="Daily Loss Headroom">
          <Stat
            label={`Limit ₹${fmt.inr(data.daily_loss_limit_inr)}`}
            value={`₹${fmt.inr(data.headroom_inr)}`}
            color={data.headroom_inr <= data.daily_loss_limit_inr * 0.3 ? "text-accent-red" : "text-accent-amber"}
          />
        </Panel>
      </div>

      <Panel title="Open Positions">
        {data.positions?.length === 0 ? (
          <div className="text-text-muted text-xs py-2">No open positions.</div>
        ) : (
          <table className="w-full text-[12px] tabular">
            <thead className="text-text-muted text-[10px] uppercase">
              <tr className="border-b border-bg-line">
                <th className="text-left py-2 px-2">Symbol</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Avg Price</th>
                <th className="text-right">LTP</th>
                <th className="text-right">Exposure</th>
                <th className="text-right">P&L</th>
                <th className="text-center">Mode</th>
              </tr>
            </thead>
            <tbody>
              {data.positions.map((p: any) => (
                <tr key={p.symbol} className="border-b border-bg-line/40">
                  <td className="py-1.5 px-2 text-text-primary font-semibold">{p.symbol}</td>
                  <td className={clsx("text-right tabular", p.qty >= 0 ? "text-accent-green" : "text-accent-red")}>
                    {p.qty}
                  </td>
                  <td className="text-right text-text-secondary">{fmt.num(p.avg)}</td>
                  <td className="text-right text-text-secondary">{fmt.num(p.ltp)}</td>
                  <td className="text-right text-text-primary">₹{fmt.inr(p.exposure)}</td>
                  <td className={clsx("text-right tabular", p.pnl >= 0 ? "text-accent-green" : "text-accent-red")}>
                    ₹{fmt.inr(p.pnl)}
                  </td>
                  <td className="text-center text-[10px]">
                    {p.paper ? <span className="text-accent-amber">PAPER</span> : <span className="text-accent-green">LIVE</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Risk Configuration">
        <div className="grid grid-cols-3 gap-4 text-[11px]">
          <Stat label="Max position size" value={`${data.max_position_pct}% of capital`} />
          <Stat label="Max daily loss" value={`${data.max_daily_loss_pct}% of capital`} />
          <Stat label="Max portfolio exposure" value={`${data.exposure_pct_limit}% of capital`} />
        </div>
        <div className="text-[10px] text-text-muted mt-3">
          Configure via <code>.env</code>: <code>RISK_MAX_POSITION_PCT</code>, <code>RISK_MAX_DAILY_LOSS_PCT</code>, <code>RISK_DEFAULT_RR</code>.
        </div>
      </Panel>
    </div>
  );
}
