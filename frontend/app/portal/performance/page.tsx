"use client";

/**
 * Performance dashboard — wired DIRECTLY to signals_journal via the
 * /api/journal/performance-summary endpoint. Zero hardcoded KPIs.
 *
 * Critical behavior: when the journal has fewer than 30 evaluated signals,
 * the page REFUSES to display KPIs. Instead it shows a "track record
 * forming" state. This prevents the platform from ever displaying
 * statistically-unsupported numbers like "87.5% win rate."
 */

import useSWR from "swr";
import { useState } from "react";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine,
} from "recharts";
import Link from "next/link";
import {
  Activity, TrendingUp, AlertTriangle, CheckCircle2, Info, Clock,
  Target, Award, ShieldCheck, BarChart3, TrendingDown, Hash, ArrowRight,
} from "lucide-react";
import clsx from "clsx";


export default function PerformancePage() {
  const [days, setDays] = useState(90);
  const [horizon, setHorizon] = useState<"" | "INTRADAY" | "SWING" | "POSITIONAL">("");

  const url = `/api/journal/performance-summary?days=${days}` +
    (horizon ? `&horizon=${horizon}` : "");
  const { data, error, isLoading } = useSWR<any>(url, fetcher,
    { refreshInterval: 60_000, shouldRetryOnError: false });

  if (error instanceof ApiError && error.status === 402) {
    return (
      <div className="space-y-4">
        <PageHeader />
        <UpgradeRequired error={error} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex bg-bg-base rounded p-0.5">
          {[30, 60, 90, 180].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={clsx("text-[11px] px-3 py-1 rounded font-semibold",
                days === d ? "bg-accent-amber text-white"
                            : "text-text-secondary hover:text-text-primary")}>
              {d}d
            </button>
          ))}
        </div>
        <div className="flex bg-bg-base rounded p-0.5">
          {["", "INTRADAY", "SWING", "POSITIONAL"].map((h) => (
            <button key={h || "ALL"} onClick={() => setHorizon(h as any)}
              className={clsx("text-[11px] px-3 py-1 rounded font-semibold",
                horizon === h ? "bg-accent-amber text-white"
                              : "text-text-secondary hover:text-text-primary")}>
              {h || "ALL"}
            </button>
          ))}
        </div>
        {data?.evaluated_count != null && (
          <span className="text-[11px] text-text-muted">
            {data.evaluated_count} evaluated signals
          </span>
        )}
      </div>

      {isLoading && !data && (
        <div className="text-text-muted text-center py-12">Loading performance data…</div>
      )}

      {/* Track record forming state */}
      {data && data.evaluated_count < (data.min_required ?? 30) && (
        <TrackRecordForming
          evaluated={data.evaluated_count}
          required={data.min_required}
          message={data.message}
        />
      )}

      {/* Real KPIs — only if journal has enough data */}
      {data?.kpis && (
        <>
          <KpiGrid kpis={data.kpis} />

          {/* Reliability curve */}
          {data.reliability_curve?.length > 0 && (
            <ReliabilityPanel curve={data.reliability_curve} />
          )}

          {/* Monthly performance */}
          {data.monthly?.length > 0 && (
            <MonthlyPanel monthly={data.monthly} />
          )}

          {/* By-horizon breakdown */}
          {data.by_horizon && Object.keys(data.by_horizon).length > 0 && (
            <HorizonBreakdown by={data.by_horizon} />
          )}

          {/* What these metrics mean — plain-English glossary so users aren't
              left guessing what "Brier score" or "edge vs baseline" mean */}
          <MethodologyPanel />
        </>
      )}
    </div>
  );
}


function MethodologyPanel() {
  const items: { icon: any; title: string; body: string }[] = [
    {
      icon: Hash,
      title: "Evaluated signals",
      body: "Signals that have hit their target, stop, or expired — i.e. the outcome is known. We only count these. Open positions don't move the KPIs.",
    },
    {
      icon: Target,
      title: "Hit rate",
      body: "Share of evaluated signals that closed profitably. Compared against the baseline a coin-flip would produce — anything below the baseline means no edge.",
    },
    {
      icon: TrendingUp,
      title: "Edge vs baseline",
      body: "Percentage-points above what a random direction guess would have produced. >+2pp = real edge; near zero = no edge; negative = worse than chance.",
    },
    {
      icon: ShieldCheck,
      title: "Brier score",
      body: "Calibration measure: lower is better. Tells us whether \"70% confidence\" signals actually win 70% of the time. Calibrated < 0.20 is honest.",
    },
    {
      icon: Award,
      title: "Avg MFE / MAE",
      body: "Maximum Favorable / Adverse Excursion — the best and worst unrealised P&L the trade saw before closing. MFE >> MAE means our targets cap winners too tight.",
    },
    {
      icon: BarChart3,
      title: "Reliability curve",
      body: "Plots claimed confidence against actual win rate. Hugging the diagonal = honest. Bowing above = under-confident; bowing below = over-confident.",
    },
  ];
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <div className="flex items-center gap-2 mb-3">
        <Info className="w-4 h-4 text-accent-amber" />
        <h2 className="text-sm font-bold text-text-primary">How to read these numbers</h2>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((it) => {
          const Icon = it.icon;
          return (
            <div key={it.title}
                  className="border-l-2 border-l-accent-amber/40 bg-bg-base/40 rounded-r px-3 py-2">
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className="w-3.5 h-3.5 text-accent-amber" />
                <div className="text-[12px] font-bold text-text-primary">{it.title}</div>
              </div>
              <div className="text-[11px] text-text-secondary leading-snug">{it.body}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function PageHeader() {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
            <Activity className="w-5 h-5 text-accent-amber" />
            Track Record
          </h1>
          <p className="text-[11px] text-text-muted mt-1">
            All metrics computed from the live signals journal. No marketing numbers,
            no aspirational targets — only what has actually happened to past signals.
          </p>
        </div>
        <Link href="/portal/performance/engines"
              className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-accent-amber hover:text-accent-gold border border-accent-amber/40 rounded px-3 py-1.5 hover:bg-accent-amber/5">
          Per-engine attribution
          <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}


function TrackRecordForming({ evaluated, required, message }:
                              { evaluated: number; required: number; message?: string }) {
  return (
    <div className="bg-bg-surface border border-accent-amber/30 rounded-lg p-8 text-center">
      <Clock className="w-10 h-10 text-accent-amber mx-auto mb-3" />
      <h2 className="text-lg font-bold text-text-primary mb-2">
        Track record forming
      </h2>
      <div className="text-[12px] text-text-secondary max-w-md mx-auto mb-4">
        {message || (
          <>Only {evaluated} closed-and-evaluated signals so far. We need ≥{required}
          to compute meaningful KPIs without misleading anyone.</>
        )}
      </div>
      <div className="inline-flex items-center gap-2 text-[10px] text-text-muted">
        <div className="w-32 h-2 bg-bg-base rounded overflow-hidden">
          <div className="h-full bg-accent-amber"
                style={{ width: `${Math.min(100, evaluated / required * 100)}%` }} />
        </div>
        {evaluated} / {required}
      </div>
    </div>
  );
}


function KpiGrid({ kpis }: { kpis: any }) {
  // Edge color — positive = green, near-zero = neutral, negative = red
  const edgeColor =
    kpis.edge_pp > 2.0 ? "text-accent-green" :
    kpis.edge_pp > 0.5 ? "text-accent-amber" :
    kpis.edge_pp > -0.5 ? "text-text-secondary" : "text-accent-red";

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Kpi icon={Hash} label="Evaluated signals"
            value={kpis.evaluated.toLocaleString()}
            sub="closed + outcome known" />
      <Kpi icon={Target} label="Hit rate"
            value={`${(kpis.hit_rate * 100).toFixed(1)}%`}
            sub={`baseline ${(kpis.baseline_hit_rate * 100).toFixed(0)}%`}
            color={kpis.hit_rate > 0.54 ? "text-accent-green" :
                    kpis.hit_rate > 0.50 ? "text-accent-amber" : "text-accent-red"} />
      <Kpi icon={TrendingUp} label="Edge vs baseline"
            value={`${kpis.edge_pp > 0 ? "+" : ""}${kpis.edge_pp.toFixed(1)}pp`}
            sub={kpis.edge_pp > 2 ? "real edge" : kpis.edge_pp > 0 ? "marginal" : "no edge"}
            color={edgeColor} />
      <Kpi icon={ShieldCheck} label="Brier score"
            value={kpis.brier_score.toFixed(3)}
            sub={kpis.is_calibrated ? "calibrated" : "miscalibrated"}
            color={kpis.is_calibrated ? "text-accent-green" : "text-accent-amber"} />
      {kpis.avg_mfe_pct != null && (
        <Kpi icon={Award} label="Avg MFE"
              value={`${kpis.avg_mfe_pct > 0 ? "+" : ""}${kpis.avg_mfe_pct.toFixed(2)}%`}
              sub="best in-trade move"
              color="text-accent-green" />
      )}
      {kpis.avg_mae_pct != null && (
        <Kpi icon={TrendingDown} label="Avg MAE"
              value={`${kpis.avg_mae_pct.toFixed(2)}%`}
              sub="worst in-trade move"
              color="text-accent-red" />
      )}
    </div>
  );
}


function Kpi({ icon: Icon, label, value, sub, color }:
              { icon?: any; label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-3 flex gap-3">
      {Icon && (
        <div className="shrink-0 w-9 h-9 rounded bg-accent-amber/10 border border-accent-amber/20 flex items-center justify-center">
          <Icon className="w-4 h-4 text-accent-amber" />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="text-[9px] uppercase text-text-muted tracking-wider font-semibold">
          {label}
        </div>
        <div className={clsx("text-xl font-bold tabular mt-0.5 truncate", color || "text-text-primary")}>
          {value}
        </div>
        {sub && <div className="text-[10px] text-text-muted truncate">{sub}</div>}
      </div>
    </div>
  );
}


function ReliabilityPanel({ curve }: { curve: any[] }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-bold text-text-primary">
          Reliability — claimed vs actual win rate
        </h2>
        <span className="text-[10px] text-text-muted italic">
          diagonal = perfect calibration
        </span>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={curve}
          margin={{ top: 5, right: 20, bottom: 25, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
          <XAxis dataKey="claimed_bucket"
                  tick={{ fontSize: 10 }}
                  label={{ value: "Claimed confidence %", position: "insideBottom",
                            offset: -15, style: { fontSize: 10 } }} />
          <YAxis tick={{ fontSize: 10 }} domain={[0, 100]}
                  label={{ value: "Actual win %", angle: -90, position: "insideLeft",
                            style: { fontSize: 10 } }} />
          <Tooltip contentStyle={{ background: "var(--bg-surface)",
                                     border: "1px solid var(--bg-line)",
                                     fontSize: 11 }} />
          {/* Perfect-calibration reference */}
          <Line type="linear" data={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
                 dataKey="y" stroke="#666" strokeDasharray="3 3" dot={false}
                 isAnimationActive={false} />
          {/* Actual data */}
          <Line type="monotone" dataKey="actual_pct" stroke="#f59e0b"
                 strokeWidth={2} dot={{ fill: "#f59e0b", r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-text-muted italic mt-2">
        Reading the chart: if at "70% confidence" the line is at 55%, the system is
        over-confident at that level. If above 70%, under-confident. Hugging the
        diagonal means scores are honest.
      </p>
    </div>
  );
}


function MonthlyPanel({ monthly }: { monthly: any[] }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <h2 className="text-sm font-bold text-text-primary mb-3">Monthly</h2>
      <table className="w-full text-[11px]">
        <thead className="text-text-muted">
          <tr className="border-b border-bg-line">
            <th className="text-left py-1">Month</th>
            <th className="text-right">Signals</th>
            <th className="text-right">Wins</th>
            <th className="text-right">Win rate</th>
          </tr>
        </thead>
        <tbody>
          {monthly.map((m: any) => (
            <tr key={m.month} className="border-b border-bg-line/40">
              <td className="py-1 font-semibold">{m.month}</td>
              <td className="text-right tabular">{m.n}</td>
              <td className="text-right tabular">{m.wins}</td>
              <td className={clsx("text-right tabular font-bold",
                m.win_rate > 54 ? "text-accent-green" :
                m.win_rate > 50 ? "text-accent-amber" : "text-accent-red")}>
                {m.win_rate}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function HorizonBreakdown({ by }: { by: Record<string, any> }) {
  const entries = Object.entries(by);
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <h2 className="text-sm font-bold text-text-primary mb-3">By horizon</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {entries.map(([h, v]: [string, any]) => (
          <div key={h} className="border border-bg-line rounded p-2.5">
            <div className="text-[10px] uppercase text-text-muted tracking-wider">{h}</div>
            <div className={clsx("text-lg font-bold tabular mt-1",
              v.win_rate > 54 ? "text-accent-green" :
              v.win_rate > 50 ? "text-accent-amber" : "text-accent-red")}>
              {v.win_rate}%
            </div>
            <div className="text-[10px] text-text-muted">
              {v.wins} wins / {v.n} signals
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
