"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Panel, Stat } from "@/components/Panel";
import { SymbolSearch } from "@/components/SymbolSearch";
import { SimpleRecommendation } from "@/components/SimpleRecommendation";
import { AnimatedNumber, ChangeBadge, PulseBadge, GlowCard } from "@/components/animated";
import { fmt, biasColor, signalColor } from "@/lib/format";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ReferenceLine, ComposedChart, Bar,
} from "recharts";
import {
  TrendingUp, TrendingDown, ShieldCheck, Moon, Clock, Sparkles,
  BarChart3, Compass, Hash, Brain, AlertTriangle, ArrowRight,
  Zap, Timer, Calendar, Target, CheckCircle2, XCircle,
} from "lucide-react";
import clsx from "clsx";

export default function SymbolPage({ params }: { params: { ticker: string } }) {
  // Next.js 14: params is a plain object. (Next.js 15+ makes it a Promise — adapt later.)
  const sym = params.ticker.toUpperCase();
  const { data, isLoading, error } = useSWR<any>(
    `/api/symbol/${sym}?horizon=SWING`,
    fetcher,
    { refreshInterval: 10_000 }
  );
  const { data: weekly } = useSWR<any>(
    `/api/forecast/symbol/${sym}?days=7`,
    fetcher,
    { refreshInterval: 600_000 }
  );

  // ---- View mode (Simple / Advanced) — persisted in localStorage ----
  const [viewMode, setViewMode] = useState<"simple" | "advanced">("simple");
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem("marketlens_view_mode");
    if (saved === "simple" || saved === "advanced") setViewMode(saved);
  }, []);
  function setMode(m: "simple" | "advanced") {
    setViewMode(m);
    if (typeof window !== "undefined") localStorage.setItem("marketlens_view_mode", m);
  }

  if (isLoading && !data) {
    return <div className="text-text-secondary text-sm p-4">Loading {sym}…</div>;
  }
  if (error) {
    return <div className="text-accent-red text-sm p-4">Error: {error.message}</div>;
  }
  if (!data) return null;

  const up = data.ltp.change >= 0;
  const ltpColor = up ? "text-accent-green" : "text-accent-red";
  const dir = data.direction;

  return (
    <div className="space-y-4">
      {/* Price-sanity banner — RED when candle close vs broker LTP disagree
          by >2%. The numbers on the page can't be trusted in this state.
          Common causes: stale scrip-master after a corporate action (bonus
          / split), wrong exchange segment, or cached pre-event data. */}
      {data.price_sanity?.verdict === "SUSPECT" && (
        <div className="border-2 border-accent-red/60 bg-accent-red/10 text-accent-red rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-bold text-sm uppercase tracking-wider mb-1">
                ⚠ Price data does NOT match the broker — do not trade off this view
              </div>
              <ul className="text-[11px] text-text-secondary space-y-0.5">
                {data.price_sanity.reasons?.map((r: string, i: number) => (
                  <li key={i}>• {r}</li>
                ))}
              </ul>
              <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] tabular bg-bg-base/40 rounded p-2">
                <div>
                  <div className="text-text-muted">Candle close</div>
                  <div className="font-bold">₹{data.price_sanity.candle_close ?? "—"}</div>
                </div>
                <div>
                  <div className="text-text-muted">Broker LTP</div>
                  <div className="font-bold">₹{data.price_sanity.broker_ltp ?? "—"}</div>
                </div>
                <div>
                  <div className="text-text-muted">Discrepancy</div>
                  <div className="font-bold">
                    {data.price_sanity.discrepancy_pct != null
                      ? `${data.price_sanity.discrepancy_pct.toFixed(2)}%`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-text-muted">Last bar age</div>
                  <div className="font-bold">
                    {data.price_sanity.last_bar_age_days != null
                      ? `${data.price_sanity.last_bar_age_days}d ago`
                      : "—"}
                  </div>
                </div>
              </div>
              <div className="mt-2 text-[10px] text-text-secondary">
                Next steps: ask admin to <code className="px-1 bg-bg-base rounded">POST /api/market/instruments/refresh</code>,
                then <code className="px-1 bg-bg-base rounded">POST /api/backfill/run?symbols={data.symbol}</code>.
                Live diagnose at <code className="px-1 bg-bg-base rounded">GET /api/market/diagnose/{data.symbol}</code>.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Partial-data warning banner */}
      {data.partial_warning && (
        <div className="border border-accent-amber/40 bg-accent-amber/10 text-accent-amber rounded p-3 text-[11px] flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{data.partial_warning}</span>
        </div>
      )}

      {/* ─────── Simple / Advanced toggle ─────── */}
      <div className="flex items-center justify-between">
        <SymbolSearch />
        <div className="flex items-center gap-1 bg-bg-panel border border-bg-line rounded p-0.5">
          <button onClick={() => setMode("simple")}
            className={clsx("px-3 py-1 text-[11px] font-bold uppercase tracking-wider rounded transition-colors",
              viewMode === "simple"
                ? "bg-accent-amber text-white"
                : "text-text-muted hover:text-text-primary")}>
            Simple
          </button>
          <button onClick={() => setMode("advanced")}
            className={clsx("px-3 py-1 text-[11px] font-bold uppercase tracking-wider rounded transition-colors",
              viewMode === "advanced"
                ? "bg-accent-amber text-white"
                : "text-text-muted hover:text-text-primary")}>
            Advanced
          </button>
        </div>
      </div>

      {/* SIMPLE VIEW — single Angel-One-style card */}
      {viewMode === "simple" && (
        <>
          <SimpleRecommendation data={data} />
          <div className="text-[10px] text-text-muted text-center">
            Want all 30+ engines, calibration, quant indicators? Switch to{" "}
            <button onClick={() => setMode("advanced")} className="text-accent-amber underline">Advanced</button>.
          </div>
        </>
      )}

      {/* ADVANCED VIEW — all the original panels */}
      {viewMode === "advanced" && <>

      {/* ─────── Top bar: search + symbol identity + LTP ─────── */}
      <div className="grid grid-cols-12 gap-4 items-center">
        <div className="col-span-12 md:col-span-4">
          <SymbolSearch />
        </div>
        <div className="col-span-12 md:col-span-8 flex items-baseline justify-end gap-4 flex-wrap">
          <div>
            <div className="text-2xl font-bold text-text-primary tracking-wide">{sym}</div>
            <div className="text-[10px] text-text-muted uppercase">
              {data.exchange} · {data.analyzers.vedic?.nakshatra || "—"} nakshatra
              {data.data_source === "live"
                ? <span className="text-accent-green ml-2">● LIVE</span>
                : data.data_source === "synthetic_fallback"
                ? <span className="text-accent-red ml-2">● STALE (live unavailable)</span>
                : <span className="text-accent-amber ml-2">● CACHED</span>}
            </div>
          </div>
          <div className="text-right">
            <AnimatedNumber value={data.ltp.ltp || 0} decimals={2}
              className={clsx("text-3xl font-bold tabular", ltpColor)} />
            <div className="flex items-center gap-2 justify-end">
              <ChangeBadge value={data.ltp.change} pct={data.ltp.change_pct} />
              {up
                ? <TrendingUp className="w-4 h-4 text-accent-green" />
                : <TrendingDown className="w-4 h-4 text-accent-red" />}
            </div>
          </div>
        </div>
      </div>

      {/* OHLC strip */}
      <div className="grid grid-cols-4 gap-2 text-[11px]">
        <OHLCCard label="Open"  value={data.ltp.open} />
        <OHLCCard label="High"  value={data.ltp.high} color="text-accent-green" />
        <OHLCCard label="Low"   value={data.ltp.low}  color="text-accent-red" />
        <OHLCCard label="Close" value={data.ltp.close} />
      </div>

      {/* Big chart + signal card side-by-side */}
      <div className="grid grid-cols-12 gap-4">
        {/* Chart */}
        <div className="col-span-12 lg:col-span-8">
          <Panel title="Price Chart (60 bars)" right={
            <span className="text-[10px] text-text-muted">
              {data.data_source === "live" ? "live ticks every 10s"
                : data.data_source === "synthetic_fallback" ? "LIVE FEED DOWN — synthetic fallback"
                : "cached bars"}
            </span>
          }>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={data.chart}>
                  <defs>
                    <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%"   stopColor={up ? "#00a86b" : "#dc2626"} stopOpacity={0.45} />
                      <stop offset="100%" stopColor={up ? "#00a86b" : "#dc2626"} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                  <XAxis dataKey="t" stroke="#94a3b8" tick={{ fontSize: 9, fill: "#475569" }} />
                  <YAxis stroke="#94a3b8" tick={{ fontSize: 10, fill: "#475569" }} domain={["auto", "auto"]} />
                  <Tooltip
                    contentStyle={{ background: "#ffffff", border: "1px solid #e2e8f0",
                                      fontSize: 11, color: "#0f172a", boxShadow: "0 4px 12px rgba(15,23,42,0.08)" }}
                    formatter={(v: any) => Number(v).toFixed(2)}
                  />
                  <ReferenceLine y={data.ltp.close} stroke="#64748b" strokeDasharray="2 3" />
                  <Area type="monotone" dataKey="c" stroke={up ? "#00a86b" : "#dc2626"}
                        strokeWidth={2} fill="url(#priceGrad)" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>

        {/* Trade card — recommendation summary */}
        <div className="col-span-12 lg:col-span-4">
          {data.confidence >= 65
            ? <GlowCard intensity="medium" color={dir === "BULLISH" ? "green" : "red"}>
                <TradeCard data={data} />
              </GlowCard>
            : <TradeCard data={data} />}
        </div>
      </div>

      {/* Analyzer matrix — 7 engines */}
      <Panel title="Multi-Analyzer Verdict"
        right={
          <div className="flex items-center gap-3 text-[10px]">
            <span>Aligned: <span className="text-accent-green font-bold">{data.confluence.aligned_count}/{data.confluence.total_count}</span></span>
            <span className={`px-1.5 py-0.5 rounded font-bold uppercase ${
              data.confluence.grade === "UNANIMOUS" ? "bg-accent-green/20 text-accent-green"
              : data.confluence.grade === "VERY_STRONG" ? "bg-accent-green/10 text-accent-green"
              : data.confluence.grade === "STRONG" ? "bg-accent-blue/15 text-accent-blue"
              : "bg-accent-amber/10 text-accent-amber"}`}>
              {data.confluence.grade?.replace("_", " ")}
            </span>
          </div>
        }>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2">
          <AnalyzerTile name="Technical" icon={BarChart3} a={data.analyzers.technical} />
          <AnalyzerTile name="SMC/ICT" icon={BarChart3} a={data.analyzers.smc} />
          <AnalyzerTile name="Gann" icon={Compass} a={data.analyzers.gann} />
          <AnalyzerTile name="Fibonacci" icon={Compass} a={data.analyzers.fibonacci} />
          <AnalyzerTile name="Vedic" icon={Sparkles} a={data.analyzers.vedic} />
          <AnalyzerTile name="Numerology" icon={Hash} a={data.analyzers.numerology} />
          <AnalyzerTile name="ML" icon={Brain} a={
            data.analyzers.ml
              ? { score: data.analyzers.ml.confidence_pct, bias: data.analyzers.ml.direction,
                  reasons: [`GBM: ${(data.analyzers.ml.gbm_prob * 100).toFixed(1)}%`,
                             `MLP: ${(data.analyzers.ml.mlp_prob * 100).toFixed(1)}%`] }
              : null
          } />
        </div>
      </Panel>

      {/* Weekly outlook — astro + tara + day-lord per day for next 7 days */}
      {weekly?.days && (
        <Panel title={`${sym} — Weekly Outlook (next 7 days)`}
          right={
            <div className="flex items-center gap-3 text-[10px] text-text-muted">
              <span>Best BUY: <span className="text-accent-green">{weekly.best_buy_day || "—"}</span></span>
              <span>Best SELL: <span className="text-accent-red">{weekly.best_sell_day || "—"}</span></span>
            </div>
          }>
          <div className="grid grid-cols-7 gap-2">
            {weekly.days.map((d: any) => (
              <DayCell key={d.date} d={d} />
            ))}
          </div>
          <div className="text-[10px] text-text-muted mt-3 leading-relaxed">
            Per-day cyclical bias for {sym} — combines Moon's nakshatra tara from the symbol's
            nakshatra ({weekly.symbol_nakshatra}, ruled by {weekly.symbol_nakshatra_ruler}),
            day-lord climate, numerology compatibility, and Gann cycle proximity.
            <span className="text-accent-amber"> Best BUY / SELL day</span> = highest / lowest composite score.
          </div>
        </Panel>
      )}

      {/* Context: lunar gate + hora + market climate */}
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-4">
          <ContextCard
            icon={Moon} label="Lunar Gate"
            big={data.context.lunar?.gate || "—"}
            sub={data.context.lunar?.summary}
            badge={data.context.lunar?.is_full_moon ? "FULL MOON" :
                    data.context.lunar?.is_void_of_course ? "VOID-OF-COURSE" :
                    data.context.lunar?.eclipse_zone ? "ECLIPSE WINDOW" : null}
            color={data.context.lunar?.gate === "AVOID" ? "red"
                    : data.context.lunar?.gate === "WAIT" ? "red"
                    : data.context.lunar?.gate === "CAUTION" ? "amber" : "green"}
          />
        </div>
        <div className="col-span-12 md:col-span-4">
          <ContextCard
            icon={Clock} label="Current Hora"
            big={data.context.hora?.ruler || "—"}
            sub={`${data.context.hora?.bias} (weight ${data.context.hora?.weight}). Next: ${data.context.hora?.next_ruler} in ${data.context.hora?.next_change_in_minutes}m`}
            color={data.context.hora?.bias === "bullish" ? "green"
                    : data.context.hora?.bias === "bearish" ? "red" : "amber"}
          />
        </div>
        <div className="col-span-12 md:col-span-4">
          <ContextCard
            icon={Sparkles} label="Market Climate"
            big={data.context.market_sentiment?.bias || "—"}
            sub={data.context.market_sentiment?.headline}
            color={data.context.market_sentiment?.bias === "BULLISH" ? "green"
                    : data.context.market_sentiment?.bias === "BEARISH" ? "red" : "amber"}
          />
        </div>
      </div>

      {/* Consistency conflicts (if any) */}
      {data.validation?.conflicts?.length > 0 && (
        <Panel title="Conflict Analysis"
          right={<span className={`text-[10px] font-bold uppercase ${
            data.validation.final_action === "PROCEED" ? "text-accent-green"
            : data.validation.final_action === "WARN" ? "text-accent-amber"
            : "text-accent-red"}`}>{data.validation.final_action}</span>}>
          <div className="text-[11px] text-text-secondary mb-2">{data.validation.summary}</div>
          <ul className="space-y-1">
            {data.validation.conflicts.map((c: any, i: number) => (
              <li key={i} className="text-[11px] flex items-start gap-2">
                <span className={clsx("uppercase font-bold shrink-0 w-12",
                  c.severity === "HIGH" ? "text-accent-red"
                  : c.severity === "MEDIUM" ? "text-accent-amber"
                  : "text-text-muted")}>[{c.severity[0]}]</span>
                <span className="text-text-muted w-20 shrink-0">{c.component}:</span>
                <span className="text-text-secondary">{c.message}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      {/* ─────── Confidence Band + Session Split (the two improvements) ─────── */}
      {(data.confidence_band || data.session_split) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {data.confidence_band && !data.confidence_band.error && (
            <ConfidenceBandPanel cb={data.confidence_band} />
          )}
          {data.session_split && !data.session_split.error && (
            <SessionSplitPanel ss={data.session_split} />
          )}
        </div>
      )}

      {/* ─────── Per-Horizon Strategy Plans (Intraday / Swing / Positional) ─────── */}
      {data.horizon_plans && !data.horizon_plans.error && (
        <HorizonStrategyPanel hp={data.horizon_plans} />
      )}

      {/* ─────── Advanced TA — VWAP + Divergence + MTF Momentum ─────── */}
      {data.advanced_ta && !data.advanced_ta.error && (
        <AdvancedTaPanel ata={data.advanced_ta} />
      )}

      {/* ─────── Meta-learner (online AI) — admin view always shows
          the panel even pre-warmup so devs can see model state during dev ─────── */}
      {data.meta_learner && !data.meta_learner.error && (
        <MetaLearnerPanel ml={data.meta_learner} ruleBasedConf={data.confidence} />
      )}

      {/* ─────── Advanced Quant Indicators ─────── */}
      {data.quant && !data.quant.error && (
        <Panel title="Advanced Quant Analysis"
          right={
            <div className="flex items-center gap-3 text-[10px]">
              <span className={clsx("px-2 py-0.5 rounded font-bold uppercase",
                data.quant.regime === "TRENDING" ? "bg-accent-green/20 text-accent-green" :
                data.quant.regime === "MEAN_REVERTING" ? "bg-accent-blue/20 text-accent-blue" :
                                                          "bg-accent-amber/20 text-accent-amber")}>
                {data.quant.regime.replace("_", " ")}
              </span>
              <span className="text-text-muted">{data.quant.bars_used} bars</span>
            </div>
          }>
          {/* Headline metrics row */}
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3 text-[11px] mb-3">
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Hurst</div>
              <div className={clsx("font-bold tabular text-base",
                data.quant.hurst > 0.55 ? "text-accent-green" :
                data.quant.hurst < 0.45 ? "text-accent-red" : "text-text-secondary")}>
                {data.quant.hurst.toFixed(3)}
              </div>
              <div className="text-[9px] text-text-muted">
                {data.quant.hurst > 0.55 ? "trending" : data.quant.hurst < 0.45 ? "mean-rev" : "random"}
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Fractal Dim</div>
              <div className="font-bold tabular text-base">{data.quant.fractal_dimension.toFixed(3)}</div>
              <div className="text-[9px] text-text-muted">
                {data.quant.fractal_dimension < 1.3 ? "smooth" :
                 data.quant.fractal_dimension > 1.7 ? "noisy" : "random-walk"}
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Z-20</div>
              <div className={clsx("font-bold tabular text-base",
                Math.abs(data.quant.z_score_20) > 2 ? "text-accent-red" :
                Math.abs(data.quant.z_score_20) > 1 ? "text-accent-amber" : "text-text-secondary")}>
                {data.quant.z_score_20 > 0 ? "+" : ""}{data.quant.z_score_20.toFixed(2)}σ
              </div>
              <div className="text-[9px] text-text-muted">
                {Math.abs(data.quant.z_score_20) > 2 ? "extreme" :
                 Math.abs(data.quant.z_score_20) > 1 ? "stretched" : "within band"}
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">LR R²</div>
              <div className={clsx("font-bold tabular text-base",
                data.quant.lr_channel?.r_squared > 0.7 ? "text-accent-green" :
                data.quant.lr_channel?.r_squared > 0.3 ? "text-accent-amber" : "text-text-muted")}>
                {data.quant.lr_channel?.r_squared?.toFixed(2)}
              </div>
              <div className="text-[9px] text-text-muted">{data.quant.lr_channel?.trend?.replace("_", " ")}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">OU Half-life</div>
              <div className="font-bold tabular text-base">
                {data.quant.ou?.half_life_bars ? `${data.quant.ou.half_life_bars.toFixed(0)}d` : "—"}
              </div>
              <div className="text-[9px] text-text-muted">{data.quant.ou?.regime?.replace("_", " ")}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">GARCH σ</div>
              <div className="font-bold tabular text-base">
                {data.quant.garch?.annualised_next_vol_pct?.toFixed(1)}%
              </div>
              <div className="text-[9px] text-text-muted">annualised next bar</div>
            </div>
          </div>

          {/* Second row: Donchian / Vortex / CMF / Heikin Ashi / Kalman */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-[11px] mb-3 border-t border-bg-line pt-3">
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Donchian 20</div>
              <div className="font-bold text-[12px]">{data.quant.donchian_20?.signal?.replace("_", " ")}</div>
              <div className="text-[9px] text-text-muted">
                pos {data.quant.donchian_20?.position_pct?.toFixed(0)}%
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Vortex</div>
              <div className={clsx("font-bold",
                data.quant.vortex?.bias === "BULLISH" ? "text-accent-green" : "text-accent-red")}>
                {data.quant.vortex?.strength} {data.quant.vortex?.bias}
              </div>
              <div className="text-[9px] text-text-muted">
                VI+ {data.quant.vortex?.vi_plus?.toFixed(2)} / VI- {data.quant.vortex?.vi_minus?.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">CMF (flow)</div>
              <div className={clsx("font-bold",
                data.quant.cmf?.bias === "BULLISH" ? "text-accent-green" :
                data.quant.cmf?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
                {data.quant.cmf?.cmf > 0 ? "+" : ""}{data.quant.cmf?.cmf?.toFixed(3)}
              </div>
              <div className="text-[9px] text-text-muted">{data.quant.cmf?.bias}</div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Heikin Ashi</div>
              <div className={clsx("font-bold",
                data.quant.heikin_ashi?.bias === "BULLISH" ? "text-accent-green" :
                data.quant.heikin_ashi?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
                {data.quant.heikin_ashi?.consecutive_bull}↑ / {data.quant.heikin_ashi?.consecutive_bear}↓
              </div>
              <div className="text-[9px] text-text-muted">last 5 bars</div>
            </div>
            <div>
              <div className="text-[9px] uppercase text-text-muted tracking-wider">Kalman trend</div>
              <div className={clsx("font-bold",
                data.quant.kalman?.trend === "BULLISH" ? "text-accent-green" :
                data.quant.kalman?.trend === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
                {data.quant.kalman?.trend}
              </div>
              <div className="text-[9px] text-text-muted">
                spot vs est {data.quant.kalman?.spot_vs_estimate_pct > 0 ? "+" : ""}{data.quant.kalman?.spot_vs_estimate_pct?.toFixed(2)}%
              </div>
            </div>
          </div>

          {/* Composite verdict */}
          <div className="border-t border-bg-line pt-2 flex items-center justify-between">
            <div className="text-[10px] text-text-muted uppercase">Composite quant verdict</div>
            <div className="flex items-baseline gap-2">
              <span className={clsx("text-xl font-bold tabular",
                data.quant.composite_bias === "BULLISH" ? "text-accent-green" :
                data.quant.composite_bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
                {data.quant.composite_score}
              </span>
              <span className="text-[10px] uppercase">{data.quant.composite_bias}</span>
            </div>
          </div>

          {/* Interpretation list */}
          <ul className="mt-3 space-y-0.5 text-[10px] text-text-muted">
            {data.quant.interpretation?.map((s: string, i: number) => (
              <li key={i}>• {s}</li>
            ))}
          </ul>
        </Panel>
      )}

      {/* ─────── Camarilla + Standard + Fibonacci Pivots ─────── */}
      {data.pivots && !data.pivots.error && (
        <Panel title="Pivot Levels — Camarilla · Standard · Fibonacci"
          right={
            <span className="text-[10px] text-text-muted">
              previous day H {fmt.inr(data.pivots.daily?.prev_high)}
              {" · "}L {fmt.inr(data.pivots.daily?.prev_low)}
              {" · "}C {fmt.inr(data.pivots.daily?.prev_close)}
            </span>
          }>
          {(["daily", "weekly", "monthly"] as const).map((period) => {
            const p = data.pivots[period];
            if (!p || p.error) return null;
            return (
              <div key={period} className="mb-4 last:mb-0">
                <div className="text-[10px] uppercase text-accent-amber font-bold tracking-wider mb-1.5">
                  {period} pivots
                  <span className={clsx("ml-2 text-[10px] px-1.5 py-0.5 rounded font-bold",
                    p.bias === "BULLISH" ? "bg-accent-green/15 text-accent-green" :
                    p.bias === "BEARISH" ? "bg-accent-red/15 text-accent-red" :
                                            "bg-text-muted/15 text-text-muted")}>
                    {p.bias}
                  </span>
                </div>
                <table className="w-full text-[10px] tabular">
                  <thead className="text-text-muted">
                    <tr>
                      <th className="text-left">Level</th>
                      <th className="text-right">Camarilla</th>
                      <th className="text-right">Standard</th>
                      <th className="text-right">Fibonacci</th>
                    </tr>
                  </thead>
                  <tbody>
                    {["r3", "r2", "r1", "pivot", "s1", "s2", "s3"].map((lvl) => {
                      const isResist = lvl.startsWith("r");
                      const isPivot = lvl === "pivot";
                      const c = p.camarilla[lvl], s = p.standard[lvl], f = p.fibonacci[lvl];
                      const last = p.last_price;
                      return (
                        <tr key={lvl} className="border-t border-bg-line">
                          <td className={clsx("py-1 uppercase font-bold",
                            isResist ? "text-accent-red" : isPivot ? "text-accent-amber" : "text-accent-green")}>
                            {lvl}
                          </td>
                          <td className="text-right">
                            <span className={clsx(Math.abs(c - last) / last < 0.003 && "bg-accent-amber/20 text-accent-amber px-1 rounded")}>
                              {c.toFixed(2)}
                            </span>
                          </td>
                          <td className="text-right">
                            <span className={clsx(Math.abs(s - last) / last < 0.003 && "bg-accent-amber/20 text-accent-amber px-1 rounded")}>
                              {s.toFixed(2)}
                            </span>
                          </td>
                          <td className="text-right">
                            <span className={clsx(Math.abs(f - last) / last < 0.003 && "bg-accent-amber/20 text-accent-amber px-1 rounded")}>
                              {f.toFixed(2)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                {period === "daily" && p.nearest_level && (
                  <div className="text-[10px] text-text-muted mt-1.5">
                    Nearest: <span className="text-accent-amber font-bold">
                      {p.nearest_level.method} {p.nearest_level.level} @ ₹{p.nearest_level.price.toFixed(2)}
                    </span>
                    {" · "}{p.distance_to_nearest_pct > 0 ? "+" : ""}{p.distance_to_nearest_pct.toFixed(2)}% away
                  </div>
                )}
              </div>
            );
          })}
          <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2 mt-2">
            Camarilla H3/L3 are the most-watched breakout/breakdown lines. Standard R1/S1 are the most-traded magnets intraday.
          </div>
        </Panel>
      )}

      {/* ─────── Pine-Script Levels (Natural Squares + Fractal Fib) ─────── */}
      {data.pine_levels && (
        <PineLevelsPanel pine={data.pine_levels} spot={data.ltp?.ltp} />
      )}

      {/* ─────── Next-session Gap Forecast ─────── */}
      {data.gap_forecast && !data.gap_forecast.error && (
        <Panel title={`Tomorrow's Gap Forecast — ${data.gap_forecast.next_session_date}`}
          right={
            <span className={clsx("px-2 py-0.5 rounded font-bold uppercase text-[10px]",
              data.gap_forecast.direction === "GAP_UP"   ? "bg-accent-green/20 text-accent-green" :
              data.gap_forecast.direction === "GAP_DOWN" ? "bg-accent-red/20 text-accent-red" :
              data.gap_forecast.direction === "FLAT"     ? "bg-text-muted/20 text-text-muted" :
                                                            "bg-accent-amber/20 text-accent-amber")}>
              {data.gap_forecast.direction.replace("_", " ")}
            </span>
          }>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px] mb-3">
            <Stat label="Expected gap"
                  value={`${data.gap_forecast.expected_gap_pct > 0 ? "+" : ""}${data.gap_forecast.expected_gap_pct}%`}
                  color={data.gap_forecast.expected_gap_pct > 0 ? "text-accent-green" : "text-accent-red"} />
            <Stat label="Expected open" value={`₹${data.gap_forecast.expected_open_price}`} />
            <Stat label="Confidence"   value={`${data.gap_forecast.confidence_pct}%`}
                  color={data.gap_forecast.confidence_pct >= 60 ? "text-accent-green"
                         : data.gap_forecast.confidence_pct >= 40 ? "text-accent-amber"
                         : "text-accent-red"} />
            <Stat label="Confidence band"
                  value={`[${data.gap_forecast.confidence_band[0]}%, ${data.gap_forecast.confidence_band[1]}%]`} />
          </div>
          <div className="text-[10px] text-text-muted mb-2 font-bold uppercase">Driving factors</div>
          <table className="w-full text-[10px]">
            <thead className="text-text-muted">
              <tr><th className="text-left">Factor</th>
                  <th className="text-right">Value</th>
                  <th className="text-right">Contribution</th>
                  <th className="text-left pl-3">Read</th></tr>
            </thead>
            <tbody>
              {data.gap_forecast.drivers.map((d: any, i: number) => (
                <tr key={i} className="border-t border-bg-line">
                  <td className="py-1 text-text-secondary">{d.factor}</td>
                  <td className="py-1 text-right tabular text-text-muted">{d.value}</td>
                  <td className={clsx("py-1 text-right tabular font-bold",
                    d.contribution_pct > 0 ? "text-accent-green" : d.contribution_pct < 0 ? "text-accent-red" : "text-text-muted")}>
                    {d.contribution_pct > 0 ? "+" : ""}{d.contribution_pct}%
                  </td>
                  <td className="py-1 pl-3 text-text-muted">{d.narrative}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.gap_forecast.risk_flags?.length > 0 && (
            <div className="mt-3 space-y-1">
              {data.gap_forecast.risk_flags.map((f: string, i: number) => (
                <div key={i} className="text-[10px] text-accent-amber flex items-start gap-2">
                  <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />
                  <span>{f}</span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-3 text-[10px] text-text-muted italic border-t border-bg-line pt-2">
            {data.gap_forecast.disclaimer}
          </div>
        </Panel>
      )}

      {/* ─────── Options Chain Analytics ─────── */}
      {data.options_analysis && !data.options_analysis.error && (
        <Panel title="Options Chain Analytics"
          right={
            <div className="flex items-center gap-3 text-[10px]">
              <span className={`px-1.5 py-0.5 rounded uppercase font-bold ${
                data.options_analysis.chain_source === "live"
                  ? "bg-accent-green/15 text-accent-green"
                  : "bg-accent-amber/15 text-accent-amber"}`}>
                {data.options_analysis.chain_source} chain
              </span>
              <span className="text-text-muted">expiry: {data.options_analysis.expiry}</span>
            </div>
          }>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-[11px] mb-3">
            <Stat label="PCR"
                  value={data.options_analysis.analytics.pcr}
                  color={data.options_analysis.analytics.pcr > 1.3 ? "text-accent-green"
                         : data.options_analysis.analytics.pcr < 0.7 ? "text-accent-red"
                         : "text-text-muted"} />
            <Stat label="Max pain" value={`₹${data.options_analysis.analytics.max_pain}`} />
            <Stat label="Support wall" value={`₹${data.options_analysis.analytics.support_wall || "—"}`} color="text-accent-green" />
            <Stat label="Resistance wall" value={`₹${data.options_analysis.analytics.resistance_wall || "—"}`} color="text-accent-red" />
            <Stat label="ATM IV"
                  value={`${data.options_analysis.analytics.iv_atm_pct}%`}
                  color={data.options_analysis.analytics.iv_atm_pct < 18 ? "text-accent-green"
                         : data.options_analysis.analytics.iv_atm_pct > 30 ? "text-accent-red"
                         : "text-accent-amber"} />
          </div>
          <div className="text-[10px] text-text-muted mb-2 font-bold uppercase">11 strikes around ATM</div>
          <table className="w-full text-[10px] tabular">
            <thead className="text-text-muted">
              <tr>
                <th className="text-right">CE OI</th>
                <th className="text-right">CE IV</th>
                <th className="text-right">CE LTP</th>
                <th className="text-center">STRIKE</th>
                <th className="text-right">PE LTP</th>
                <th className="text-right">PE IV</th>
                <th className="text-right">PE OI</th>
              </tr>
            </thead>
            <tbody>
              {data.options_analysis.chain_preview
                .sort((a: any, b: any) => a.strike - b.strike)
                .map((r: any) => (
                  <tr key={r.strike} className="border-t border-bg-line">
                    <td className="text-right text-text-secondary">{r.ce_oi || "—"}</td>
                    <td className="text-right text-text-muted">{r.ce_iv ? Number(r.ce_iv).toFixed(1) : "—"}</td>
                    <td className="text-right text-accent-green">{r.ce_ltp ? Number(r.ce_ltp).toFixed(2) : "—"}</td>
                    <td className="text-center font-bold py-0.5">
                      {Math.abs(r.strike - data.ltp.ltp) < 50
                        ? <span className="bg-accent-amber/20 text-accent-amber px-1 rounded">{r.strike}</span>
                        : <span className="text-text-secondary">{r.strike}</span>}
                    </td>
                    <td className="text-right text-accent-red">{r.pe_ltp ? Number(r.pe_ltp).toFixed(2) : "—"}</td>
                    <td className="text-right text-text-muted">{r.pe_iv ? Number(r.pe_iv).toFixed(1) : "—"}</td>
                    <td className="text-right text-text-secondary">{r.pe_oi || "—"}</td>
                  </tr>
                ))}
            </tbody>
          </table>
          <div className="text-[10px] text-text-muted mt-2">
            {data.options_analysis.analytics.institutional_view}
          </div>
        </Panel>
      )}

      {/* ─────── Recommended Options Trade with entry/exit triggers ─────── */}
      {data.options_analysis?.trade_plan && data.options_analysis.trade_plan.strategy !== "WAIT" && (
        <Panel title="Recommended Options Trade"
          right={
            <span className={clsx("px-2 py-0.5 rounded font-bold text-[10px] uppercase",
              data.options_analysis.trade_plan.direction === "BULLISH" ? "bg-accent-green/20 text-accent-green" :
              data.options_analysis.trade_plan.direction === "BEARISH" ? "bg-accent-red/20 text-accent-red" :
                                                                          "bg-accent-amber/20 text-accent-amber")}>
              {data.options_analysis.trade_plan.strategy} · {data.options_analysis.trade_plan.iv_regime} IV
            </span>
          }>
          <div className="text-[11px] text-text-secondary mb-3">
            {data.options_analysis.trade_plan.strategy_subtype}
          </div>

          {/* Legs table */}
          <div className="text-[10px] text-text-muted mb-1 font-bold uppercase">Legs</div>
          <table className="w-full text-[10px] tabular mb-3">
            <thead className="text-text-muted">
              <tr>
                <th className="text-left">Action</th>
                <th className="text-left">Type</th>
                <th className="text-right">Strike</th>
                <th className="text-right">LTP</th>
                <th className="text-right">Δ Delta</th>
                <th className="text-right">Γ Gamma</th>
                <th className="text-right">Θ Theta/d</th>
                <th className="text-right">V Vega</th>
              </tr>
            </thead>
            <tbody>
              {data.options_analysis.trade_plan.legs.map((leg: any, i: number) => (
                <tr key={i} className="border-t border-bg-line">
                  <td className={clsx("font-bold", leg.action === "BUY" ? "text-accent-green" : "text-accent-red")}>
                    {leg.action}
                  </td>
                  <td className="text-text-secondary">{leg.type}</td>
                  <td className="text-right text-text-secondary">{leg.strike}</td>
                  <td className="text-right">{leg.ltp}</td>
                  <td className="text-right text-text-muted">{leg.delta.toFixed(3)}</td>
                  <td className="text-right text-text-muted">{leg.gamma.toFixed(5)}</td>
                  <td className="text-right text-accent-amber">{leg.theta.toFixed(2)}</td>
                  <td className="text-right text-text-muted">{leg.vega.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* P&L envelope */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px] mb-3">
            <Stat label="Net premium"
                  value={`₹${data.options_analysis.trade_plan.net_premium_inr}`}
                  color={data.options_analysis.trade_plan.net_premium_inr < 0 ? "text-accent-red" : "text-accent-green"} />
            <Stat label="Max profit"
                  value={isFinite(data.options_analysis.trade_plan.max_profit_inr)
                          ? `₹${data.options_analysis.trade_plan.max_profit_inr}` : "Unlimited"}
                  color="text-accent-green" />
            <Stat label="Max loss"
                  value={isFinite(data.options_analysis.trade_plan.max_loss_inr)
                          ? `₹${data.options_analysis.trade_plan.max_loss_inr}` : "Unlimited"}
                  color="text-accent-red" />
            <Stat label="R:R"
                  value={data.options_analysis.trade_plan.risk_reward}
                  color={data.options_analysis.trade_plan.risk_reward > 1.5 ? "text-accent-green" : "text-accent-amber"} />
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px] mb-3">
            <Stat label="Suggested lots" value={data.options_analysis.trade_plan.suggested_lots} />
            <Stat label="Capital needed" value={`₹${data.options_analysis.trade_plan.suggested_capital_inr}`} />
            <Stat label="Margin (est.)" value={data.options_analysis.trade_plan.margin_required_inr
                                                ? `₹${data.options_analysis.trade_plan.margin_required_inr}` : "—"} />
            <Stat label="Breakeven(s)" value={data.options_analysis.trade_plan.breakeven_prices.map((b: number) => b.toFixed(1)).join(" / ")} />
          </div>

          {/* Portfolio greeks */}
          <div className="text-[10px] text-text-muted mb-1 font-bold uppercase">Portfolio greeks (net)</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px] mb-3">
            <Stat label="Net Δ" value={data.options_analysis.trade_plan.portfolio_greeks.net_delta} />
            <Stat label="Net Γ" value={data.options_analysis.trade_plan.portfolio_greeks.net_gamma} />
            <Stat label="Net Θ /day" value={`₹${data.options_analysis.trade_plan.portfolio_greeks.net_theta_per_day}`}
                  color={data.options_analysis.trade_plan.portfolio_greeks.net_theta_per_day < 0 ? "text-accent-red" : "text-accent-green"} />
            <Stat label="Net V" value={data.options_analysis.trade_plan.portfolio_greeks.net_vega} />
          </div>

          {/* Triggers */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div className="text-[10px] text-accent-green font-bold uppercase mb-1">▶ Entry triggers</div>
              <ul className="space-y-1">
                {data.options_analysis.trade_plan.entry_triggers.map((t: string, i: number) => (
                  <li key={i} className="text-[11px] text-text-secondary flex gap-2">
                    <span className="text-accent-green">→</span> {t}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-[10px] text-accent-red font-bold uppercase mb-1">■ Exit triggers</div>
              <ul className="space-y-1">
                {data.options_analysis.trade_plan.exit_triggers.map((t: string, i: number) => (
                  <li key={i} className="text-[11px] text-text-secondary flex gap-2">
                    <span className="text-accent-red">→</span> {t}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {data.options_analysis.trade_plan.intraday_notes?.length > 0 && (
            <div className="mt-3 border-t border-bg-line pt-2">
              <div className="text-[10px] text-accent-amber font-bold uppercase mb-1">Intraday notes</div>
              {data.options_analysis.trade_plan.intraday_notes.map((n: string, i: number) => (
                <div key={i} className="text-[10px] text-text-muted">• {n}</div>
              ))}
            </div>
          )}

          <div className="mt-3 text-[10px] text-text-muted italic border-t border-bg-line pt-2">
            {data.options_analysis.trade_plan.disclaimer}
          </div>
        </Panel>
      )}

      {/* Holding plan */}
      {data.holding_plan && (
        <Panel title="Holding Plan"
          right={<span className="text-[10px] text-text-muted">
            best entry: <span className="text-accent-amber">{data.holding_plan.optimal_entry_window?.when?.replace(/_/g, " ")}</span>
          </span>}>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
            <Stat label="Est. days to T1" value={`${data.holding_plan.estimated_days_to_t1}d`} color="text-accent-green" />
            <Stat label="Est. days to T-final" value={`${data.holding_plan.estimated_days_to_t_final}d`} />
            <Stat label="Exit by" value={data.holding_plan.exit_by_date} color="text-accent-red" />
            <Stat label="Best entry" value={data.holding_plan.optimal_entry_window?.when?.replace(/_/g, " ") || "—"} color="text-accent-amber" />
          </div>
          {data.holding_plan.partial_book_schedule?.length > 0 && (
            <div className="text-[10px] text-text-muted mt-3 border-t border-bg-line pt-2">
              Booking schedule:{" "}
              {data.holding_plan.partial_book_schedule.map((s: any, i: number) => (
                <span key={i}>
                  {i > 0 && " · "}
                  <span className="text-accent-amber">{s.book_pct}%</span> @ {s.at_target} ({s.est_date})
                </span>
              ))}
            </div>
          )}
          {data.holding_plan.notes?.map((n: string, i: number) => (
            <div key={i} className="text-[10px] text-accent-amber mt-1">⚠ {n}</div>
          ))}
        </Panel>
      )}

      </>}
      {/* ↑ closes the {viewMode === "advanced" && <> ... } */}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function OHLCCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-bg-panel border border-bg-line rounded px-3 py-2">
      <div className="text-[9px] uppercase text-text-muted tracking-wider">{label}</div>
      <AnimatedNumber value={value || 0} decimals={2}
        className={clsx("text-base font-semibold tabular", color || "text-text-primary")} />
    </div>
  );
}

function TradeCard({ data }: { data: any }) {
  const s = data.strategy;
  const dir = data.direction;
  const sig = s?.strategy === "WAIT" ? "WAIT" : (dir === "BULLISH" ? "BUY" : dir === "BEARISH" ? "SELL" : "HOLD");
  return (
    <div className={clsx("border rounded h-full bg-panel-grad",
      dir === "BULLISH" ? "border-accent-green/40"
      : dir === "BEARISH" ? "border-accent-red/40"
      : "border-bg-line")}>
      <div className="px-3 py-2 border-b border-bg-line flex items-center justify-between">
        <span className="text-[10px] uppercase text-text-muted tracking-wider">Recommendation</span>
        <span className={`text-sm font-bold tracking-wider ${signalColor(sig)}`}>
          {sig} · {fmt.num(data.confidence, 0)}%
        </span>
      </div>
      <div className="p-3 space-y-2">
        <div className="text-[11px] text-accent-amber font-semibold uppercase">{s?.strategy}</div>
        <div className="text-[10px] text-text-secondary">{s?.rationale}</div>

        <div className="grid grid-cols-2 gap-2 text-[11px] pt-2 border-t border-bg-line">
          <div><div className="text-text-muted uppercase text-[9px]">Entry</div><div className="tabular text-text-primary">₹{fmt.inr(s?.entry)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">SL</div><div className="tabular text-accent-red">₹{fmt.inr(s?.stoploss)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Target 1</div><div className="tabular text-accent-green">₹{fmt.inr(s?.targets?.[0])}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">R:R</div><div className="tabular text-text-primary">{fmt.num(s?.risk_reward, 2)}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Qty</div><div className="tabular text-text-primary">{s?.suggested_qty}</div></div>
          <div><div className="text-text-muted uppercase text-[9px]">Capital</div><div className="tabular text-accent-amber">{fmt.num(s?.capital_allocation_pct, 2)}%</div></div>
        </div>

        {s?.instrument_legs?.length > 0 && (
          <div className="text-[10px] text-text-secondary pt-1 border-t border-bg-line">
            <span className="text-text-muted uppercase">Legs:</span>{" "}
            {s.instrument_legs.map((l: any, i: number) =>
              <span key={i} className={l.action === "BUY" ? "text-accent-green" : "text-accent-red"}>
                {l.action} {l.type}@{l.strike}{i < s.instrument_legs.length - 1 ? ", " : ""}
              </span>)}
          </div>
        )}

        {sig !== "WAIT" && sig !== "HOLD" && (
          <button className={clsx("w-full mt-2 py-2 rounded text-sm font-semibold tracking-wider",
            sig === "BUY"
              ? "bg-accent-green/20 text-accent-green hover:bg-accent-green/30"
              : "bg-accent-red/20 text-accent-red hover:bg-accent-red/30")}>
            {sig} {data.symbol} <ArrowRight className="w-3 h-3 inline" />
          </button>
        )}
      </div>
    </div>
  );
}

function AnalyzerTile({ name, icon: Icon, a }: { name: string; icon: any; a: any }) {
  if (!a) {
    return (
      <div className="bg-bg-panel border border-bg-line rounded p-2">
        <div className="flex items-center gap-1 text-[10px] uppercase text-text-muted">
          <Icon className="w-3 h-3" /> {name}
        </div>
        <div className="text-text-muted text-[11px] mt-1">— not trained —</div>
      </div>
    );
  }
  const color = biasColor(a.bias);
  return (
    <div className={clsx("bg-bg-panel border rounded p-2",
      a.bias === "BULLISH" ? "border-accent-green/40"
      : a.bias === "BEARISH" ? "border-accent-red/40"
      : "border-bg-line")}>
      <div className="flex items-center gap-1 text-[10px] uppercase text-text-muted">
        <Icon className="w-3 h-3" /> {name}
      </div>
      <div className="flex items-baseline justify-between mt-1">
        <span className={clsx("text-lg font-bold tabular", color)}>
          {fmt.num(a.score, 0)}
        </span>
        <span className={clsx("text-[9px] uppercase font-bold", color)}>
          {a.bias?.slice(0, 4)}
        </span>
      </div>
      {a.reasons?.[0] && (
        <div className="text-[9px] text-text-muted mt-1 truncate" title={a.reasons[0]}>
          {a.reasons[0]}
        </div>
      )}
    </div>
  );
}

function DayCell({ d }: { d: any }) {
  const gradeColor =
    d.grade === "EXCELLENT" ? "bg-accent-green/20 border-accent-green/50 text-accent-green"
    : d.grade === "GOOD"    ? "bg-accent-green/10 border-accent-green/30 text-accent-green"
    : d.grade === "OK"      ? "bg-bg-panel border-bg-line text-text-secondary"
    : d.grade === "WEAK"    ? "bg-accent-red/10 border-accent-red/30 text-accent-red"
                            : "bg-accent-red/20 border-accent-red/50 text-accent-red";
  return (
    <div className={clsx("border rounded p-2 min-h-[120px]", gradeColor)}>
      <div className="flex items-baseline justify-between">
        <span className="text-text-primary font-bold text-[12px]">{d.weekday.slice(0, 3)}</span>
        <span className="text-text-muted text-[9px]">{d.date.slice(5)}</span>
      </div>
      <div className="text-2xl font-bold tabular my-1">{fmt.num(d.score, 0)}</div>
      <div className="text-[9px] uppercase tracking-wider font-bold">{d.grade}</div>
      <div className="text-[9px] text-text-muted mt-2 border-t border-bg-line/50 pt-1">
        <div className="truncate" title={d.moon_nakshatra}>{d.moon_nakshatra}</div>
        <div className="text-text-muted">{d.day_lord} day · tara {d.tara_from_symbol}</div>
      </div>
      {d.events?.length > 0 && (
        <div className="text-[9px] text-accent-amber mt-1 truncate" title={d.events.join(", ")}>
          ⚡ {d.events[0]}
        </div>
      )}
    </div>
  );
}

function ContextCard({ icon: Icon, label, big, sub, badge, color }:
                      { icon: any; label: string; big: string; sub?: string; badge?: string | null; color: "green" | "red" | "amber" }) {
  const c = color === "green" ? "text-accent-green border-accent-green/40 bg-accent-green/5"
            : color === "red" ? "text-accent-red border-accent-red/40 bg-accent-red/5"
            : "text-accent-amber border-accent-amber/40 bg-accent-amber/5";
  return (
    <div className={clsx("border rounded p-3", c)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[10px] uppercase text-text-muted">
          <Icon className="w-3 h-3" /> {label}
        </div>
        {badge && <PulseBadge color={color === "red" ? "red" : "amber"}>{badge}</PulseBadge>}
      </div>
      <div className="text-xl font-bold mt-1">{big}</div>
      {sub && <div className="text-[10px] text-text-secondary mt-1">{sub}</div>}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────────────
// Horizon Strategy Panel — three tabs (Intraday / Swing / Positional)
// ─────────────────────────────────────────────────────────────────────────────

function HorizonStrategyPanel({ hp }: { hp: any }) {
  const horizons: ("INTRADAY" | "SWING" | "POSITIONAL")[] = ["INTRADAY", "SWING", "POSITIONAL"];
  const recommended = hp.recommended_horizon;
  const [active, setActive] = useState<"INTRADAY" | "SWING" | "POSITIONAL">(
    horizons.includes(recommended) ? recommended : "SWING"
  );
  const plan = hp.plans[active];
  if (!plan) return null;

  const fitColor = plan.fit_rating === "EXCELLENT" ? "text-accent-green"
                   : plan.fit_rating === "GOOD" ? "text-accent-green"
                   : plan.fit_rating === "MARGINAL" ? "text-accent-amber"
                   : "text-accent-red";

  const horizonIcon = (h: string) => h === "INTRADAY" ? Zap : h === "SWING" ? Timer : Calendar;
  const horizonLabel = (h: string) => h === "INTRADAY" ? "Intraday" : h === "SWING" ? "Swing (2-10d)" : "Positional (2-12w)";

  return (
    <Panel title="Per-Horizon Strategy Plans"
      right={<span className="text-[10px] text-text-muted">
        Regime: <span className="text-accent-amber font-bold uppercase">{hp.regime?.replace("_", " ")}</span>
        {" · "}Recommended: <span className="text-accent-green font-bold">{recommended.replace("_", " ")}</span>
      </span>}>

      {/* Tabs */}
      <div className="flex gap-2 mb-4 border-b border-bg-line">
        {horizons.map((h) => {
          const p = hp.plans[h];
          const Icon = horizonIcon(h);
          const isActive = active === h;
          const isRecommended = recommended === h;
          return (
            <button key={h} onClick={() => setActive(h)}
              className={clsx(
                "flex items-center gap-2 px-3 py-2 text-[11px] font-semibold uppercase tracking-wider border-b-2 transition-colors",
                isActive
                  ? "border-accent-amber text-accent-amber"
                  : "border-transparent text-text-muted hover:text-text-primary"
              )}>
              <Icon className="w-3.5 h-3.5" />
              {horizonLabel(h)}
              {isRecommended && <span className="text-[9px] bg-accent-green/20 text-accent-green px-1.5 py-0.5 rounded">★ PICK</span>}
              <span className={clsx("text-[9px] px-1.5 py-0.5 rounded font-bold",
                p.fit_rating === "EXCELLENT" || p.fit_rating === "GOOD"
                  ? "bg-accent-green/15 text-accent-green"
                  : p.fit_rating === "MARGINAL"
                  ? "bg-accent-amber/15 text-accent-amber"
                  : "bg-accent-red/15 text-accent-red")}>
                {Math.round(p.fit_score)}
              </span>
            </button>
          );
        })}
      </div>

      {/* Active plan */}
      <div className="space-y-3">
        {/* Headline strategy */}
        <div className="grid grid-cols-12 gap-3 items-start">
          <div className="col-span-12 md:col-span-8">
            <div className="text-[10px] uppercase text-text-muted tracking-wider">Strategy</div>
            <div className="flex items-baseline gap-2 mt-0.5">
              <span className="text-lg font-bold text-text-primary">{plan.strategy.replace(/_/g, " ")}</span>
              <span className={clsx("text-[10px] px-2 py-0.5 rounded font-bold uppercase",
                plan.recommended
                  ? "bg-accent-green/15 text-accent-green border border-accent-green/40"
                  : "bg-accent-amber/15 text-accent-amber border border-accent-amber/40")}>
                {plan.recommended ? "ACT" : "REVIEW"}
              </span>
            </div>
            <div className="text-[11px] text-text-secondary mt-1">
              {plan.strategy_rationale}
            </div>
            <div className="text-[10px] text-text-muted mt-1">
              <strong>Instrument:</strong> {plan.preferred_instrument}
            </div>
          </div>
          <div className="col-span-12 md:col-span-4 text-right">
            <div className="text-[10px] uppercase text-text-muted tracking-wider">Fit score</div>
            <div className={clsx("text-3xl font-bold tabular", fitColor)}>
              {Math.round(plan.fit_score)}<span className="text-base">/100</span>
            </div>
            <div className={clsx("text-[10px] font-bold uppercase", fitColor)}>{plan.fit_rating}</div>
          </div>
        </div>

        {/* Price levels */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-[11px] border-t border-bg-line pt-3">
          <Stat label="Entry" value={`₹${fmt.inr(plan.entry)}`} />
          <Stat label="Stop loss" value={`₹${fmt.inr(plan.stoploss)}`} color="text-accent-red" />
          <Stat label="T1" value={`₹${fmt.inr(plan.target_1)}`} color="text-accent-green" />
          <Stat label="T2" value={`₹${fmt.inr(plan.target_2)}`} color="text-accent-green" />
          <Stat label="T3" value={`₹${fmt.inr(plan.target_3)}`} color="text-accent-green" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
          <Stat label="R:R at T1" value={plan.risk_reward_t1} />
          <Stat label="R:R at T3" value={plan.risk_reward_t3}
                color={plan.risk_reward_t3 >= 2 ? "text-accent-green" : "text-accent-amber"} />
          <Stat label="Capital %" value={`${plan.suggested_capital_pct}%`} color="text-accent-amber" />
          <Stat label="Max loss" value={`₹${fmt.inr(plan.max_loss_inr)}`} color="text-accent-red" />
        </div>

        {/* Time estimates — the key new feature */}
        <div className="border border-bg-line rounded p-3 bg-bg-base/40">
          <div className="text-[10px] uppercase text-text-muted font-bold tracking-wider mb-2">
            <Timer className="w-3 h-3 inline mr-1" /> Expected holding time
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]">
            <div>
              <div className="text-[9px] text-text-muted">To T1</div>
              <div className="font-bold text-accent-green">
                {plan.expected_bars_to_t1?.toFixed(1)} bars
                <span className="text-[10px] text-text-muted"> · {plan.expected_calendar_days_to_t1?.toFixed(1)}d</span>
              </div>
            </div>
            <div>
              <div className="text-[9px] text-text-muted">To T2</div>
              <div className="font-bold">
                {plan.expected_bars_to_t2?.toFixed(1)} bars
                <span className="text-[10px] text-text-muted"> · {plan.expected_calendar_days_to_t2?.toFixed(1)}d</span>
              </div>
            </div>
            <div>
              <div className="text-[9px] text-text-muted">To T3</div>
              <div className="font-bold">
                {plan.expected_bars_to_t3?.toFixed(1)} bars
                <span className="text-[10px] text-text-muted"> · {plan.expected_calendar_days_to_t3?.toFixed(1)}d</span>
              </div>
            </div>
            <div>
              <div className="text-[9px] text-text-muted">Max hold</div>
              <div className="font-bold text-accent-amber">
                {plan.max_holding_calendar_days?.toFixed(1)}d
              </div>
            </div>
          </div>
        </div>

        {/* Timing rules */}
        <div className="border border-bg-line rounded p-3 text-[11px] space-y-1.5">
          <div className="text-[10px] uppercase text-text-muted font-bold tracking-wider mb-2">
            <Clock className="w-3 h-3 inline mr-1" /> Timing rules
          </div>
          <div className="flex items-start gap-2">
            <CheckCircle2 className="w-3 h-3 text-accent-green shrink-0 mt-0.5" />
            <span><strong>Best entry:</strong> {plan.best_entry_time}</span>
          </div>
          {plan.worst_entry_time && (
            <div className="flex items-start gap-2">
              <XCircle className="w-3 h-3 text-accent-red shrink-0 mt-0.5" />
              <span className="text-accent-red">{plan.worst_entry_time}</span>
            </div>
          )}
          {plan.hard_exit_time && (
            <div className="flex items-start gap-2">
              <Timer className="w-3 h-3 text-accent-amber shrink-0 mt-0.5" />
              <span className="text-accent-amber font-bold">{plan.hard_exit_time}</span>
            </div>
          )}
          <div className="flex items-start gap-2">
            <Sparkles className="w-3 h-3 text-accent-amber shrink-0 mt-0.5" />
            <span className="text-text-secondary"><strong>Hora alignment:</strong> {plan.hora_requirement}</span>
          </div>
          <div className="flex items-start gap-2">
            <Target className="w-3 h-3 text-text-muted shrink-0 mt-0.5" />
            <span className="text-text-secondary"><strong>Review cadence:</strong> {plan.review_cadence}</span>
          </div>
        </div>

        {/* Exit rules */}
        <div className="border border-bg-line rounded p-3">
          <div className="text-[10px] uppercase text-text-muted font-bold tracking-wider mb-2">
            Exit rules ({active.toLowerCase()})
          </div>
          <ol className="space-y-1 text-[11px] text-text-secondary list-decimal list-inside">
            {plan.exit_rules?.map((r: string, i: number) => (
              <li key={i}>{r}</li>
            ))}
          </ol>
        </div>

        {/* Caveats */}
        {plan.caveats?.length > 0 && (
          <div className="border border-accent-amber/30 bg-accent-amber/5 rounded p-3">
            <div className="text-[10px] uppercase text-accent-amber font-bold tracking-wider mb-1">
              <AlertTriangle className="w-3 h-3 inline mr-1" /> Caveats
            </div>
            <ul className="space-y-0.5 text-[10px] text-text-muted">
              {plan.caveats.map((c: string, i: number) => (
                <li key={i}>• {c}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2 mt-3">
        {hp.note}
      </div>
    </Panel>
  );
}


// ─────────────────────────────────────────────────────────────────────────────
// Confidence band panel — engine disagreement visualizer
// ─────────────────────────────────────────────────────────────────────────────

function ConfidenceBandPanel({ cb }: { cb: any }) {
  const qualityColor =
    cb.conviction_quality === "UNANIMOUS" ? "text-accent-green border-accent-green/40 bg-accent-green/5" :
    cb.conviction_quality === "STRONG"    ? "text-accent-green border-accent-green/30 bg-accent-green/5" :
    cb.conviction_quality === "MIXED"     ? "text-accent-amber border-accent-amber/30 bg-accent-amber/5" :
                                              "text-accent-red border-accent-red/30 bg-accent-red/5";

  return (
    <Panel title="Confidence Band  (engine agreement)"
      right={<span className={clsx("px-2 py-0.5 rounded text-[10px] uppercase font-bold border", qualityColor)}>
        {cb.conviction_quality.replace("_", " ")}
      </span>}>
      {/* The band visualization */}
      <div className="mb-3">
        <div className="text-[10px] uppercase text-text-muted tracking-wider mb-1">
          Realistic confidence range
        </div>
        <div className="relative h-7 bg-bg-line/30 rounded overflow-hidden">
          {/* The band as a colored region */}
          <div className="absolute h-full bg-accent-amber/30"
                style={{
                  left: `${cb.lower_bound}%`,
                  width: `${cb.upper_bound - cb.lower_bound}%`,
                }} />
          {/* Point estimate marker */}
          <div className="absolute h-full w-0.5 bg-accent-amber"
                style={{ left: `${cb.point_estimate}%` }} />
          {/* 50% midpoint */}
          <div className="absolute h-full w-px bg-text-muted/40" style={{ left: "50%" }} />
          {/* Labels */}
          <div className="absolute inset-0 flex items-center justify-between px-2 text-[10px] font-bold tabular text-text-primary">
            <span>{cb.lower_bound}%</span>
            <span className="text-accent-amber">{cb.point_estimate}%</span>
            <span>{cb.upper_bound}%</span>
          </div>
        </div>
        <div className="text-[10px] text-text-muted mt-1">
          Band width: {cb.band_width}pp · narrower = more agreement
        </div>
      </div>

      {/* Vote breakdown */}
      <div className="grid grid-cols-3 gap-2 text-[11px] mb-3">
        <div className="text-center">
          <div className="text-[9px] text-text-muted uppercase tracking-wider">Bullish</div>
          <div className="text-accent-green text-xl font-bold tabular">{cb.vote_breakdown?.BULLISH}</div>
        </div>
        <div className="text-center">
          <div className="text-[9px] text-text-muted uppercase tracking-wider">Neutral</div>
          <div className="text-text-secondary text-xl font-bold tabular">{cb.vote_breakdown?.NEUTRAL}</div>
        </div>
        <div className="text-center">
          <div className="text-[9px] text-text-muted uppercase tracking-wider">Bearish</div>
          <div className="text-accent-red text-xl font-bold tabular">{cb.vote_breakdown?.BEARISH}</div>
        </div>
      </div>

      {/* Per-engine list */}
      <div className="border-t border-bg-line pt-2 mb-2">
        <div className="text-[9px] uppercase text-text-muted tracking-wider mb-1">Engines</div>
        <div className="flex flex-wrap gap-1.5 text-[10px]">
          {Object.entries(cb.engine_directions || {}).map(([name, bias]: any) => (
            <span key={name} className={clsx("px-1.5 py-0.5 rounded font-semibold",
              bias === "BULLISH" ? "bg-accent-green/15 text-accent-green" :
              bias === "BEARISH" ? "bg-accent-red/15 text-accent-red" :
                                    "bg-text-muted/15 text-text-secondary")}>
              {name} · {bias[0]}
            </span>
          ))}
        </div>
      </div>

      {/* Sizing multiplier */}
      <div className="grid grid-cols-2 gap-3 text-[11px] mb-2">
        <Stat label="Agreement %" value={`${cb.agreement_pct.toFixed(0)}%`} />
        <Stat label="Sizing × normal"
              value={`${(cb.sizing_multiplier * 100).toFixed(0)}%`}
              color={cb.sizing_multiplier >= 0.75 ? "text-accent-green"
                     : cb.sizing_multiplier >= 0.5 ? "text-accent-amber"
                     : "text-accent-red"} />
      </div>

      <ul className="text-[10px] text-text-muted space-y-0.5 border-t border-bg-line pt-2">
        {cb.interpretation?.slice(0, 5).map((line: string, i: number) => (
          <li key={i}>{line}</li>
        ))}
      </ul>
    </Panel>
  );
}


// ─────────────────────────────────────────────────────────────────────────────
// Session split panel — intraday / overnight / breakout decomposition
// ─────────────────────────────────────────────────────────────────────────────

function SessionSplitPanel({ ss }: { ss: any }) {
  return (
    <Panel title="Session Forecast Split"
      right={<span className="px-2 py-0.5 rounded text-[10px] uppercase font-bold bg-accent-amber/15 text-accent-amber border border-accent-amber/30">
        {ss.most_likely_pattern?.split(" — ")[0]}
      </span>}>
      <div className="space-y-3 text-[11px]">
        {/* Three sub-forecasts */}
        <div className="grid grid-cols-3 gap-2">
          {/* Gap */}
          <div className="border border-bg-line rounded p-2">
            <div className="text-[9px] uppercase text-text-muted tracking-wider mb-0.5">Gap</div>
            <div className={clsx("font-bold text-[12px]",
              ss.gap_direction === "GAP_UP" ? "text-accent-green" :
              ss.gap_direction === "GAP_DOWN" ? "text-accent-red" : "text-text-secondary")}>
              {ss.gap_direction?.replace("_", " ")}
            </div>
            <div className="text-[10px] tabular">
              {ss.gap_pct_expected > 0 ? "+" : ""}{ss.gap_pct_expected}%
            </div>
            <div className="text-[9px] text-text-muted">conf {ss.gap_confidence_pct?.toFixed(0)}%</div>
          </div>
          {/* Daily close */}
          <div className="border border-bg-line rounded p-2">
            <div className="text-[9px] uppercase text-text-muted tracking-wider mb-0.5">Daily close</div>
            <div className={clsx("font-bold text-[12px]",
              ss.daily_direction === "BULLISH" ? "text-accent-green" :
              ss.daily_direction === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
              {ss.daily_direction}
            </div>
            <div className="text-[10px] tabular">
              {ss.daily_close_above_prior_prob_pct?.toFixed(0)}% above prior
            </div>
            <div className="text-[9px] text-text-muted">vs prior close</div>
          </div>
          {/* Breakout */}
          <div className="border border-bg-line rounded p-2">
            <div className="text-[9px] uppercase text-text-muted tracking-wider mb-0.5">Breakout</div>
            <div className={clsx("font-bold text-[12px]",
              ss.breakout_direction === "BREAKOUT_UP" ? "text-accent-green" :
              ss.breakout_direction === "BREAKOUT_DOWN" ? "text-accent-red" : "text-text-secondary")}>
              {ss.breakout_direction?.replace("_", " ")}
            </div>
            <div className="text-[10px] tabular">
              ±{ss.expected_range_pct?.toFixed(2)}% range
            </div>
            <div className="text-[9px] text-text-muted">conf {ss.breakout_confidence_pct?.toFixed(0)}%</div>
          </div>
        </div>

        {/* Bias per trader type */}
        <div className="grid grid-cols-2 gap-2 border-t border-bg-line pt-2">
          <div>
            <div className="text-[9px] uppercase text-text-muted tracking-wider">Intraday traders</div>
            <div className={clsx("text-base font-bold",
              ss.intraday_bias === "LONG" ? "text-accent-green" :
              ss.intraday_bias === "SHORT" ? "text-accent-red" :
              ss.intraday_bias?.includes("FADE") ? "text-accent-amber" : "text-text-secondary")}>
              {ss.intraday_bias?.replace(/_/g, " ")}
            </div>
          </div>
          <div>
            <div className="text-[9px] uppercase text-text-muted tracking-wider">Swing traders</div>
            <div className={clsx("text-base font-bold",
              ss.swing_bias === "LONG" ? "text-accent-green" :
              ss.swing_bias === "SHORT" ? "text-accent-red" : "text-text-secondary")}>
              {ss.swing_bias}
            </div>
          </div>
        </div>

        {/* Pattern */}
        <div className="border-t border-bg-line pt-2 text-[11px]">
          <span className="text-[9px] uppercase text-text-muted tracking-wider">Most likely pattern:</span>
          <div className="text-text-primary font-semibold mt-0.5">{ss.most_likely_pattern}</div>
        </div>

        {/* Interpretation */}
        <ul className="text-[10px] text-text-muted space-y-0.5 border-t border-bg-line pt-2">
          {ss.interpretation?.map((line: string, i: number) => (
            <li key={i} className={clsx(line.startsWith("⚠") && "text-accent-amber font-semibold")}>{line}</li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}


/**
 * Pine-Script ports — integer perfect-square Gann levels + nested fractal Fibonacci.
 *
/**
 * Advanced Technical Analysis — load-bearing TA block that drives the
 * composite confidence shown in the recommendation card.
 *
 * Three sub-engines:
 *   1. VWAP family — institutional reference + ±1σ/±2σ bands
 *   2. RSI / MACD divergence — momentum exhaustion detection
 *   3. Multi-timeframe momentum alignment — direction filter
 *
 * The confluence_count (0..3) is the headline number: how many sub-engines
 * agree on the composite direction. 3/3 is rare-but-high-conviction; 2/3
 * is the standard "decent setup" threshold.
 */
/**
 * MetaLearnerPanel — admin view of the online-learner output.
 *
 * Shows the model's predicted P(win) alongside the rule-based composite
 * confidence so admins can validate that the model is sensible. Pre-warmup
 * (n_samples < 30), the prediction is shown with a "not yet trustworthy"
 * caveat instead of being hidden — useful during dev/QA.
 */
function MetaLearnerPanel({ ml, ruleBasedConf }:
                           { ml: any; ruleBasedConf: number }) {
  const pct = ml.p_win_pct ?? 0;
  const ready = ml.is_trustworthy;
  const samples = ml.n_samples_seen ?? 0;
  const diff = pct - (ruleBasedConf ?? 0);

  return (
    <Panel title="AI win-probability (online meta-learner)"
      right={
        <span className={clsx("text-[10px] px-2 py-0.5 rounded font-bold uppercase",
          ready ? "bg-accent-green/15 text-accent-green"
                : "bg-accent-amber/15 text-accent-amber")}>
          {ready ? "Trained" : `Warmup ${samples}/30`}
        </span>
      }>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="bg-bg-base/40 rounded p-3 border border-bg-line">
          <div className="text-[9px] uppercase text-text-muted tracking-wider">Model P(win)</div>
          <div className={clsx("text-2xl font-black tabular mt-1",
            pct >= 60 ? "text-accent-green" :
            pct >= 50 ? "text-accent-amber" : "text-accent-red")}>
            {pct.toFixed(1)}%
          </div>
          <div className="text-[9px] text-text-muted mt-1">
            16-D logistic regression, online updates
          </div>
        </div>
        <div className="bg-bg-base/40 rounded p-3 border border-bg-line">
          <div className="text-[9px] uppercase text-text-muted tracking-wider">Rule-based composite</div>
          <div className="text-2xl font-black tabular text-text-primary mt-1">
            {ruleBasedConf?.toFixed?.(1) ?? "—"}%
          </div>
          <div className="text-[9px] text-text-muted mt-1">
            Authoritative until model is trusted
          </div>
        </div>
        <div className="bg-bg-base/40 rounded p-3 border border-bg-line">
          <div className="text-[9px] uppercase text-text-muted tracking-wider">Model vs rules</div>
          <div className={clsx("text-2xl font-black tabular mt-1",
            Math.abs(diff) < 5 ? "text-text-secondary" :
            diff > 0 ? "text-accent-green" : "text-accent-red")}>
            {diff > 0 ? "+" : ""}{diff.toFixed(1)}pp
          </div>
          <div className="text-[9px] text-text-muted mt-1">
            {Math.abs(diff) < 5 ? "Agreement"
              : diff > 0 ? "Model more bullish"
                          : "Model more cautious"}
          </div>
        </div>
      </div>
      {!ready && (
        <div className="mt-3 text-[10px] text-text-muted italic border-t border-bg-line pt-2">
          ⏳ The model's prediction is shown for diagnostic purposes only —
          decisions should follow the rule-based composite until the model has
          seen ≥30 evaluated signals.
        </div>
      )}
    </Panel>
  );
}


function AdvancedTaPanel({ ata }: { ata: any }) {
  const v = ata.vwap || {};
  const d = ata.divergence || {};
  const m = ata.mtf_momentum || {};
  const conf = ata.confluence_count || 0;
  const bias = ata.composite_bias || "NEUTRAL";

  const biasColor = bias === "BULLISH" ? "text-accent-green border-accent-green/40 bg-accent-green/5"
                    : bias === "BEARISH" ? "text-accent-red border-accent-red/40 bg-accent-red/5"
                    : "text-text-secondary border-bg-line bg-bg-base/40";

  const conflBadge = conf === 3 ? "bg-accent-green/20 text-accent-green"
                      : conf === 2 ? "bg-accent-amber/20 text-accent-amber"
                      : "bg-bg-base text-text-muted";

  return (
    <Panel title="Advanced TA — VWAP · Divergence · Multi-timeframe momentum"
      right={
        <div className="flex items-center gap-2 text-[10px]">
          <span className={clsx("px-2 py-0.5 rounded font-bold uppercase border", biasColor)}>
            {bias}
          </span>
          <span className={clsx("px-2 py-0.5 rounded font-bold", conflBadge)}>
            {conf}/3 confluence
          </span>
          <span className="text-text-muted font-bold tabular">
            Score {ata.composite_score?.toFixed(1)}
          </span>
        </div>
      }>
      {/* Three sub-engine cards side-by-side */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">

        {/* ---- VWAP ---- */}
        <div className={clsx("border rounded-lg p-3",
          v.bias === "BULLISH" ? "border-accent-green/30 bg-accent-green/5" :
          v.bias === "BEARISH" ? "border-accent-red/30 bg-accent-red/5" :
                                  "border-bg-line bg-bg-base/40")}>
          <div className="flex items-center justify-between mb-1">
            <div className="text-[10px] uppercase font-bold tracking-wider text-text-secondary">
              VWAP
            </div>
            <span className={clsx("text-[9px] uppercase font-bold px-1.5 py-0.5 rounded",
              v.bias === "BULLISH" ? "bg-accent-green/20 text-accent-green" :
              v.bias === "BEARISH" ? "bg-accent-red/20 text-accent-red" :
                                      "bg-bg-base text-text-muted")}>
              {v.bias}
            </span>
          </div>
          <div className="text-base font-bold tabular text-text-primary">
            ₹{v.vwap?.toFixed(2)}
          </div>
          <div className="text-[10px] text-text-muted mb-2">
            Spot {v.distance_pct > 0 ? "+" : ""}{v.distance_pct?.toFixed(2)}% vs VWAP
          </div>
          {/* Bands */}
          <div className="text-[9px] grid grid-cols-2 gap-1 tabular text-text-muted">
            <div>+2σ <span className="text-accent-red">{v.upper_2sigma?.toFixed(2)}</span></div>
            <div>-2σ <span className="text-accent-green">{v.lower_2sigma?.toFixed(2)}</span></div>
            <div>+1σ <span>{v.upper_1sigma?.toFixed(2)}</span></div>
            <div>-1σ <span>{v.lower_1sigma?.toFixed(2)}</span></div>
          </div>
          <div className={clsx("mt-2 text-[9px] inline-block px-1.5 py-0.5 rounded font-bold uppercase",
            v.zone === "ABOVE_2S" || v.zone === "BELOW_2S" ? "bg-accent-amber/20 text-accent-amber" :
            v.zone === "ABOVE_1S" || v.zone === "BULLISH" ? "bg-accent-green/15 text-accent-green" :
            v.zone === "BELOW_1S" || v.zone === "BEARISH" ? "bg-accent-red/15 text-accent-red" :
                                                              "bg-bg-base text-text-muted")}>
            {v.zone?.replace(/_/g, " ")}
          </div>
        </div>

        {/* ---- Divergence ---- */}
        <div className={clsx("border rounded-lg p-3",
          d.bias === "BULLISH" ? "border-accent-green/30 bg-accent-green/5" :
          d.bias === "BEARISH" ? "border-accent-red/30 bg-accent-red/5" :
                                  "border-bg-line bg-bg-base/40")}>
          <div className="flex items-center justify-between mb-1">
            <div className="text-[10px] uppercase font-bold tracking-wider text-text-secondary">
              Divergence
            </div>
            <span className={clsx("text-[9px] uppercase font-bold px-1.5 py-0.5 rounded",
              d.bias === "BULLISH" ? "bg-accent-green/20 text-accent-green" :
              d.bias === "BEARISH" ? "bg-accent-red/20 text-accent-red" :
                                      "bg-bg-base text-text-muted")}>
              {d.bias}
            </span>
          </div>
          <div className="text-base font-bold tabular text-text-primary">
            {d.confirmed_count || 0} / 2
          </div>
          <div className="text-[10px] text-text-muted mb-2">
            indicators showing divergence
          </div>
          {/* Per-indicator status */}
          <div className="text-[10px] space-y-1">
            <div className="flex justify-between border-b border-bg-line/50 pb-0.5">
              <span className="text-text-muted">RSI</span>
              <span className={clsx("font-semibold",
                !d.rsi_divergence ? "text-text-muted" :
                d.rsi_divergence.includes("BULLISH") ? "text-accent-green" : "text-accent-red")}>
                {d.rsi_divergence ? d.rsi_divergence.replace("_", " ").toLowerCase() : "none"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">MACD</span>
              <span className={clsx("font-semibold",
                !d.macd_divergence ? "text-text-muted" :
                d.macd_divergence.includes("BULLISH") ? "text-accent-green" : "text-accent-red")}>
                {d.macd_divergence ? d.macd_divergence.replace("_", " ").toLowerCase() : "none"}
              </span>
            </div>
          </div>
        </div>

        {/* ---- Multi-Timeframe Momentum ---- */}
        <div className={clsx("border rounded-lg p-3",
          m.bias === "BULLISH" ? "border-accent-green/30 bg-accent-green/5" :
          m.bias === "BEARISH" ? "border-accent-red/30 bg-accent-red/5" :
                                  "border-bg-line bg-bg-base/40")}>
          <div className="flex items-center justify-between mb-1">
            <div className="text-[10px] uppercase font-bold tracking-wider text-text-secondary">
              MTF momentum
            </div>
            <span className={clsx("text-[9px] uppercase font-bold px-1.5 py-0.5 rounded",
              m.bias === "BULLISH" ? "bg-accent-green/20 text-accent-green" :
              m.bias === "BEARISH" ? "bg-accent-red/20 text-accent-red" :
                                      "bg-bg-base text-text-muted")}>
              {m.bias}
            </span>
          </div>
          <div className="text-base font-bold tabular">
            <span className={clsx(m.aligned ? "text-accent-green" : "text-text-muted")}>
              {m.aligned ? "✓ Aligned" : "⚠ Conflict"}
            </span>
          </div>
          <div className="text-[10px] text-text-muted mb-2">
            {m.higher_tf_trending ? "Higher TF: trending" : "Higher TF: ranging"}
          </div>
          <div className="text-[10px] space-y-1">
            <div className="flex justify-between border-b border-bg-line/50 pb-0.5">
              <span className="text-text-muted">Short TF</span>
              <span className={clsx("font-semibold tabular",
                m.short_tf_momentum > 0 ? "text-accent-green" :
                m.short_tf_momentum < 0 ? "text-accent-red" : "text-text-muted")}>
                {m.short_tf_momentum > 0 ? "+" : ""}{m.short_tf_momentum?.toFixed(2)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Long TF</span>
              <span className={clsx("font-semibold tabular",
                m.long_tf_momentum > 0 ? "text-accent-green" :
                m.long_tf_momentum < 0 ? "text-accent-red" : "text-text-muted")}>
                {m.long_tf_momentum > 0 ? "+" : ""}{m.long_tf_momentum?.toFixed(2)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Reasons */}
      {ata.reasons?.length > 0 && (
        <ul className="text-[11px] text-text-secondary space-y-1 border-t border-bg-line pt-3">
          {ata.reasons.slice(0, 4).map((r: string, i: number) => (
            <li key={i} className={clsx(
              r.startsWith("⚡") && "text-accent-green font-semibold",
              r.startsWith("✓") && "text-accent-amber font-semibold",
            )}>
              {r}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}


/**
 * Renders two side-by-side blocks:
 *   1. Natural squares (n², where n = floor(√spot))
 *   2. Fractal-Fib confluence zones (clusters where 3+ Fib levels overlap)
 * Both are direct ports of "[A618] Fibonacci and Gann based S/R" Pine Script v4.
 */
function PineLevelsPanel({ pine, spot }: { pine: any; spot?: number }) {
  const ns = pine?.natural_squares;
  const ff = pine?.fractal_fib;
  const nsBroken = !ns || ns.error;
  const ffBroken = !ff || ff.error;
  if (nsBroken && ffBroken) return null;

  return (
    <Panel title="Pine-Script Levels — Natural Squares & Fractal Fibonacci"
      right={<span className="text-[10px] text-text-muted">[A618] port · {spot ? `spot ₹${spot.toFixed(2)}` : ""}</span>}>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* ─────── Natural perfect-square ladder ─────── */}
        {!nsBroken && (
          <div>
            <div className="text-[10px] uppercase text-accent-amber font-bold tracking-wider mb-1.5">
              Gann natural squares (n²)
              <span className="ml-2 text-text-muted normal-case font-normal">
                base n = {ns.base_n} · √spot ≈ {Math.sqrt(ns.spot).toFixed(3)}
              </span>
            </div>
            <table className="w-full text-[10px] tabular">
              <thead className="text-text-muted">
                <tr>
                  <th className="text-left">Role</th>
                  <th className="text-left">Level</th>
                  <th className="text-right">Price (₹)</th>
                  <th className="text-right">Distance</th>
                </tr>
              </thead>
              <tbody>
                {/* Upper levels — highest first */}
                {[...(ns.upper_levels || [])].reverse().map((u: any) => (
                  <tr key={`U${u.k}`} className="border-t border-bg-line">
                    <td className="py-1 uppercase font-bold text-accent-red">R{u.k}</td>
                    <td>{u.n}²</td>
                    <td className="text-right text-accent-red">{u.price.toFixed(2)}</td>
                    <td className="text-right">+{u.distance_pct.toFixed(2)}%</td>
                  </tr>
                ))}
                {/* Zero (n²) — spot sits above */}
                <tr className="border-t border-accent-amber/40 bg-accent-amber/5">
                  <td className="py-1 uppercase font-bold text-accent-amber">ZERO</td>
                  <td>{ns.base_n}²</td>
                  <td className="text-right text-accent-amber font-bold">{ns.zero_level.toFixed(2)}</td>
                  <td className="text-right">+{ns.distance_above_zero_pct.toFixed(2)}%</td>
                </tr>
                {/* Lower levels — closest first */}
                {(ns.lower_levels || []).map((l: any) => (
                  <tr key={`L${l.k}`} className="border-t border-bg-line">
                    <td className="py-1 uppercase font-bold text-accent-green">S{l.k}</td>
                    <td>{l.n}²</td>
                    <td className="text-right text-accent-green">{l.price.toFixed(2)}</td>
                    <td className="text-right">-{l.distance_pct.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="text-[10px] text-text-muted space-y-0.5 border-t border-bg-line pt-2 mt-2">
              {ns.interpretation?.slice(0, 3).map((line: string, i: number) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        )}

        {/* ─────── Fractal Fibonacci confluence zones ─────── */}
        {!ffBroken && (
          <div>
            <div className="text-[10px] uppercase text-accent-amber font-bold tracking-wider mb-1.5">
              Fractal Fib confluence zones
              <span className="ml-2 text-text-muted normal-case font-normal">
                {ff.levels?.length || 0} levels · swing ₹{ff.swing_low?.toFixed(2)}–₹{ff.swing_high?.toFixed(2)}
              </span>
            </div>

            {/* Nearest above + below shortcut */}
            <div className="grid grid-cols-2 gap-2 text-[10px] mb-2">
              <div className="bg-accent-red/5 border border-accent-red/30 rounded p-1.5">
                <div className="text-[9px] uppercase text-text-muted">Nearest above</div>
                <div className="font-bold tabular text-accent-red">
                  ₹{ff.nearest_above?.price?.toFixed(2)} ({ff.nearest_above?.label})
                </div>
                <div className="text-[9px] text-text-muted">
                  {ff.nearest_above?.distance_pct > 0 ? "+" : ""}{ff.nearest_above?.distance_pct?.toFixed(2)}%
                </div>
              </div>
              <div className="bg-accent-green/5 border border-accent-green/30 rounded p-1.5">
                <div className="text-[9px] uppercase text-text-muted">Nearest below</div>
                <div className="font-bold tabular text-accent-green">
                  ₹{ff.nearest_below?.price?.toFixed(2)} ({ff.nearest_below?.label})
                </div>
                <div className="text-[9px] text-text-muted">
                  {ff.nearest_below?.distance_pct?.toFixed(2)}%
                </div>
              </div>
            </div>

            {/* Confluence zones table */}
            {ff.confluence_zones && ff.confluence_zones.length > 0 ? (
              <>
                <div className="text-[9px] uppercase text-text-muted font-bold mb-1">
                  ⚡ Clusters where 3+ Fibs overlap (within 0.3%)
                </div>
                <table className="w-full text-[10px] tabular">
                  <thead className="text-text-muted">
                    <tr>
                      <th className="text-left">#</th>
                      <th className="text-right">Mid (₹)</th>
                      <th className="text-right">Range</th>
                      <th className="text-right">Levels</th>
                      <th className="text-right">Distance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ff.confluence_zones.slice(0, 6).map((z: any, i: number) => (
                      <tr key={i} className="border-t border-bg-line">
                        <td className="py-1 text-accent-amber font-bold">#{i + 1}</td>
                        <td className="text-right font-bold">{z.midpoint.toFixed(2)}</td>
                        <td className="text-right text-text-muted">
                          {z.low.toFixed(2)}–{z.high.toFixed(2)}
                        </td>
                        <td className="text-right">
                          <span className={clsx("px-1.5 py-0.5 rounded font-bold",
                            z.n_levels >= 5 ? "bg-accent-amber/30 text-accent-amber" :
                            z.n_levels >= 4 ? "bg-accent-amber/15 text-accent-amber" :
                                                "bg-bg-base text-text-secondary")}>
                            {z.n_levels}×
                          </span>
                        </td>
                        <td className={clsx("text-right",
                          z.distance_pct_from_spot > 0 ? "text-accent-red" : "text-accent-green")}>
                          {z.distance_pct_from_spot > 0 ? "+" : ""}{z.distance_pct_from_spot.toFixed(2)}%
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            ) : (
              <div className="text-[10px] text-text-muted italic py-2">
                No 3+ Fib overlaps in current swing — levels are well-spaced.
              </div>
            )}

            <ul className="text-[10px] text-text-muted space-y-0.5 border-t border-bg-line pt-2 mt-2">
              {ff.interpretation?.slice(0, 3).map((line: string, i: number) => (
                <li key={i} className={clsx(line.startsWith("⚡") && "text-accent-amber font-semibold")}>{line}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="text-[10px] text-text-muted italic border-t border-bg-line pt-2 mt-3">
        Natural squares = strongest Gann S/R (where √price is a whole number). Fractal-Fib clusters
        = price zones where 3+ retracement/extension ratios overlap — historically high reaction probability.
      </div>
    </Panel>
  );
}

