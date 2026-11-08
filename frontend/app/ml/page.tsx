"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { ErrorState, InfoBanner } from "@/components/States";
import { fmt } from "@/lib/format";
import { Brain, Cpu, Network, AlertTriangle, CheckCircle2 } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import clsx from "clsx";

export default function MLPage() {
  const { data: status, mutate } = useSWR<any>("/api/ml/status", fetcher, { refreshInterval: 10_000 });
  const { data: cal } = useSWR<any>(status?.trained ? "/api/ml/calibration-curve" : null, fetcher);
  const { data: feat } = useSWR<any>(status?.trained ? "/api/ml/feature-importance" : null, fetcher);

  const [predSymbol, setPredSymbol] = useState("RELIANCE");
  const [pred, setPred] = useState<any>(null);
  const [predBusy, setPredBusy] = useState(false);

  const [training, setTraining] = useState(false);
  const [trainReport, setTrainReport] = useState<any>(null);
  const [trainErr, setTrainErr] = useState("");

  async function runPredict() {
    setPredBusy(true);
    setPred(null);
    try {
      const r = await fetcher<any>(`/api/ml/predict/${predSymbol}`);
      setPred(r);
    } catch (e: any) {
      setPred({ error: e.message });
    } finally {
      setPredBusy(false);
    }
  }

  async function runTraining() {
    setTraining(true);
    setTrainErr("");
    setTrainReport(null);
    try {
      const r = await fetch("/api/ml/train", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ history_bars: 400, horizon_bars: 5 }),
      });
      if (!r.ok) {
        // Parse the JSON error message from the backend if possible
        let detail = "";
        try {
          const j = await r.json();
          detail = j.detail || j.message || JSON.stringify(j);
        } catch {
          detail = await r.text();
        }
        throw new Error(detail);
      }
      const data = await r.json();
      setTrainReport(data);
      mutate();
    } catch (e: any) {
      setTrainErr(e.message);
    } finally {
      setTraining(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Architecture overview */}
      <Panel title="Model Architecture">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <ArchCard icon={Cpu} title="Gradient Boosting"
            desc="GradientBoostingClassifier (200 trees, depth 4, lr 0.05). Primary model — strongest on tabular financial data."
            color="text-accent-green" />
          <ArchCard icon={Network} title="Neural Network"
            desc="MLPClassifier — 2 hidden layers (64→32, ReLU, Adam optimizer). Captures non-linear feature interactions."
            color="text-accent-blue" />
          <ArchCard icon={Brain} title="Ensemble + Calibration"
            desc="Mean of both models' probabilities, each wrapped in CalibratedClassifierCV (isotonic regression). Output is a CALIBRATED probability."
            color="text-accent-amber" />
        </div>
      </Panel>

      {/* Status + training */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-7">
          <Panel title="Model Status"
            right={status?.trained
              ? <span className="text-accent-green text-[11px] flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> trained
                </span>
              : <span className="text-accent-amber text-[11px] flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3" /> not trained
                </span>}>
            {status?.meta && Object.keys(status.meta).length > 0 ? (
              <div className="grid grid-cols-2 gap-3 text-[11px]">
                <Stat label="Trained at" value={String(status.meta.trained_at || "—").slice(0, 19)} />
                <Stat label="Training samples" value={status.meta.n_samples || 0} />
                <Stat label="OOS Brier (lower=better)" value={fmt.num(status.meta.out_of_sample_brier, 4)}
                  color={status.meta.out_of_sample_brier < 0.22 ? "text-accent-green"
                          : status.meta.out_of_sample_brier < 0.245 ? "text-accent-amber" : "text-accent-red"} />
                <Stat label="OOS ROC-AUC (higher=better)" value={fmt.num(status.meta.out_of_sample_auc, 4)}
                  color={status.meta.out_of_sample_auc > 0.6 ? "text-accent-green" : "text-text-secondary"} />
                <Stat label="GBM Brier" value={fmt.num(status.meta.out_of_sample_brier_gbm, 4)} />
                <Stat label="MLP Brier" value={fmt.num(status.meta.out_of_sample_brier_mlp, 4)} />
                <Stat label="Positive class rate" value={fmt.pct((status.meta.positive_rate || 0) * 100, 1)} />
                <Stat label="Forward horizon" value={`${status.meta.horizon_bars} bars`} />
              </div>
            ) : (
              <div className="text-[11px] text-text-muted">
                No model trained yet. Click "Train Now" below — first training takes 2-5 min depending on
                CPU and number of symbols processed.
              </div>
            )}
          </Panel>
        </div>

        <div className="col-span-12 md:col-span-5">
          <Panel title="Train / Retrain">
            <p className="text-[11px] text-text-secondary leading-relaxed mb-3">
              Walk-forward training across the top-50 most liquid F&O names. Generates features from each
              historical bar's engine outputs, labels each by the forward 5-bar return, fits both models
              with 5-fold time-series cross-validation, calibrates with isotonic regression, then evaluates
              on a held-out 20% test fold. Models are <strong>only saved</strong> if out-of-sample Brier
              score ≤ 0.245 (better than baseline).
            </p>
            <button onClick={runTraining} disabled={training}
              className="w-full px-4 py-2 bg-accent-amber text-black rounded font-semibold disabled:opacity-50">
              {training ? "Training… (2–5 min)" : status?.trained ? "Retrain" : "Train Now"}
            </button>
            {trainErr && (
              <ErrorState
                title="Could not train"
                message={trainErr}
                onRetry={runTraining}
              />
            )}
            {trainReport && (
              <div className="mt-3 text-[11px]">
                <div className={trainReport.saved ? "text-accent-green" : "text-accent-red"}>
                  {trainReport.saved
                    ? `✓ Saved — OOS Brier ${trainReport.metrics?.out_of_sample_brier}`
                    : `✗ Rejected — ${trainReport.status}`}
                </div>
                {trainReport.advice && <div className="text-text-muted mt-1">{trainReport.advice}</div>}
              </div>
            )}
          </Panel>
        </div>
      </div>

      {/* Calibration curve */}
      {cal?.calibration?.length > 0 && (
        <Panel title="Calibration Curve — predicted vs realized probability (OOS)">
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={cal.calibration.map((c: any) => ({
                predicted: (c.pred_low + c.pred_high) / 2,
                realized:  c.realized_rate,
                n: c.n,
              }))}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                <XAxis dataKey="predicted" type="number" domain={[0, 1]}
                  label={{ value: "Predicted probability", fill: "#475569", position: "insideBottom", offset: -5, fontSize: 11 }}
                  stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }} />
                <YAxis type="number" domain={[0, 1]}
                  label={{ value: "Realized rate", fill: "#475569", angle: -90, position: "insideLeft", fontSize: 11 }}
                  stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }} />
                <Tooltip contentStyle={{ background: "#ffffff", border: "1px solid #e2e8f0",
                                          fontSize: 11, color: "#0f172a", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#94a3b8" strokeDasharray="4 4" />
                <Line type="monotone" dataKey="realized" stroke="#d97706" strokeWidth={2} dot />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="text-[10px] text-text-muted mt-2">
            Perfectly calibrated = the orange line equals the dashed diagonal. Line above diagonal = model
            is underconfident; below = overconfident. Currently this is the only honest accuracy proof.
          </div>
        </Panel>
      )}

      {/* Feature importance */}
      {feat?.features?.length > 0 && (
        <Panel title="Feature Importance (GradientBoosting)">
          <div className="space-y-1">
            {feat.features.slice(0, 15).map((f: any) => (
              <div key={f.feature} className="flex items-center gap-2 text-[11px]">
                <span className="w-40 text-text-secondary truncate" title={f.feature}>{f.feature}</span>
                <div className="flex-1 h-2 bg-bg-line rounded overflow-hidden">
                  <div className="h-full bg-accent-violet"
                       style={{ width: `${Math.min(100, f.importance * 100 / (feat.features[0]?.importance || 1) * 0.99)}%` }} />
                </div>
                <span className="w-16 text-right text-accent-amber tabular">{fmt.num(f.importance, 4)}</span>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* Live predict */}
      <Panel title="Live Prediction">
        <div className="flex gap-2 items-center">
          <input value={predSymbol} onChange={(e) => setPredSymbol(e.target.value.toUpperCase())}
            className="flex-1 max-w-xs bg-bg-base border border-bg-line rounded px-3 py-1.5 text-sm font-mono" />
          <button onClick={runPredict} disabled={predBusy || !status?.trained}
            className="px-4 py-1.5 bg-accent-amber text-black rounded text-sm font-semibold disabled:opacity-50">
            {predBusy ? "Predicting…" : "Predict"}
          </button>
          {!status?.trained && (
            <span className="text-[11px] text-accent-amber">Train the model first.</span>
          )}
        </div>

        {pred && pred.error && <div className="text-accent-red text-[11px] mt-3">{pred.error}</div>}
        {pred && !pred.error && (
          <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
            <Stat label="Direction" value={pred.direction}
              color={pred.direction === "BULLISH" ? "text-accent-green" : "text-accent-red"} />
            <Stat label="Ensemble probability" value={fmt.pct(pred.confidence_pct, 1)} color="text-accent-amber" />
            <Stat label="GBM individual" value={fmt.num(pred.gbm_prob, 4)} />
            <Stat label="MLP individual" value={fmt.num(pred.mlp_prob, 4)} />
            <div className="col-span-2 md:col-span-4">
              <div className="text-[10px] uppercase text-text-muted mb-1">Top contributing features</div>
              <div className="space-y-0.5">
                {Object.entries(pred.feature_contributions || {}).map(([k, v]: any) => (
                  <div key={k} className="text-[11px] flex justify-between">
                    <span className="text-text-secondary">{k}</span>
                    <span className={clsx("tabular", v > 0 ? "text-accent-green" : "text-accent-red")}>
                      {v > 0 ? "+" : ""}{v}
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div className="col-span-2 md:col-span-4 text-[10px] text-text-muted italic mt-2">
              {pred.note}
            </div>
          </div>
        )}
      </Panel>

      {/* Honesty footer */}
      <Panel title="Honest Limits — read before deploying capital">
        <ul className="text-[11px] text-text-secondary list-disc pl-5 space-y-1">
          <li>Models predict on the SAME features the existing engines produce. They cannot create signal where none exists — they only re-weight what's already there.</li>
          <li>Out-of-sample binary direction accuracy for liquid F&O equities tops out around <strong className="text-accent-amber">55-65%</strong> with strict filtering. Anything higher = overfit.</li>
          <li>Models <strong>drift</strong>. Retrain monthly minimum, quarterly safer.</li>
          <li>The training currently uses synthetic OHLCV in paper mode. Real edge only after live data flows in.</li>
          <li>Brier score &gt; 0.245 means worse than baseline — the training job refuses to save in that case.</li>
        </ul>
      </Panel>
    </div>
  );
}

function ArchCard({ icon: Icon, title, desc, color }:
                   { icon: any; title: string; desc: string; color: string }) {
  return (
    <div className="border border-bg-line rounded p-3 bg-bg-panel">
      <div className={clsx("flex items-center gap-2 mb-2", color)}>
        <Icon className="w-4 h-4" />
        <span className="font-semibold text-[13px]">{title}</span>
      </div>
      <p className="text-[11px] text-text-secondary leading-relaxed">{desc}</p>
    </div>
  );
}
