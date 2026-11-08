"use client";

/**
 * Engine attribution leaderboard — answers "which of our engines actually
 * contributes alpha vs which is noise?"
 *
 * For every engine that has voted in the signals journal during the lookback
 * window, shows:
 *   • Sample size (decided votes)
 *   • Hit rate when voting BULLISH vs BEARISH
 *   • Net hit rate
 *   • Edge vs baseline (+pp / -pp)
 *   • Avg PnL when the engine called direction-aligned
 *   • Status: ALPHA / NEUTRAL / NOISE / INSUFFICIENT_DATA
 *
 * Engines are ranked: alpha first, then noise (anti-predictive), then
 * insufficient. This is the dashboard that tells you which engines to keep,
 * which to downweight, and which to throw away.
 */

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { authedFetcher as fetcher, ApiError } from "@/lib/auth";
import { UpgradeRequired } from "@/components/UpgradeRequired";
import {
  Activity, ChevronLeft, TrendingUp, TrendingDown, Info, AlertTriangle, CheckCircle2, MinusCircle,
} from "lucide-react";
import clsx from "clsx";


type EngineRow = {
  engine:               string;
  bullish_votes:        number;
  bearish_votes:        number;
  bullish_wins:         number;
  bearish_wins:         number;
  bullish_losses:       number;
  bearish_losses:       number;
  sample_size:          number;
  decided_size:         number;
  hit_rate_bull:        number | null;
  hit_rate_bear:        number | null;
  net_hit_rate:         number | null;
  edge_pp:              number | null;
  avg_pnl_when_bullish: number | null;
  avg_pnl_when_bearish: number | null;
  status:               "ALPHA" | "NEUTRAL" | "NOISE" | "INSUFFICIENT_DATA";
  verdict:              string;
};

type Attribution = {
  as_of:             string;
  lookback_days:     number;
  horizon:           string | null;
  total_signals:     number;
  evaluated_signals: number;
  baseline_hit_rate: number;
  min_samples_threshold: number;
  engines:           EngineRow[];
  current_weights?: {
    weights:               Record<string, number>;
    status:                "DATA_DRIVEN" | "EQUAL_WEIGHT" | "MIXED" | "ERROR";
    reason:                string;
    data_driven_engines:   string[];
    equal_weight_engines:  string[];
  };
};


export default function EngineAttributionPage() {
  const [days, setDays] = useState(90);
  const [horizon, setHorizon] = useState<"" | "INTRADAY" | "SWING" | "POSITIONAL">("");

  const url = `/api/journal/engine-attribution?days=${days}` +
    (horizon ? `&horizon=${horizon}` : "");
  const { data, error, isLoading } = useSWR<Attribution>(url, fetcher,
    { refreshInterval: 300_000, shouldRetryOnError: false });

  if (error instanceof ApiError && error.status === 402) {
    return <UpgradeRequired error={error} />;
  }

  return (
    <div className="space-y-4">
      <Link href="/portal/performance"
            className="inline-flex items-center gap-1 text-[12px] text-text-muted hover:text-accent-amber">
        <ChevronLeft className="w-3.5 h-3.5" /> Back to performance
      </Link>

      <Header />

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
        {data && (
          <span className="text-[11px] text-text-muted">
            {data.evaluated_signals} evaluated · baseline{" "}
            <strong className="text-text-primary">
              {(data.baseline_hit_rate * 100).toFixed(1)}%
            </strong>
          </span>
        )}
      </div>

      {/* Loading + empty states */}
      {isLoading && !data && (
        <div className="text-text-muted text-center py-12">Loading engine attribution…</div>
      )}
      {data && data.evaluated_signals === 0 && (
        <div className="bg-bg-surface border border-accent-amber/30 rounded-lg p-6 text-center">
          <Info className="w-6 h-6 text-accent-amber mx-auto mb-2" />
          <p className="text-sm text-text-secondary">
            No evaluated signals yet in the last {days} days. The outcome tracker
            needs ≥5 days to evaluate any signal. Check back once trades have closed.
          </p>
        </div>
      )}

      {/* Current weights banner — surfaces what the recommender is ACTUALLY using */}
      {data?.current_weights && (
        <CurrentWeightsBanner cw={data.current_weights} />
      )}

      {/* Leaderboard */}
      {data && data.engines?.length > 0 && (
        <EngineLeaderboard engines={data.engines} baseline={data.baseline_hit_rate} />
      )}

      {/* Methodology */}
      {data && data.engines?.length > 0 && (
        <Methodology min_samples={data.min_samples_threshold} />
      )}
    </div>
  );
}


function CurrentWeightsBanner({ cw }: { cw: NonNullable<Attribution["current_weights"]> }) {
  const statusCfg = {
    DATA_DRIVEN: {
      border: "border-accent-green/40", bg: "bg-accent-green/5", text: "text-accent-green",
      icon: <CheckCircle2 className="w-4 h-4" />,
      label: "Data-driven",
    },
    MIXED: {
      border: "border-accent-amber/40", bg: "bg-accent-amber/5", text: "text-accent-amber",
      icon: <Info className="w-4 h-4" />,
      label: "Mixed",
    },
    EQUAL_WEIGHT: {
      border: "border-bg-line", bg: "bg-bg-base/40", text: "text-text-secondary",
      icon: <MinusCircle className="w-4 h-4" />,
      label: "Equal weighting",
    },
    ERROR: {
      border: "border-accent-red/40", bg: "bg-accent-red/5", text: "text-accent-red",
      icon: <AlertTriangle className="w-4 h-4" />,
      label: "Error",
    },
  }[cw.status];
  const weightEntries = Object.entries(cw.weights || {});
  return (
    <div className={clsx("border rounded-lg p-4 space-y-3", statusCfg.border, statusCfg.bg)}>
      <div className="flex items-start gap-2 flex-wrap">
        <div className={clsx("flex items-center gap-1.5 font-bold text-sm", statusCfg.text)}>
          {statusCfg.icon}
          Live voting weights — {statusCfg.label}
        </div>
        <div className="text-[11px] text-text-secondary flex-1 min-w-0">{cw.reason}</div>
      </div>
      {weightEntries.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {weightEntries
            .sort((a, b) => b[1] - a[1])
            .map(([engine, w]) => (
              <span key={engine}
                     className={clsx("inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border tabular",
                                      w > 1.05 ? "text-accent-green border-accent-green/40 bg-accent-green/5"
                                       : w < 0.95 ? "text-accent-red border-accent-red/40 bg-accent-red/5"
                                       : "text-text-secondary border-bg-line bg-bg-base/30")}>
                <span className="font-semibold uppercase tracking-wider">{engine}</span>
                <span className="font-bold">{w.toFixed(2)}×</span>
              </span>
            ))}
        </div>
      )}
      {cw.equal_weight_engines && cw.equal_weight_engines.length > 0 && (
        <div className="text-[10px] text-text-muted">
          Equal-weighted (insufficient data):{" "}
          <span className="font-mono">{cw.equal_weight_engines.join(", ")}</span>
        </div>
      )}
    </div>
  );
}


function Header() {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
        <Activity className="w-5 h-5 text-accent-amber" />
        Engine attribution
      </h1>
      <p className="text-[12px] text-text-secondary mt-1 leading-relaxed">
        Which of the {17} engines actually contributes alpha when it votes BULLISH or BEARISH?
        Computed from the live journal of evaluated signals — no guesses, no marketing numbers.
        Anti-predictive engines (hit rate well below baseline) are surfaced as NOISE so you can
        downweight or remove them.
      </p>
    </div>
  );
}


function EngineLeaderboard({ engines, baseline }: { engines: EngineRow[]; baseline: number }) {
  const alpha = engines.filter((e) => e.status === "ALPHA");
  const neutral = engines.filter((e) => e.status === "NEUTRAL");
  const noise = engines.filter((e) => e.status === "NOISE");
  const insufficient = engines.filter((e) => e.status === "INSUFFICIENT_DATA");

  return (
    <div className="space-y-4">
      {alpha.length > 0 && (
        <Section title="Alpha contributors"
                  desc="Net hit rate >5pp above baseline. Keep, consider upweighting."
                  rows={alpha} baseline={baseline} statusColor="text-accent-green" />
      )}
      {neutral.length > 0 && (
        <Section title="Neutral"
                  desc="Within ±5pp of baseline. Marginal contribution."
                  rows={neutral} baseline={baseline} statusColor="text-text-secondary" />
      )}
      {noise.length > 0 && (
        <Section title="Noise (anti-predictive)"
                  desc="Hit rate >5pp BELOW baseline. Downweighting or removing should improve overall accuracy."
                  rows={noise} baseline={baseline} statusColor="text-accent-red" />
      )}
      {insufficient.length > 0 && (
        <Section title="Insufficient data"
                  desc="Fewer evaluated votes than the threshold — no verdict possible yet."
                  rows={insufficient} baseline={baseline} statusColor="text-text-muted" />
      )}
    </div>
  );
}


function Section({ title, desc, rows, baseline, statusColor }:
                  { title: string; desc: string; rows: EngineRow[];
                    baseline: number; statusColor: string }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg overflow-hidden">
      <div className="px-4 py-2.5 border-b border-bg-line">
        <h2 className={clsx("text-sm font-bold flex items-center gap-2", statusColor)}>
          <StatusIcon status={title} />
          {title}
          <span className="text-[10px] text-text-muted font-normal">
            ({rows.length} {rows.length === 1 ? "engine" : "engines"})
          </span>
        </h2>
        <p className="text-[11px] text-text-muted mt-0.5">{desc}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="bg-bg-base/30 text-text-muted">
            <tr>
              <th className="text-left py-2 pl-4">Engine</th>
              <th className="text-right">Votes</th>
              <th className="text-right">Net hit %</th>
              <th className="text-right">Edge vs baseline</th>
              <th className="text-right">Bullish votes (hit %)</th>
              <th className="text-right">Bearish votes (hit %)</th>
              <th className="text-right pr-4">Avg PnL</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <EngineRowView key={r.engine} row={r} baseline={baseline} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function EngineRowView({ row, baseline }: { row: EngineRow; baseline: number }) {
  const edgeColor =
    row.edge_pp == null            ? "text-text-muted" :
    row.edge_pp >= 5              ? "text-accent-green font-bold" :
    row.edge_pp >= -5             ? "text-text-secondary" :
                                       "text-accent-red font-bold";

  const netHitColor =
    row.net_hit_rate == null     ? "text-text-muted" :
    row.net_hit_rate > 0.55       ? "text-accent-green" :
    row.net_hit_rate >= 0.45      ? "text-accent-amber" :
                                       "text-accent-red";

  const avgPnl = (() => {
    const both = [row.avg_pnl_when_bullish, row.avg_pnl_when_bearish].filter((x): x is number => x != null);
    if (!both.length) return null;
    return both.reduce((a, b) => a + b, 0) / both.length;
  })();

  return (
    <tr className="border-t border-bg-line hover:bg-bg-base/30">
      <td className="py-2 pl-4">
        <div className="font-bold text-text-primary uppercase tracking-wider text-[11px]">
          {row.engine}
        </div>
        <div className="text-[9px] text-text-muted leading-tight max-w-md">
          {row.verdict}
        </div>
      </td>
      <td className="text-right tabular">{row.decided_size}/{row.sample_size}</td>
      <td className={clsx("text-right tabular font-bold", netHitColor)}>
        {row.net_hit_rate != null ? `${(row.net_hit_rate * 100).toFixed(1)}%` : "—"}
      </td>
      <td className={clsx("text-right tabular", edgeColor)}>
        {row.edge_pp != null
          ? `${row.edge_pp > 0 ? "+" : ""}${row.edge_pp.toFixed(1)}pp`
          : "—"}
      </td>
      <td className="text-right tabular text-text-secondary">
        <span className="text-text-primary">{row.bullish_votes}</span>
        {row.hit_rate_bull != null && (
          <span className="text-text-muted ml-1">
            ({(row.hit_rate_bull * 100).toFixed(0)}%)
          </span>
        )}
      </td>
      <td className="text-right tabular text-text-secondary">
        <span className="text-text-primary">{row.bearish_votes}</span>
        {row.hit_rate_bear != null && (
          <span className="text-text-muted ml-1">
            ({(row.hit_rate_bear * 100).toFixed(0)}%)
          </span>
        )}
      </td>
      <td className={clsx("text-right tabular pr-4",
        avgPnl == null ? "text-text-muted" :
        avgPnl > 0 ? "text-accent-green" : "text-accent-red")}>
        {avgPnl != null ? `${avgPnl > 0 ? "+" : ""}${avgPnl.toFixed(2)}%` : "—"}
      </td>
    </tr>
  );
}


function StatusIcon({ status }: { status: string }) {
  if (status.toLowerCase().includes("alpha"))         return <CheckCircle2 className="w-4 h-4" />;
  if (status.toLowerCase().includes("noise"))         return <AlertTriangle className="w-4 h-4" />;
  if (status.toLowerCase().includes("neutral"))       return <MinusCircle className="w-4 h-4" />;
  return <Info className="w-4 h-4" />;
}


function Methodology({ min_samples }: { min_samples: number }) {
  return (
    <div className="bg-bg-surface border border-bg-line rounded-lg p-4">
      <h3 className="text-sm font-bold text-text-primary flex items-center gap-2 mb-2">
        <Info className="w-4 h-4 text-accent-amber" />
        How this is computed
      </h3>
      <ul className="text-[11px] text-text-secondary space-y-1 leading-relaxed">
        <li>
          · For every <strong>evaluated</strong> signal in the journal (outcome
          known — target hit, stop hit, or 5-day PnL settled), each engine's
          vote (BULLISH / BEARISH / NEUTRAL) is read from <code>engines_snapshot</code>.
        </li>
        <li>
          · A vote counts as <span className="text-accent-green">a win</span> when
          the trade's actual outcome agreed with the engine's directional call.
          Neutral votes are skipped — we measure directional contribution only.
        </li>
        <li>
          · <strong>Edge vs baseline</strong> = engine's net hit rate − overall
          baseline hit rate. Positive = adding alpha; negative = anti-predictive.
        </li>
        <li>
          · An engine is only published with a hit rate when it has ≥{min_samples}{" "}
          decided votes. Below that, status is <strong>INSUFFICIENT_DATA</strong>{" "}
          — never a misleading percentage from a tiny sample.
        </li>
        <li>
          · <strong>Anti-predictive</strong> (NOISE) engines are real. An engine
          that wins 38% of the time when baseline is 52% is consistently wrong —
          flipping its signal or removing it improves the aggregate.
        </li>
      </ul>
    </div>
  );
}
