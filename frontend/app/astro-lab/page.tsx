"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { ErrorState, EmptyState, InfoBanner, LoadingSkeleton } from "@/components/States";
import {
  Sparkles, Flask, TrendingUp, TrendingDown, Calendar, Target, RefreshCw, AlertTriangle,
  CheckCircle2, XCircle, ArrowRight,
} from "lucide-react";
import clsx from "clsx";


/**
 * Astro Lab — the honest, measurable astrology evaluation page.
 *
 * Four panels:
 *   1. Pure-astrology call (no price action)
 *   2. Walk-forward hit rate of astrology alone
 *   3. Per-engine comparison (sorted by hit rate)
 *   4. Reversal-date planner for next 30 days
 *
 * Each section answers ONE question with data.
 */

export default function AstroLabPage() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [submitted, setSubmitted] = useState("NIFTY");

  const { data: pure }    = useSWR<any>(`/api/astro-lab/only/${submitted}`, fetcher,
                                          { refreshInterval: 60_000 });
  const { data: measure, error: measureErr, mutate: refetchMeasure } =
    useSWR<any>(`/api/astro-lab/measure/${submitted}?lookback_bars=120`, fetcher);
  const { data: perEng } = useSWR<any>(`/api/astro-lab/per-engine/${submitted}?lookback_bars=150`, fetcher);
  const { data: revDates } = useSWR<any>(`/api/astro-lab/reversal-dates/${submitted}?horizon_days=30`, fetcher);
  const { data: screen } = useSWR<any>(
    `/api/astro-lab/nakshatra-screener?direction=BOTH&top_n=12&only_aligned=true`,
    fetcher, { refreshInterval: 600_000 });
  const { data: fullConf } = useSWR<any>(
    `/api/astro-lab/full-confluence/${submitted}?periods=150`, fetcher);

  function run() {
    setSubmitted(symbol.toUpperCase().trim() || "NIFTY");
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-accent-violet/10 to-accent-amber/5 border border-accent-violet/30 rounded-lg p-5">
        <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-accent-violet" />
          Astro Lab
        </h1>
        <p className="text-[12px] text-text-muted mt-1">
          Honest evaluation of what astrology actually contributes. Each panel
          measures something specific with data, not opinion.
        </p>
        <div className="flex gap-2 mt-3">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
            className="flex-1 max-w-xs px-3 py-1.5 text-sm rounded border border-bg-line bg-bg-base focus:border-accent-amber" />
          <button onClick={run}
            className="bg-accent-amber text-white font-bold px-4 py-1.5 text-sm rounded hover:bg-accent-gold">
            Run all 4 experiments
          </button>
        </div>
      </div>

      {/* PANEL 1 — Pure astrology call */}
      <Panel title="1. Pure-Astrology Call (no price data used)"
        right={pure?.pure_astrology && (
          <span className={clsx("px-2 py-0.5 rounded text-[10px] font-bold uppercase",
            pure.pure_astrology.direction === "BULLISH" ? "bg-accent-green/15 text-accent-green" :
            pure.pure_astrology.direction === "BEARISH" ? "bg-accent-red/15 text-accent-red" :
                                                          "bg-text-muted/15 text-text-muted")}>
            {pure.pure_astrology.direction}  ·  {pure.pure_astrology.score}/100
          </span>
        )}>
        {pure ? (
          <div className="space-y-2 text-[11px]">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label="Nakshatra match"
                value={`${pure.components.symbol_astro_match.score} (${pure.components.symbol_astro_match.bias})`}
                color={pure.components.symbol_astro_match.bias === "BULLISH" ? "text-accent-green" :
                       pure.components.symbol_astro_match.bias === "BEARISH" ? "text-accent-red" : undefined} />
              <Stat label="Market climate"
                value={`${pure.components.market_sentiment.score} (${pure.components.market_sentiment.bias})`} />
              <Stat label="Hora ruler"
                value={`${pure.components.hora.ruler} (${pure.components.hora.bias})`} />
              <Stat label="Numerology root"
                value={`${pure.components.numerology.ruler}`} />
            </div>
            <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2">
              {pure.disclaimer}
            </div>
          </div>
        ) : <LoadingSkeleton lines={2} />}
      </Panel>

      {/* PANEL 2 — Astro-only walk-forward */}
      <Panel title="2. Walk-Forward Hit Rate (does astrology actually predict?)">
        {measureErr && <ErrorState message={String(measureErr.message)} onRetry={refetchMeasure} />}
        {!measure && !measureErr && <LoadingSkeleton />}
        {measure?.hit_rate_pct != null && (
          <div className="space-y-3 text-[11px]">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div>
                <div className="text-[9px] uppercase text-text-muted tracking-wider">Hit rate</div>
                <div className={clsx("text-2xl font-bold tabular",
                  measure.hit_rate_pct > 55 ? "text-accent-green" :
                  measure.hit_rate_pct > 50 ? "text-accent-amber" : "text-accent-red")}>
                  {measure.hit_rate_pct}%
                </div>
                <div className="text-[9px] text-text-muted">
                  random would be 50%
                </div>
              </div>
              <Stat label="Edge vs random" value={`${measure.edge_vs_random_pp > 0 ? "+" : ""}${measure.edge_vs_random_pp}pp`}
                color={measure.edge_vs_random_pp > 2 ? "text-accent-green" :
                       measure.edge_vs_random_pp > 0 ? "text-accent-amber" : "text-accent-red"} />
              <Stat label="Sample size" value={`${measure.n_predictions} bars`} />
              <Stat label="Verdict" value={measure.verdict?.replace(/_/g, " ")}
                color={measure.verdict?.includes("STRONG_EVIDENCE_FOR") ? "text-accent-green" :
                       measure.verdict?.includes("FOR") ? "text-accent-amber" :
                       measure.verdict?.includes("AGAINST") ? "text-accent-red" : undefined} />
            </div>
            <div className={clsx("rounded p-3 text-[11px]",
              measure.hit_rate_pct > 55 ? "bg-accent-green/5 border border-accent-green/30 text-accent-green" :
              measure.hit_rate_pct > 48 ? "bg-accent-amber/5 border border-accent-amber/30 text-accent-amber" :
                                            "bg-accent-red/5 border border-accent-red/30 text-accent-red")}>
              <strong>{measure.interpretation}</strong>
            </div>
          </div>
        )}
      </Panel>

      {/* PANEL 3 — Per-engine comparison */}
      <Panel title="3. Per-Engine Hit Rates (which engine actually works?)">
        {!perEng ? <LoadingSkeleton /> : (
          <table className="w-full text-[11px]">
            <thead className="text-text-muted">
              <tr>
                <th className="text-left py-1.5">Engine</th>
                <th className="text-right">Hit rate</th>
                <th className="text-right">Edge vs random</th>
                <th className="text-right">Sample</th>
                <th className="text-center">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {perEng.engine_hit_rates_sorted?.map((r: any) => {
                const hit = (r.hit_rate * 100);
                const edge = (r.edge_vs_random * 100);
                const verdict = edge > 5  ? "REAL EDGE" :
                                 edge > 1  ? "MARGINAL"  :
                                 edge > -2 ? "RANDOM"    : "ANTI-EDGE";
                const verdictColor = edge > 5  ? "text-accent-green" :
                                      edge > 1  ? "text-accent-amber" :
                                      edge > -2 ? "text-text-muted"   : "text-accent-red";
                return (
                  <tr key={r.engine} className="border-t border-bg-line">
                    <td className="py-1.5 font-bold capitalize">{r.engine}</td>
                    <td className="text-right tabular">{hit.toFixed(1)}%</td>
                    <td className={clsx("text-right tabular font-bold", verdictColor)}>
                      {edge > 0 ? "+" : ""}{edge.toFixed(1)}pp
                    </td>
                    <td className="text-right text-text-muted">{r.n_predictions}</td>
                    <td className={clsx("text-center font-bold uppercase text-[10px]", verdictColor)}>
                      {verdict}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="text-[10px] text-text-muted italic mt-3 pt-2 border-t border-bg-line">
          Engines with edge ≤ 0 are HURTING the system. If astrology shows up here as
          ANTI-EDGE, that's hard data — not opinion. You can shrink its weight via
          /api/optimize/apply.
        </div>
      </Panel>

      {/* PANEL 4 — Reversal date planner */}
      <Panel title="4. Next 30 Days — Reversal-Watch Dates (Gann time cycles + harmonics)">
        {!revDates ? <LoadingSkeleton /> : revDates.reversal_dates?.length === 0 ? (
          <EmptyState title="No reversal windows in next 30 days"
            message="No Gann time-cycle anchors fall in the next 30 days based on the current swing high/low." />
        ) : (
          <div className="space-y-2 text-[11px]">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Recent high" value={`₹${revDates.anchors?.recent_high?.price?.toFixed(2)}`}
                color="text-accent-red" />
              <Stat label="Recent low" value={`₹${revDates.anchors?.recent_low?.price?.toFixed(2)}`}
                color="text-accent-green" />
            </div>
            <table className="w-full text-[11px] mt-2">
              <thead className="text-text-muted">
                <tr>
                  <th className="text-left py-1">Date</th>
                  <th className="text-right">Days ahead</th>
                  <th className="text-left">Type</th>
                  <th className="text-left">Watch for</th>
                </tr>
              </thead>
              <tbody>
                {revDates.reversal_dates?.slice(0, 15).map((d: any, i: number) => (
                  <tr key={i} className="border-t border-bg-line">
                    <td className="py-1.5 font-bold tabular">{d.date}</td>
                    <td className="text-right text-text-muted">{d.days_ahead}d</td>
                    <td className="text-text-secondary text-[10px]">
                      {d.type.replace(/_/g, " ")}
                      {d.cycle_days && <span className="text-text-muted"> ({d.cycle_days}d)</span>}
                    </td>
                    <td className="text-text-secondary text-[10px]">{d.watch_for}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <InfoBanner type="warning">
              These dates flag <strong>elevated reversal probability windows</strong>,
              not specific buy/sell points. Always confirm with a technical signal
              (RSI divergence, BoS, candlestick reversal) on the day before acting.
            </InfoBanner>
          </div>
        )}
      </Panel>

      {/* PANEL 5 — Nakshatra screener (universe-wide reverse lookup) */}
      <Panel title="5. Stocks Aligned with Today's Moon Nakshatra"
        right={screen?.moon_nakshatra && (
          <span className="text-[10px] text-accent-amber">
            Moon: <strong>{screen.moon_nakshatra.name}</strong> ({screen.moon_nakshatra.ruler})
          </span>
        )}>
        {!screen ? <LoadingSkeleton lines={4} /> : (
          <>
            <div className="text-[10px] text-text-muted mb-2">
              Algorithm: tara distance d = (moon_nak - sym_nak + 27) mod 27, then technical+Gann composite, then top-N via heap.
              {" "}
              {screen.aligned_candidates}/{screen.universe_size} symbols passed the alignment filter.
            </div>
            <table className="w-full text-[11px]">
              <thead className="text-text-muted">
                <tr>
                  <th className="text-left py-1.5">Symbol</th>
                  <th className="text-right">Price</th>
                  <th className="text-right">Day %</th>
                  <th className="text-left">Nakshatra</th>
                  <th className="text-center">Tara</th>
                  <th className="text-right">Tech</th>
                  <th className="text-right">Gann</th>
                  <th className="text-right">+Astro</th>
                  <th className="text-right">Score</th>
                  <th className="text-center">Dir</th>
                </tr>
              </thead>
              <tbody>
                {screen.top_picks?.map((p: any) => (
                  <>
                    <tr key={p.symbol} className="border-t border-bg-line">
                      <td className="py-1.5 font-bold">
                        <a href={`/symbol/${p.symbol}`} className="hover:text-accent-amber">
                          {p.symbol}
                        </a>
                      </td>
                      <td className="text-right tabular">
                        {p.last_price != null
                          ? <span className="text-text-primary">₹{p.last_price.toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>
                          : <span className="text-text-muted text-[9px]">—</span>}
                      </td>
                      <td className={clsx("text-right tabular",
                        p.day_change_pct == null ? "text-text-muted" :
                        p.day_change_pct >= 0 ? "text-accent-green" : "text-accent-red")}>
                        {p.day_change_pct != null
                          ? `${p.day_change_pct >= 0 ? "+" : ""}${p.day_change_pct.toFixed(2)}%`
                          : "—"}
                      </td>
                      <td className="text-text-secondary">{p.symbol_nakshatra}</td>
                      <td className="text-center">
                        <span className={clsx("text-[10px] uppercase px-1.5 py-0.5 rounded font-bold",
                          p.tara_class === "JANMA" || p.tara_class === "SAMPADA" || p.tara_class === "SYMPATHETIC"
                            ? "bg-accent-green/15 text-accent-green"
                            : "bg-accent-amber/15 text-accent-amber")}>
                          {p.tara_class} (d={p.tara_distance})
                        </span>
                      </td>
                      <td className="text-right tabular">{p.details?.technical_score}</td>
                      <td className="text-right tabular">{p.details?.gann_score}</td>
                      <td className={clsx("text-right tabular",
                        p.tara_bonus > 0 ? "text-accent-green" : "text-accent-red")}>
                        {p.tara_bonus > 0 ? "+" : ""}{p.tara_bonus.toFixed(1)}
                      </td>
                      <td className={clsx("text-right tabular font-bold",
                        p.composite_score >= 60 ? "text-accent-green" :
                        p.composite_score <= 40 ? "text-accent-red" : "text-text-secondary")}>
                        {p.composite_score}
                      </td>
                      <td className="text-center">
                        {p.direction === "BULLISH" ? <TrendingUp className="w-3 h-3 text-accent-green inline" />
                         : p.direction === "BEARISH" ? <TrendingDown className="w-3 h-3 text-accent-red inline" />
                         : <span className="text-text-muted">—</span>}
                      </td>
                    </tr>
                    {p.reason && (
                      <tr key={`${p.symbol}-reason`} className="bg-bg-base/30">
                        <td colSpan={10} className="text-[10px] text-text-muted italic px-2 py-1">
                          ↳ {p.reason}
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
            <div className="text-[10px] text-text-muted italic mt-2 pt-2 border-t border-bg-line">
              Math: composite = clamp(0.6·tech + 0.4·gann + tara_bonus, 0, 100). Click symbol for full analysis.
            </div>
          </>
        )}
      </Panel>

      {/* PANEL 6 — Full confluence for the focused symbol */}
      <Panel title={`6. Full Confluence — Every Layer for ${submitted}`}
        right={fullConf && (
          <span className={clsx("text-[10px] font-bold uppercase px-2 py-0.5 rounded",
            fullConf.direction === "BULLISH" ? "bg-accent-green/15 text-accent-green" :
            fullConf.direction === "BEARISH" ? "bg-accent-red/15 text-accent-red" :
                                                 "bg-text-muted/15 text-text-muted")}>
            {fullConf.direction} · {fullConf.composite_score}/100
          </span>
        )}>
        {!fullConf ? <LoadingSkeleton lines={6} /> : (
          <>
            {/* Headline composite */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-[11px] mb-3">
              <Stat label="Spot" value={`₹${fullConf.spot?.toFixed(2)}`} />
              <Stat label="Composite" value={`${fullConf.composite_score}/100`}
                color={fullConf.composite_score >= 60 ? "text-accent-green" :
                       fullConf.composite_score <= 40 ? "text-accent-red" : undefined} />
              <Stat label="Arithmetic" value={fullConf.arithmetic_mean_score} />
              <Stat label="Geometric" value={fullConf.geometric_mean_score} />
              <Stat label="Cosine bias" value={fullConf.cosine_bias?.toFixed(3)} />
            </div>

            <div className="text-[10px] text-text-muted mb-2">
              Confidence band: <strong>[{fullConf.confidence_band[0]}, {fullConf.confidence_band[1]}]</strong>
              {" "} (width scales with engine disagreement)
            </div>

            {/* Per-engine row */}
            <div className="text-[9px] uppercase text-text-muted tracking-wider mb-1">Per-engine scores</div>
            <table className="w-full text-[11px] mb-3">
              <tbody>
                {Object.entries(fullConf.raw_engine_scores || {}).map(([engine, score]: any) => {
                  const bias = fullConf.raw_engine_biases[engine];
                  return (
                    <tr key={engine} className="border-t border-bg-line">
                      <td className="py-1 font-bold capitalize">{engine}</td>
                      <td className="text-right tabular">{score.toFixed(1)}</td>
                      <td className="text-right">
                        <span className={clsx("text-[10px] uppercase",
                          bias === "BULLISH" ? "text-accent-green" :
                          bias === "BEARISH" ? "text-accent-red" : "text-text-muted")}>
                          {bias}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {/* Gann breakdown */}
            {fullConf.engines?.gann && (
              <div className="bg-bg-base rounded p-2 mb-2 text-[10px]">
                <div className="text-[9px] uppercase text-text-muted font-bold mb-1">Gann breakdown</div>
                <div>Nearest support: <strong>₹{fullConf.engines.gann.nearest_support}</strong>
                  ({fullConf.engines.gann.distance_to_support_pct}% away)</div>
                <div>Nearest resistance: <strong>₹{fullConf.engines.gann.nearest_resistance}</strong>
                  ({fullConf.engines.gann.distance_to_resistance_pct}% away)</div>
                {fullConf.engines.gann.vibration_resonance?.score >= 60 && (
                  <div className="text-accent-amber mt-1">
                    ⚡ Vibration resonance with {fullConf.engines.gann.vibration_resonance.nearest_planet}
                    {" "}(score {fullConf.engines.gann.vibration_resonance.score})
                  </div>
                )}
              </div>
            )}

            {/* Astrology breakdown */}
            {fullConf.engines?.astrology && (
              <div className="bg-bg-base rounded p-2 mb-2 text-[10px]">
                <div className="text-[9px] uppercase text-text-muted font-bold mb-1">Astrology breakdown</div>
                <div>Symbol nakshatra: <strong>{fullConf.engines.astrology.symbol_nakshatra?.name}</strong>
                  {" "}(ruler {fullConf.engines.astrology.symbol_nakshatra?.ruler})</div>
                <div>Moon today: <strong>{fullConf.engines.astrology.moon_nakshatra?.name}</strong>
                  {" "}· tara distance {fullConf.engines.astrology.tara_distance}</div>
                <div>Mercury retrograde: {fullConf.engines.astrology.mercury_retrograde ? "YES" : "no"}</div>
                <div className="text-text-muted">{fullConf.engines.astrology.market_sentiment?.headline}</div>
              </div>
            )}

            {/* Formulas */}
            <div className="border-t border-bg-line pt-2 mt-2">
              <div className="text-[9px] uppercase text-text-muted font-bold tracking-wider mb-1">
                Mathematical formulas used
              </div>
              <ul className="text-[10px] text-text-muted font-mono space-y-0.5">
                {fullConf.formulas_used?.map((f: string, i: number) => (
                  <li key={i}>• {f}</li>
                ))}
              </ul>
            </div>

            <div className="text-[9px] text-text-muted italic mt-3 pt-2 border-t border-bg-line">
              {fullConf.disclaimer}
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}
