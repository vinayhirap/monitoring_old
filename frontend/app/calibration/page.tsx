"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { ErrorState, EmptyState, InfoBanner, LoadingSkeleton } from "@/components/States";
import {
  LineChart, Line, ScatterChart, Scatter, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, ReferenceLine, Legend,
} from "recharts";
import {
  TrendingUp, AlertTriangle, CheckCircle2, Target, Activity,
  Gauge, BarChart3, RefreshCw,
} from "lucide-react";
import clsx from "clsx";


export default function CalibrationPage() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [submitted, setSubmitted] = useState("NIFTY");
  const [quick, setQuick] = useState(true);

  const url = quick
    ? `/api/calibration/quick/${submitted}`
    : `/api/calibration/${submitted}?lookback_bars=150`;
  const { data, isLoading, error, mutate } = useSWR<any>(url, fetcher, {
    revalidateOnFocus: false,
    refreshInterval: 0,
  });

  function run() {
    setSubmitted(symbol.toUpperCase().trim());
    mutate();
  }

  // Diagonal reference line — perfect calibration y=x
  const diagonal = Array.from({ length: 11 }, (_, i) => ({
    predicted: i / 10,
    realized: i / 10,
  }));

  return (
    <div className="space-y-4">
      {/* Top bar */}
      <Panel title="Calibration Self-Check"
        right={
          <span className="text-[10px] text-text-muted">
            Walk-forward backtest of the forecast engine vs realized outcomes
          </span>
        }>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[200px]">
            <label className="text-[10px] uppercase text-text-muted tracking-wider block mb-1">
              Symbol
            </label>
            <div className="flex gap-2">
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && run()}
                placeholder="NIFTY / RELIANCE / TCS"
                className="flex-1 px-3 py-1.5 text-sm rounded border border-bg-line bg-bg-surface focus:border-accent-amber"
              />
              <button onClick={run} disabled={isLoading}
                className="bg-accent-amber text-white px-4 py-1.5 text-sm font-bold rounded hover:bg-accent-gold disabled:opacity-50 flex items-center gap-1.5">
                <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
                {isLoading ? "running…" : "Run"}
              </button>
            </div>
          </div>
          <div>
            <label className="text-[10px] uppercase text-text-muted tracking-wider block mb-1">
              Mode
            </label>
            <button onClick={() => setQuick(!quick)}
              className={clsx("text-[11px] px-3 py-1.5 rounded border font-bold",
                quick ? "border-accent-green/40 text-accent-green bg-accent-green/5"
                       : "border-accent-amber/40 text-accent-amber bg-accent-amber/5")}>
              {quick ? "QUICK (~10s)" : "FULL (~60-90s)"}
            </button>
          </div>
        </div>
        <div className="text-[10px] text-text-muted mt-3 border-t border-bg-line pt-2">
          Calibration replays the forecast engine on each historical bar (with no look-ahead),
          then compares the predicted confidence against what actually happened the next bar.
          A perfectly calibrated system has its calibration curve on the diagonal — when it
          says 65%, the market closes in predicted direction 65% of the time.
        </div>
      </Panel>

      {error && (
        <ErrorState
          title="Calibration failed"
          message={String(error.message)}
          hint="Calibration replays the engine on historical bars. If the cache is empty, run the backfill first: POST /api/backfill/run?quick=true&days_back=365"
          onRetry={() => mutate()}
        />
      )}

      {isLoading && !data && (
        <>
          <InfoBanner>
            Replaying the forecast engine on {submitted}'s historical bars
            (≈{quick ? "10s" : "60–90s"}). The lightweight path uses Technical
            + Gann + Fibonacci only — astrology is held constant for speed.
          </InfoBanner>
          <LoadingSkeleton lines={5} height="h-16" />
        </>
      )}

      {data && data.n_predictions === 0 && (
        <EmptyState
          title="No predictions to evaluate"
          message={(data.interpretation?.[0]) ||
            "The engine couldn't generate predictions from this bar window. Most common cause: no historical OHLCV in the cache. Run the backfill first."}
          action={{
            label: "Open backfill instructions",
            onClick: () => window.open("/methodology", "_self"),
          }}
        />
      )}

      {data && data.n_predictions > 0 && (
        <>
          {/* Headline rating */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <RatingCard rating={data.rating} avgOver={data.avg_overconfidence_pp} />
            <Stat label="Predictions tested" value={data.n_predictions} color="text-accent-amber" />
            <Stat label="Overall accuracy" value={`${(data.overall_accuracy * 100).toFixed(1)}%`}
                  color={data.overall_accuracy >= 0.55 ? "text-accent-green"
                         : data.overall_accuracy >= 0.50 ? "text-accent-amber"
                         : "text-accent-red"} />
            <Stat label="Brier score" value={data.brier_score.toFixed(4)}
                  color={data.brier_score < 0.22 ? "text-accent-green"
                         : data.brier_score < 0.245 ? "text-accent-amber"
                         : "text-accent-red"} />
          </div>

          {/* Calibration curve */}
          <Panel title="Calibration Curve — Predicted vs Realized"
            right={<span className="text-[10px] text-text-muted">
              {data.is_calibrated
                ? <><CheckCircle2 className="w-3 h-3 inline mr-1 text-accent-green" /> calibrated</>
                : <><AlertTriangle className="w-3 h-3 inline mr-1 text-accent-amber" /> miscalibrated</>}
            </span>}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                  <XAxis type="number" dataKey="predicted" domain={[0.5, 1]}
                          stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }}
                          label={{ value: "Predicted probability", fill: "#475569",
                                    position: "insideBottom", offset: -5, fontSize: 11 }} />
                  <YAxis type="number" dataKey="realized" domain={[0, 1]}
                          stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }}
                          label={{ value: "Realized hit rate", fill: "#475569",
                                    angle: -90, position: "insideLeft", fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: "#ffffff", border: "1px solid #e2e8f0",
                                      fontSize: 11, color: "#0f172a",
                                      boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                    formatter={(v: any) => Number(v).toFixed(3)}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {/* Diagonal — perfect calibration */}
                  <Scatter name="Perfect calibration"
                            data={diagonal} line fill="#94a3b8"
                            lineType="fitting" shape="cross"
                            isAnimationActive={false} />
                  {/* Actual buckets */}
                  <Scatter name="Engine calibration"
                            data={data.buckets.map((b: any) => ({
                              predicted: b.expected_rate,
                              realized: b.realized_rate,
                              n: b.n_predictions,
                            }))}
                            fill="#d97706" shape="circle" />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
            <div className="text-[10px] text-text-muted mt-2">
              Orange dots above the grey diagonal = under-confident (system understates).<br />
              Orange dots below the grey diagonal = OVER-confident (the dangerous direction).<br />
              Dots on the diagonal = perfectly calibrated.
            </div>
          </Panel>

          {/* Per-bucket table */}
          <Panel title="Calibration Buckets">
            <table className="w-full text-[11px]">
              <thead className="text-text-muted">
                <tr>
                  <th className="text-left py-1.5">Predicted band</th>
                  <th className="text-right">n</th>
                  <th className="text-right">Expected</th>
                  <th className="text-right">Realized</th>
                  <th className="text-right">Gap</th>
                  <th className="text-right">Avg P&L (win)</th>
                  <th className="text-right">Avg P&L (loss)</th>
                  <th className="text-center">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.buckets.map((b: any) => {
                  const gapPct = b.calibration_gap * 100;
                  const status = Math.abs(gapPct) < 5 ? "OK"
                                  : gapPct > 0 ? "UNDER" : "OVER";
                  const statusColor = status === "OK" ? "text-accent-green"
                                       : status === "UNDER" ? "text-accent-blue"
                                       : "text-accent-red";
                  return (
                    <tr key={`${b.range_low}-${b.range_high}`} className="border-t border-bg-line">
                      <td className="py-1.5">
                        {(b.range_low * 100).toFixed(0)}-{(b.range_high * 100).toFixed(0)}%
                      </td>
                      <td className="text-right tabular">{b.n_predictions}</td>
                      <td className="text-right tabular">{(b.expected_rate * 100).toFixed(1)}%</td>
                      <td className="text-right tabular font-bold">
                        {(b.realized_rate * 100).toFixed(1)}%
                      </td>
                      <td className={clsx("text-right tabular font-bold",
                        Math.abs(gapPct) < 3 ? "text-accent-green"
                        : Math.abs(gapPct) < 7 ? "text-accent-amber"
                        : "text-accent-red")}>
                        {gapPct > 0 ? "+" : ""}{gapPct.toFixed(1)}pp
                      </td>
                      <td className="text-right tabular text-accent-green">
                        +{b.avg_pnl_pct_when_right?.toFixed(2)}%
                      </td>
                      <td className="text-right tabular text-accent-red">
                        −{b.avg_pnl_pct_when_wrong?.toFixed(2)}%
                      </td>
                      <td className={clsx("text-center font-bold uppercase text-[10px]", statusColor)}>
                        {status}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>

          {/* Action — correction multiplier */}
          {!data.is_calibrated && (
            <Panel title="Recommended correction">
              <div className="bg-accent-amber/5 border border-accent-amber/30 rounded p-3">
                <div className="text-[11px] mb-2">
                  <strong className="text-accent-amber">System is overconfident by ~{data.avg_overconfidence_pp.toFixed(1)}pp.</strong>
                </div>
                <div className="text-[11px] text-text-secondary mb-2">
                  Apply this multiplier to incoming confidence labels:
                </div>
                <div className="flex items-baseline gap-3">
                  <span className="text-3xl font-bold text-accent-amber tabular">
                    × {data.suggested_confidence_multiplier.toFixed(2)}
                  </span>
                  <span className="text-[11px] text-text-muted">
                    e.g. a "65%" label becomes "{(50 + (65 - 50) * data.suggested_confidence_multiplier).toFixed(0)}%" for sizing decisions
                  </span>
                </div>
                <div className="text-[10px] text-text-muted mt-3">
                  Translation: when you see a 65% recommendation today, treat it as a{" "}
                  <strong>{(50 + (65 - 50) * data.suggested_confidence_multiplier).toFixed(0)}% bet</strong> for position sizing.
                  Larger sizes are based on a confidence the system hasn't earned.
                </div>
              </div>
            </Panel>
          )}

          {/* Interpretation */}
          <Panel title="Interpretation">
            <ul className="space-y-1 text-[11px] text-text-secondary">
              {data.interpretation?.map((line: string, i: number) => (
                <li key={i} className={clsx(
                  line.startsWith("→") && "text-accent-amber font-semibold border-l-2 border-accent-amber/40 pl-2",
                  line.startsWith("  •") && "ml-3 text-text-muted text-[10px]"
                )}>
                  {line}
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}
    </div>
  );
}


// ─── Rating card with color ────────────────────────────────────────────

function RatingCard({ rating, avgOver }: { rating: string; avgOver: number }) {
  const cfg = {
    WELL_CALIBRATED: {
      color: "text-accent-green border-accent-green/40 bg-accent-green/5",
      icon: CheckCircle2,
      msg: "Labels are honest"
    },
    SLIGHTLY_OVERCONFIDENT: {
      color: "text-accent-amber border-accent-amber/40 bg-accent-amber/5",
      icon: Gauge,
      msg: "Slight overstatement"
    },
    OVERCONFIDENT: {
      color: "text-accent-amber border-accent-amber/40 bg-accent-amber/5",
      icon: AlertTriangle,
      msg: "Reduce sizing"
    },
    SEVERELY_OVERCONFIDENT: {
      color: "text-accent-red border-accent-red/40 bg-accent-red/5",
      icon: AlertTriangle,
      msg: "Do NOT trust labels"
    },
    INSUFFICIENT_DATA: {
      color: "text-text-muted border-bg-line bg-bg-base",
      icon: Activity,
      msg: "Run backfill first"
    },
  }[rating] || {
    color: "text-text-muted border-bg-line bg-bg-base",
    icon: Activity,
    msg: ""
  };
  const Icon = cfg.icon;
  return (
    <div className={clsx("border rounded p-3", cfg.color)}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider opacity-70">
        <Icon className="w-3 h-3" /> Calibration
      </div>
      <div className="text-lg font-bold mt-1 leading-tight">
        {rating.replace(/_/g, " ")}
      </div>
      <div className="text-[10px] mt-1">{cfg.msg}</div>
      {avgOver !== 0 && (
        <div className="text-[10px] tabular mt-1 opacity-80">
          avg over-confidence: {avgOver > 0 ? "+" : ""}{avgOver.toFixed(1)}pp
        </div>
      )}
    </div>
  );
}
