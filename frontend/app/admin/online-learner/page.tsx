"use client";

/**
 * Admin monitoring page for the online learner.
 *
 * Shows everything an operator needs to assess whether the model is
 * working: sample count, in-sample win rate, learned weights (per-engine),
 * warmup status, last-updated timestamp.
 *
 * Includes destructive controls (reset, tune lr/l2) — OWNER role only on
 * the backend.
 */

import { useState } from "react";
import useSWR from "swr";
import { authedFetcher as fetcher, authedFetch } from "@/lib/auth";
import {
  Sparkles, RefreshCw, AlertTriangle, RotateCcw, Sliders,
  TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import clsx from "clsx";


export default function AdminOnlineLearnerPage() {
  const url = "/api/admin/online-learner/status";
  const { data, isLoading, mutate } = useSWR<any>(url, fetcher,
    { refreshInterval: 30_000, shouldRetryOnError: false });

  const [lrInput, setLrInput]   = useState("");
  const [l2Input, setL2Input]   = useState("");
  const [busy, setBusy] = useState(false);

  async function doReset() {
    if (!confirm("Reset the AI model? All learned weights wiped. The model will re-warm from the next 30 evaluated signals. This is destructive — use only when engine schema changed or the model has diverged.")) return;
    setBusy(true);
    try {
      await authedFetch("/api/admin/online-learner/reset", { method: "POST" });
      mutate();
    } catch (e: any) {
      alert(`Reset failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function doTune() {
    if (!lrInput && !l2Input) {
      alert("Set at least one of LR / L2 before tuning.");
      return;
    }
    setBusy(true);
    try {
      const body: any = {};
      if (lrInput) body.lr = Number(lrInput);
      if (l2Input) body.l2 = Number(l2Input);
      await authedFetch("/api/admin/online-learner/tune", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setLrInput(""); setL2Input("");
      mutate();
    } catch (e: any) {
      alert(`Tune failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  }

  if (isLoading && !data) {
    return <div className="text-text-muted text-sm py-12 text-center">Loading model state…</div>;
  }

  if (!data) return null;

  const weightsEntries = Object.entries(data.weights || {}) as [string, number][];
  // Sort by absolute weight magnitude — biggest signals first
  weightsEntries.sort(([, a], [, b]) => Math.abs(b) - Math.abs(a));

  const maxAbs = weightsEntries.length > 0
    ? Math.max(...weightsEntries.map(([, w]) => Math.abs(w))) : 1;

  return (
    <div className="space-y-4 max-w-4xl">
      {/* Header */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-lg font-bold text-text-primary flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-accent-violet" />
              AI Meta-Learner — Online Logistic Regression
            </h1>
            <p className="text-[11px] text-text-muted mt-1">
              Pure-NumPy model that updates one SGD step per evaluated signal. State persisted at <code className="text-[10px]">{data.state_path}</code>.
            </p>
          </div>
          <button onClick={() => mutate()} disabled={isLoading}
            className="text-[11px] flex items-center gap-1 text-accent-amber hover:text-accent-gold disabled:opacity-50">
            <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
            refresh
          </button>
        </div>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Samples seen" value={String(data.n_samples_seen)}
              sub={data.ready ? "trained" : `${data.warmup_remaining} more to warmup`}
              color={data.ready ? "text-accent-green" : "text-accent-amber"} />
        <Kpi label="Wins observed" value={String(data.n_wins_seen)} />
        <Kpi label="In-sample win rate"
             value={`${(data.in_sample_win_rate * 100).toFixed(1)}%`}
             color={data.in_sample_win_rate > 0.54 ? "text-accent-green" :
                    data.in_sample_win_rate > 0.50 ? "text-accent-amber" : "text-accent-red"} />
        <Kpi label="Status"
             value={data.ready ? "TRAINED" : "WARMUP"}
             color={data.ready ? "text-accent-green" : "text-accent-amber"}
             sub={data.last_updated > 0
               ? `Last updated ${new Date(data.last_updated * 1000).toLocaleString("en-IN")}`
               : "never updated"} />
      </div>

      {/* Hyperparameters */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <h2 className="text-sm font-bold text-text-primary mb-3 flex items-center gap-2">
          <Sliders className="w-4 h-4 text-accent-amber" /> Hyperparameters
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
          <div>
            <div className="text-text-muted text-[10px] uppercase tracking-wider">Learning rate</div>
            <div className="text-base font-bold tabular text-text-primary">{data.lr}</div>
            <input type="number" step="0.01" min="0.001" max="1" placeholder="new LR"
              value={lrInput} onChange={(e) => setLrInput(e.target.value)}
              className="mt-1 w-full bg-bg-base border border-bg-line rounded px-2 py-1 text-[11px]" />
          </div>
          <div>
            <div className="text-text-muted text-[10px] uppercase tracking-wider">L2 regularisation</div>
            <div className="text-base font-bold tabular text-text-primary">{data.l2}</div>
            <input type="number" step="0.001" min="0" max="1" placeholder="new L2"
              value={l2Input} onChange={(e) => setL2Input(e.target.value)}
              className="mt-1 w-full bg-bg-base border border-bg-line rounded px-2 py-1 text-[11px]" />
          </div>
          <div>
            <div className="text-text-muted text-[10px] uppercase tracking-wider">Bias (intercept)</div>
            <div className="text-base font-bold tabular text-text-primary">{data.bias}</div>
          </div>
          <div className="flex items-end gap-2">
            <button onClick={doTune} disabled={busy}
              className="text-[11px] font-bold px-3 py-1.5 rounded bg-accent-amber text-white disabled:opacity-50">
              Apply tune
            </button>
            <button onClick={doReset} disabled={busy}
              className="text-[11px] font-bold px-3 py-1.5 rounded bg-accent-red text-white flex items-center gap-1 disabled:opacity-50"
              title="OWNER only — wipes the entire model state">
              <RotateCcw className="w-3 h-3" /> Reset
            </button>
          </div>
        </div>
      </div>

      {/* Weights visualisation */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
        <h2 className="text-sm font-bold text-text-primary mb-3 flex items-center gap-2">
          Feature weights
          <span className="text-[10px] font-normal text-text-muted">
            sorted by absolute magnitude · positive = predicts wins · negative = anti-predicts
          </span>
        </h2>
        <div className="space-y-1.5">
          {weightsEntries.map(([key, w]) => {
            const widthPct = (Math.abs(w) / maxAbs) * 100;
            const positive = w > 0;
            return (
              <div key={key} className="flex items-center gap-2 text-[11px]">
                <div className="w-44 text-text-secondary truncate">{key}</div>
                <div className="flex-1 relative h-4 bg-bg-base rounded overflow-hidden">
                  <div className={clsx("absolute top-0 h-full",
                      positive ? "left-1/2 bg-accent-green/70" : "right-1/2 bg-accent-red/70")}
                    style={{ width: `${widthPct / 2}%` }} />
                  <div className="absolute left-1/2 top-0 h-full w-px bg-bg-line" />
                </div>
                <div className={clsx("w-16 text-right tabular font-bold",
                  positive ? "text-accent-green" : w < 0 ? "text-accent-red" : "text-text-muted")}>
                  {w >= 0 ? "+" : ""}{w.toFixed(3)}
                </div>
              </div>
            );
          })}
        </div>
        <div className="text-[10px] text-text-muted italic mt-4 pt-3 border-t border-bg-line">
          How to read: positive weights mean that feature/engine has historically
          correlated with winning signals. Negative weights mean it has anti-predicted.
          Near-zero weights mean the feature is noise for this data set. After
          ≥100 samples these become meaningful diagnostic for retiring engines.
        </div>
      </div>

      {/* Doc footer */}
      <div className="text-[10px] text-text-muted italic px-2">
        Inference cost ~50µs · update cost ~10µs · zero external dependencies · no GPU · no API
      </div>
    </div>
  );
}


function Kpi({ label, value, sub, color }:
              { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-3">
      <div className="text-[9px] uppercase text-text-muted tracking-wider font-semibold">{label}</div>
      <div className={clsx("text-xl font-bold tabular mt-1", color || "text-text-primary")}>{value}</div>
      {sub && <div className="text-[10px] text-text-muted mt-0.5">{sub}</div>}
    </div>
  );
}
