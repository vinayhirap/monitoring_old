"use client";

import {
  TrendingUp, TrendingDown, Minus, Target, Shield, Clock, ChevronDown, ChevronUp,
  AlertTriangle, BarChart3, Sparkles, ArrowRight, Info, ShieldAlert, Ban,
} from "lucide-react";
import Link from "next/link";
import clsx from "clsx";
import { useState } from "react";
import { fmt } from "@/lib/format";


/**
 * Angel-One-style simple recommendation card.
 * One panel that shows the user everything they need to decide a trade:
 *   • Symbol + live price + day change
 *   • Big BUY / SELL / HOLD label with conviction
 *   • Entry · SL · T1 · T2 · T3 in one row
 *   • 3 plain-English reasons
 *   • One-click "place order" button (paper or live based on broker auth)
 *   • Confidence band (small, honest)
 *   • Collapsible details for the curious user
 *
 * Everything else (Gann panels, quant indicators, calibration) is hidden by
 * default. The Advanced toggle reveals them.
 */
export function SimpleRecommendation({ data, hideAstrology = false }:
                                       { data: any; hideAstrology?: boolean }) {
  const [showDetails, setShowDetails] = useState(false);

  // ---- Derive action — but DEMOTE weak signals to WAIT ----
  const direction = data.direction;                      // BULLISH / BEARISH / NEUTRAL
  const confidence = Math.round(data.confidence || 50);
  const cb = data.confidence_band;                       // confidence band if present

  // Honesty layer: when conviction is too weak OR engines are conflicted,
  // suppress the BUY/SELL label and show WAIT instead. Otherwise the big
  // "SELL" label misleads users into acting on a coin-flip.
  const isWeak       = confidence < 50;
  const isConflicted = cb && (cb.conviction_quality === "CONFLICTED" ||
                                cb.conviction_quality === "MIXED");
  const isLowConviction = isWeak || isConflicted;

  // Map to displayed action. WAIT for low-conviction.
  let action: "BUY" | "SELL" | "WAIT" | "HOLD";
  if (isLowConviction) {
    action = "WAIT";
  } else {
    action = direction === "BULLISH" ? "BUY"
           : direction === "BEARISH" ? "SELL" : "HOLD";
  }

  const conviction = confidence >= 75 ? "STRONG"
                    : confidence >= 60 ? "GOOD"
                    : confidence >= 50 ? "WEAK"
                    : "NO EDGE";

  // ---- Color theme based on (demoted) action ----
  const colorClass = action === "BUY"
    ? "border-accent-green/40 bg-accent-green/5"
    : action === "SELL"
    ? "border-accent-red/40 bg-accent-red/5"
    : action === "WAIT"
    ? "border-accent-amber/40 bg-accent-amber/5"
    : "border-bg-line bg-bg-panel2/30";

  const actionTextColor = action === "BUY" ? "text-accent-green"
                         : action === "SELL" ? "text-accent-red"
                         : action === "WAIT" ? "text-accent-amber"
                         : "text-text-muted";

  const ActionIcon = action === "BUY" ? TrendingUp
                    : action === "SELL" ? TrendingDown
                    : action === "WAIT" ? AlertTriangle
                    : Minus;

  // ---- Pick the swing horizon as the default plan if available ----
  const plan = data.horizon_plans?.plans?.SWING || {};
  const entry = plan.entry || data.ltp?.ltp;
  // Prefer the comprehensive stop_loss_analysis if the backend applied it
  // (more defensible than the strategy's ATR×k). Falls back to plan.stoploss
  // or a sensible default.
  const slBlock = data.stop_loss_analysis;
  const slApplied = slBlock?.applied;
  const sl = plan.stoploss || slBlock?.recommended_sl || data.ltp?.ltp * 0.98;
  const t1 = plan.target_1 || data.ltp?.ltp * 1.015;
  const t2 = plan.target_2 || data.ltp?.ltp * 1.025;
  const t3 = plan.target_3 || data.ltp?.ltp * 1.04;
  const expectedDays = plan.expected_calendar_days_to_t1 || "—";

  // ---- 3 simple reasons (pull the strongest from the engine outputs) ----
  const reasons: string[] = [];
  if (data.analyzers?.technical?.bias === direction) {
    reasons.push(`Technical: ${data.analyzers.technical.reasons?.[0] || "trend confirmed"}`);
  }
  if (data.analyzers?.vedic?.bias === direction && data.analyzers.vedic.reasons?.[0]) {
    // In user portal, label as "Cycle timing" instead of exposing "Vedic"
    const label = hideAstrology ? "Cycle timing" : "Vedic";
    reasons.push(`${label}: ${data.analyzers.vedic.reasons[0].replace(/nakshatra|tara/gi, hideAstrology ? "cycle" : "$&")}`);
  }
  if (data.analyzers?.smc?.bias === direction && data.analyzers.smc.reasons?.[0]) {
    reasons.push(`SMC: ${data.analyzers.smc.reasons[0]}`);
  }
  if (data.options_analysis?.analytics?.institutional_view) {
    reasons.push(`F&O: ${data.options_analysis.analytics.institutional_view}`);
  }
  if (data.gap_forecast?.direction && data.gap_forecast.direction !== "UNCERTAIN") {
    reasons.push(`Tomorrow: ${data.gap_forecast.direction.replace("_", " ")} expected (${data.gap_forecast.confidence_pct}% conf)`);
  }
  const topReasons = reasons.slice(0, 3);

  // ---- Risk-reward ----
  const risk = Math.abs(entry - sl);
  const reward = Math.abs(t1 - entry);
  const rr = risk > 0 ? (reward / risk).toFixed(2) : "—";

  // ---- Suggested options strategy if available ----
  const optStrategy = data.options_analysis?.trade_plan?.strategy;
  const optStrike = data.options_analysis?.trade_plan?.legs?.[0]?.strike;
  const optAction = data.options_analysis?.trade_plan?.legs?.[0]?.action;
  const optType = data.options_analysis?.trade_plan?.legs?.[0]?.type;

  // ============================================================================
  // NEW: clarity layer — the backend's `verdict` block collapses 8 signals
  // into one user-actionable decision. When it's present, we render the
  // clean VerdictCard at the TOP of the card. The existing complex panels
  // remain below for users who want to drill in.
  // ============================================================================
  const verdict = data.verdict;
  const hasNewVerdict = verdict && !verdict.error;

  return (
    <div className={clsx("border-2 rounded-lg p-5 shadow-card", colorClass)}>
      {/* Verdict card — visible WHENEVER the backend produced one and price
          sanity is OK. Everything else in the card is justification for it. */}
      {hasNewVerdict && data.price_sanity?.verdict !== "SUSPECT" && (
        <VerdictCard verdict={verdict} />
      )}

      {/* Price-sanity guard — if the candle close vs broker LTP disagree,
          the entire recommendation is built on wrong data. We OVERRIDE the
          full card with a do-not-trade warning. No analysis is shown when
          SUSPECT — better to refuse than mislead the user into acting on
          stale or wrong-instrument data. */}
      {data.price_sanity?.verdict === "SUSPECT" && (
        <div className="border-2 border-accent-red/60 bg-accent-red/10 rounded p-4 -m-1">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-5 h-5 text-accent-red shrink-0 mt-0.5" />
            <div className="flex-1">
              <div className="font-bold text-accent-red uppercase tracking-wider text-sm mb-1">
                ⚠ Data integrity issue — do not trade off this view
              </div>
              <div className="text-[12px] text-text-secondary">
                The price shown here doesn't match the live broker price. This
                usually means the instrument data is stale (post bonus/split)
                or pointing to the wrong listing. Verify the price on your
                broker terminal before any action.
              </div>
              {data.price_sanity.candle_close && data.price_sanity.broker_ltp && (
                <div className="mt-2 text-[11px] tabular bg-bg-base/40 rounded p-2 inline-block">
                  Candle ₹{data.price_sanity.candle_close}
                  {" vs "}
                  Broker ₹{data.price_sanity.broker_ltp}
                  {" → "}
                  <span className="font-bold">
                    {data.price_sanity.discrepancy_pct?.toFixed(2)}% off
                  </span>
                </div>
              )}
              <div className="mt-2 text-[10px] text-text-muted italic">
                Ask your admin to refresh instruments. Until resolved, the
                recommendation below is hidden because it's unsafe.
              </div>
            </div>
          </div>
        </div>
      )}

      {data.price_sanity?.verdict === "SUSPECT" ? null : <>

      {/* Low-conviction warning — explicit honesty about weak signals */}
      {isLowConviction && (
        <div className="mb-4 p-2.5 rounded bg-accent-amber/10 border border-accent-amber/40 flex items-start gap-2 text-[11px]">
          <AlertTriangle className="w-4 h-4 text-accent-amber shrink-0 mt-0.5" />
          <div>
            <strong className="text-accent-amber">Low conviction signal — system suggests WAIT.</strong>
            <span className="text-text-secondary ml-1">
              Confidence is {confidence}% (below the 50% acting threshold)
              {isConflicted && " and engines are split"}.
              Direction is leaning <span className="font-bold">{direction.toLowerCase()}</span> but
              the data isn't strong enough to act. Wait for stronger confluence.
            </span>
          </div>
        </div>
      )}

      {/* Risk-Guard warnings — discipline enforcer. BLOCKS override even
          the action label below; WARNINGS surface as amber notices but
          let the user decide. */}
      {data.risk_guard && !data.risk_guard.error && (
        <RiskGuardNotice rg={data.risk_guard} />
      )}

      {/* Calibration honesty — show users when confidence is calibrated
          vs raw composite (depending on whether journal had enough data). */}
      {data.confidence_is_calibrated === false && data.confidence_raw != null && (
        <div className="mb-3 text-[10px] text-text-muted italic flex items-center gap-1">
          <Info className="w-3 h-3" />
          Confidence shown is the raw composite. Calibrated probability becomes available
          after the system has ≥300 evaluated signals in the journal.
        </div>
      )}

      {/* Big action label */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-[10px] uppercase text-text-muted tracking-wider">
            Recommendation {isLowConviction && <span className="text-accent-amber">(demoted from {direction === "BULLISH" ? "BUY" : "SELL"})</span>}
          </div>
          <div className="flex items-baseline gap-3 mt-1">
            <span className={clsx("text-5xl font-black", actionTextColor)}>{action}</span>
            <ActionIcon className={clsx("w-8 h-8", actionTextColor)} />
            <div>
              <div className={clsx("text-[10px] uppercase font-bold", actionTextColor)}>{conviction}</div>
              <div className="text-2xl font-bold tabular text-text-primary">{confidence}%</div>
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase text-text-muted tracking-wider">Live price</div>
          <div className="text-3xl font-bold tabular text-text-primary">
            ₹{fmt.inr(data.ltp?.ltp)}
          </div>
          <div className={clsx("text-[11px] font-bold tabular",
            data.ltp?.change >= 0 ? "text-accent-green" : "text-accent-red")}>
            {data.ltp?.change >= 0 ? "+" : ""}{data.ltp?.change?.toFixed(2)} ({data.ltp?.change_pct?.toFixed(2)}%)
          </div>
        </div>
      </div>

      {/* Single-row trade plan */}
      <div className="bg-bg-surface rounded p-3 mb-3 border border-bg-line">
        <div className="text-[9px] uppercase text-text-muted tracking-wider font-bold mb-1.5">
          Trade plan (swing — typical hold {expectedDays} days)
        </div>
        <div className="grid grid-cols-5 gap-2 text-center">
          <div>
            <div className="text-[9px] text-text-muted">ENTRY</div>
            <div className="text-base font-bold tabular text-text-primary">₹{fmt.inr(entry)}</div>
          </div>
          <div>
            <div className="text-[9px] text-accent-red flex items-center justify-center gap-1">
              STOP LOSS
              {slApplied && slBlock?.recommended_method && (
                <span className="text-[8px] uppercase font-normal px-1 rounded bg-accent-amber/20 text-accent-amber"
                       title={slBlock.reasons?.[0]}>
                  {slBlock.recommended_method === "CONFLUENCE"
                    ? `⚡${slBlock.confluence_count}×`
                    : slBlock.recommended_method}
                </span>
              )}
            </div>
            <div className="text-base font-bold tabular text-accent-red">₹{fmt.inr(sl)}</div>
            {slBlock?.distance_pct != null && (
              <div className="text-[9px] text-text-muted">
                -{slBlock.distance_pct.toFixed(2)}% from entry
              </div>
            )}
          </div>
          <div>
            <div className="text-[9px] text-accent-green">T1</div>
            <div className="text-base font-bold tabular text-accent-green">₹{fmt.inr(t1)}</div>
          </div>
          <div>
            <div className="text-[9px] text-accent-green">T2</div>
            <div className="text-base font-bold tabular text-accent-green">₹{fmt.inr(t2)}</div>
          </div>
          <div>
            <div className="text-[9px] text-accent-green">T3</div>
            <div className="text-base font-bold tabular text-accent-green">₹{fmt.inr(t3)}</div>
          </div>
        </div>
        <div className="flex items-center justify-center gap-4 mt-2 pt-2 border-t border-bg-line text-[10px] text-text-muted">
          <span>R:R = <strong className={Number(rr) >= 1.5 ? "text-accent-green" : "text-accent-amber"}>{rr}:1</strong></span>
          <span>•</span>
          <span>Risk per share: ₹{risk.toFixed(2)}</span>
          <span>•</span>
          <span>Reward to T1: ₹{reward.toFixed(2)}</span>
        </div>
      </div>

      {/* Stop-loss reasoning — only when the SL engine produced a real
          multi-method analysis. Shows users WHY the SL is placed where
          it is, plus confluence info if applicable. */}
      {slBlock && !slBlock.error && slBlock.reasons?.length > 0 && (
        <div className="bg-bg-surface/50 rounded p-2.5 mb-3 border border-bg-line text-[10px]">
          <div className="flex items-center justify-between mb-1">
            <div className="text-[9px] uppercase tracking-wider text-text-muted font-bold">
              Stop-loss reasoning
            </div>
            <div className="flex items-center gap-2">
              {slBlock.recommended_method === "CONFLUENCE" && (
                <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded
                                  bg-accent-amber/20 text-accent-amber">
                  ⚡ {slBlock.confluence_count} methods agree
                </span>
              )}
              <span className="text-[9px] text-text-muted">
                {slBlock.recommended_method}
              </span>
            </div>
          </div>
          <ul className="text-text-secondary space-y-0.5">
            {slBlock.reasons.slice(0, 3).map((r: string, i: number) => (
              <li key={i} className={clsx(r.startsWith("⚡") && "text-accent-amber font-semibold")}>
                {r}
              </li>
            ))}
          </ul>
          {slBlock.warnings?.length > 0 && (
            <div className="mt-2 pt-2 border-t border-bg-line/60 text-accent-amber">
              {slBlock.warnings.slice(0, 2).map((w: string, i: number) => (
                <div key={i}>⚠ {w}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Natural-language explanation — when a local LLM is configured
          (LOCAL_LLM_MODEL_PATH env), backend includes `llm_prose` field
          with more fluent output. Otherwise the template-based version
          (headline + body bullets) renders. */}
      {data.explanation && !data.explanation.error && (
        <div className="bg-bg-surface rounded p-3 mb-3 border border-accent-amber/30 text-[12px]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-accent-amber font-bold">
              <Sparkles className="w-3 h-3" />
              Why this signal
            </div>
            {data.explanation.llm_enhanced && (
              <span className="text-[8px] uppercase font-bold px-1 rounded
                                bg-accent-violet/15 text-accent-violet">
                LLM
              </span>
            )}
          </div>
          {data.explanation.llm_prose ? (
            // LLM-fluent path — render the prose as one block
            <div className="text-text-secondary leading-relaxed whitespace-pre-line">
              {data.explanation.llm_prose}
            </div>
          ) : (
            // Template path — headline + bullet body
            <>
              {data.explanation.headline && (
                <div className="font-semibold text-text-primary mb-2">{data.explanation.headline}</div>
              )}
              {data.explanation.body?.length > 0 && (
                <ul className="text-text-secondary space-y-1 leading-relaxed">
                  {data.explanation.body.slice(0, 5).map((s: string, i: number) => (
                    <li key={i}>• {s}</li>
                  ))}
                </ul>
              )}
            </>
          )}
          {data.explanation.cautions?.length > 0 && (
            <div className="mt-2 pt-2 border-t border-bg-line/60 text-accent-amber text-[11px]">
              {data.explanation.cautions.map((c: string, i: number) => (
                <div key={i}>⚠ {c}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Meta-learner (online-AI) prediction — only shown once trustworthy.
          Pure-numpy logistic regression that self-updates per closed signal.
          See `app/services/online_learner.py`. */}
      {data.meta_learner && data.meta_learner.is_trustworthy
        && !data.meta_learner.error && (
        <div className="bg-bg-surface rounded p-3 mb-3 border border-accent-violet/40 text-[11px]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-accent-violet font-bold">
              <Sparkles className="w-3 h-3" /> AI win-probability
            </div>
            <span className="text-[9px] text-text-muted">
              from {data.meta_learner.n_samples_seen} learned signals
            </span>
          </div>
          <div className="flex items-center gap-3">
            {/* Big percentage */}
            <div className={clsx("text-3xl font-black tabular",
              data.meta_learner.p_win_pct >= 60 ? "text-accent-green" :
              data.meta_learner.p_win_pct >= 50 ? "text-accent-amber" :
                                                    "text-accent-red")}>
              {data.meta_learner.p_win_pct.toFixed(1)}%
            </div>
            {/* Bar */}
            <div className="flex-1">
              <div className="w-full h-1.5 bg-bg-base rounded overflow-hidden">
                <div className={clsx("h-full",
                  data.meta_learner.p_win_pct >= 60 ? "bg-accent-green" :
                  data.meta_learner.p_win_pct >= 50 ? "bg-accent-amber" :
                                                        "bg-accent-red")}
                  style={{ width: `${data.meta_learner.p_win_pct}%` }} />
              </div>
              <div className="text-[9px] text-text-muted mt-1">
                Self-learning model trained on actual past outcomes. Read this as
                "P(this setup wins)" — separate from the rule-based confidence.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* AI warm-up notice — shown while the meta-learner is still training */}
      {data.meta_learner && !data.meta_learner.is_trustworthy
        && !data.meta_learner.error
        && (data.meta_learner.n_samples_seen ?? 0) > 0 && (
        <div className="bg-bg-base/40 rounded p-2 mb-3 border border-bg-line text-[10px] text-text-muted">
          <span className="inline-flex items-center gap-1">
            <Sparkles className="w-3 h-3 text-accent-violet" />
            AI model is learning — {data.meta_learner.n_samples_seen} closed signals seen, needs ≥30 before its prediction is shown.
          </span>
        </div>
      )}

      {/* Historical analogs — the offline-AI killer feature. Shows how
          similar setups have RESOLVED in the past, with hit rates and
          average best/worst moves. */}
      {data.historical_analog && !data.historical_analog.error
        && data.historical_analog.has_enough_data && (
        <div className="bg-bg-surface rounded p-3 mb-3 border border-accent-violet/30 text-[11px]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1 text-[9px] uppercase tracking-wider text-accent-violet font-bold">
              <BarChart3 className="w-3 h-3" />
              Historical analogs (past setups like this)
            </div>
            <span className="text-[9px] text-text-muted">
              avg similarity {(data.historical_analog.avg_similarity * 100).toFixed(0)}%
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
            <div className="bg-bg-base/60 rounded p-1.5 text-center">
              <div className="text-[9px] text-text-muted uppercase">Past Setups</div>
              <div className="font-bold text-base tabular text-text-primary">
                {data.historical_analog.outcomes?.n || 0}
              </div>
            </div>
            <div className="bg-bg-base/60 rounded p-1.5 text-center">
              <div className="text-[9px] text-text-muted uppercase">Won</div>
              <div className={clsx("font-bold text-base tabular",
                (data.historical_analog.outcomes?.win_rate || 0) > 0.55 ? "text-accent-green" :
                (data.historical_analog.outcomes?.win_rate || 0) > 0.50 ? "text-accent-amber" :
                                                                            "text-accent-red")}>
                {Math.round((data.historical_analog.outcomes?.win_rate || 0) * 100)}%
              </div>
            </div>
            <div className="bg-bg-base/60 rounded p-1.5 text-center">
              <div className="text-[9px] text-text-muted uppercase">T1 Hit</div>
              <div className="font-bold text-base tabular text-accent-green">
                {Math.round((data.historical_analog.outcomes?.t1_hit_rate || 0) * 100)}%
              </div>
            </div>
            <div className="bg-bg-base/60 rounded p-1.5 text-center">
              <div className="text-[9px] text-text-muted uppercase">Avg MFE</div>
              <div className="font-bold text-base tabular text-accent-green">
                {data.historical_analog.outcomes?.avg_mfe != null
                  ? `${data.historical_analog.outcomes.avg_mfe > 0 ? "+" : ""}${data.historical_analog.outcomes.avg_mfe.toFixed(1)}%`
                  : "—"}
              </div>
            </div>
          </div>

          <div className="text-[10px] text-text-muted italic">
            {data.historical_analog.interpretation}
          </div>
        </div>
      )}

      {/* Candlestick patterns — adds confirmation/exhaustion signal */}
      {data.candlestick_patterns && !data.candlestick_patterns.error
        && data.candlestick_patterns.headline_pattern && (
        <div className="bg-bg-surface/60 rounded p-2.5 mb-3 border border-bg-line text-[10px]">
          <div className="flex items-center justify-between mb-1">
            <div className="text-[9px] uppercase tracking-wider text-text-muted font-bold">
              Candle pattern
            </div>
            <span className={clsx("text-[9px] font-bold uppercase px-1.5 py-0.5 rounded",
              data.candlestick_patterns.composite_bias === "BULLISH" ? "bg-accent-green/20 text-accent-green" :
              data.candlestick_patterns.composite_bias === "BEARISH" ? "bg-accent-red/20 text-accent-red" :
                                                                          "bg-bg-base text-text-muted")}>
              {data.candlestick_patterns.headline_pattern}
            </span>
          </div>
          {data.candlestick_patterns.reasons?.[0] && (
            <div className="text-text-secondary">{data.candlestick_patterns.reasons[0]}</div>
          )}
          {data.candlestick_patterns.confluence_count > 1 && (
            <div className="text-[9px] text-accent-amber mt-1">
              ⚡ {data.candlestick_patterns.confluence_count} candle patterns confirm direction
            </div>
          )}
        </div>
      )}

      {/* F&O quick recommendation (only if available) */}
      {optStrategy && optStrategy !== "WAIT" && optStrike && (
        <div className="bg-bg-surface rounded p-2.5 mb-3 border border-bg-line text-[11px]">
          <div className="text-[9px] uppercase text-accent-amber tracking-wider font-bold mb-1">
            F&O suggestion
          </div>
          <div>
            <span className={clsx("font-bold",
              optAction === "BUY" ? "text-accent-green" : "text-accent-red")}>{optAction}</span>
            {" "}
            <span className="font-bold">{optStrike} {optType}</span>
            {" "}
            <span className="text-text-muted">({optStrategy.replace(/_/g, " ")})</span>
          </div>
        </div>
      )}

      {/* 3 plain-English reasons */}
      {topReasons.length > 0 && (
        <div className="mb-3">
          <div className="text-[9px] uppercase text-text-muted tracking-wider font-bold mb-1.5">
            Why this recommendation
          </div>
          <ul className="space-y-1">
            {topReasons.map((r, i) => (
              <li key={i} className="text-[12px] text-text-secondary flex gap-2">
                <span className={actionTextColor}>✓</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Confidence band (honest line) */}
      {cb && (
        <div className="mb-3 text-[10px] text-text-muted bg-bg-base/50 rounded px-2 py-1.5 border border-bg-line">
          Realistic confidence range: <strong className="text-text-primary">[{cb.lower_bound}% – {cb.upper_bound}%]</strong>
          {" · "}
          Conviction: <strong className={
            cb.conviction_quality === "UNANIMOUS" || cb.conviction_quality === "STRONG"
              ? "text-accent-green"
              : cb.conviction_quality === "MIXED"
              ? "text-accent-amber"
              : "text-accent-red"
          }>{cb.conviction_quality?.replace("_", " ")}</strong>
          {" · "}
          Suggested sizing: <strong>{Math.round((cb.sizing_multiplier || 1) * 100)}% of normal</strong>
        </div>
      )}

      {/* Caveats — show the most important one */}
      {data.validation?.conflicts?.length > 0 && (
        <div className="bg-accent-amber/5 border border-accent-amber/30 rounded p-2 text-[11px] text-accent-amber mb-3">
          ⚠ {data.validation.summary || "Some engines disagree — review before acting"}
        </div>
      )}

      {/* ── Always-visible ADVANCED ANALYSIS summary strip ── */}
      <div className="mt-4 pt-3 border-t border-bg-line">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[10px] uppercase text-text-muted font-bold tracking-wider flex items-center gap-1">
            <BarChart3 className="w-3 h-3 text-accent-amber" />
            Advanced Analysis (always-on)
          </div>
          {data.quant?.regime && (
            <span className={clsx("text-[10px] px-1.5 py-0.5 rounded font-bold uppercase",
              data.quant.regime === "TRENDING" ? "bg-accent-green/15 text-accent-green" :
              data.quant.regime === "MEAN_REVERTING" ? "bg-accent-blue/15 text-accent-blue" :
                                                        "bg-accent-amber/15 text-accent-amber")}>
              Regime: {data.quant.regime.replace("_", " ")}
            </span>
          )}
        </div>

        {/* TOP ROW — Advanced TA composite (VWAP + Divergence + MTF momentum).
            This is the load-bearing technical block that drives the
            recommendation confidence. Shown FIRST because it has the most
            decision value. */}
        {data.advanced_ta && !data.advanced_ta.error && (
          <div className="mb-3 p-2.5 rounded border border-accent-amber/30 bg-accent-amber/5">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[10px] uppercase font-bold tracking-wider text-accent-amber">
                Technical Confluence
              </div>
              <div className="flex items-center gap-2">
                <span className={clsx("text-[10px] px-1.5 py-0.5 rounded font-bold uppercase",
                  data.advanced_ta.composite_bias === "BULLISH" ? "bg-accent-green/20 text-accent-green" :
                  data.advanced_ta.composite_bias === "BEARISH" ? "bg-accent-red/20 text-accent-red" :
                                                                    "bg-bg-base text-text-muted")}>
                  {data.advanced_ta.composite_bias}
                </span>
                <span className={clsx("text-[10px] font-bold px-1.5 py-0.5 rounded",
                  data.advanced_ta.confluence_count === 3 ? "bg-accent-green/20 text-accent-green" :
                  data.advanced_ta.confluence_count === 2 ? "bg-accent-amber/20 text-accent-amber" :
                                                              "bg-bg-base text-text-muted")}>
                  {data.advanced_ta.confluence_count}/3 agree
                </span>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-[10px]">
              {/* VWAP */}
              <div className="bg-bg-base/60 rounded p-1.5">
                <div className="text-text-muted uppercase text-[9px]">VWAP</div>
                <div className={clsx("font-bold tabular text-[11px]",
                  data.advanced_ta.vwap?.bias === "BULLISH" ? "text-accent-green" :
                  data.advanced_ta.vwap?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
                  {data.advanced_ta.vwap?.distance_pct > 0 ? "+" : ""}
                  {data.advanced_ta.vwap?.distance_pct?.toFixed(2)}%
                </div>
                <div className="text-text-muted text-[9px]">
                  {data.advanced_ta.vwap?.zone?.replace(/_/g, " ").toLowerCase() || "—"}
                </div>
              </div>
              {/* Divergence */}
              <div className="bg-bg-base/60 rounded p-1.5">
                <div className="text-text-muted uppercase text-[9px]">Divergence</div>
                <div className={clsx("font-bold tabular text-[11px]",
                  data.advanced_ta.divergence?.bias === "BULLISH" ? "text-accent-green" :
                  data.advanced_ta.divergence?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
                  {data.advanced_ta.divergence?.confirmed_count || 0}/2
                </div>
                <div className="text-text-muted text-[9px]">
                  {data.advanced_ta.divergence?.confirmed_count
                    ? "momentum warning"
                    : "no warning"}
                </div>
              </div>
              {/* MTF Momentum */}
              <div className="bg-bg-base/60 rounded p-1.5">
                <div className="text-text-muted uppercase text-[9px]">MTF Momentum</div>
                <div className={clsx("font-bold tabular text-[11px]",
                  data.advanced_ta.mtf_momentum?.aligned
                    ? (data.advanced_ta.mtf_momentum?.bias === "BULLISH" ? "text-accent-green" : "text-accent-red")
                    : "text-text-muted")}>
                  {data.advanced_ta.mtf_momentum?.aligned ? "✓ Aligned" : "⚠ Mixed"}
                </div>
                <div className="text-text-muted text-[9px]">
                  {data.advanced_ta.mtf_momentum?.higher_tf_trending ? "Trending" : "Ranging"}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
          {/* Technical */}
          <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
            <div className="text-text-muted uppercase tracking-wider">Technical</div>
            <div className={clsx("font-bold text-sm tabular",
              data.analyzers?.technical?.bias === "BULLISH" ? "text-accent-green" :
              data.analyzers?.technical?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
              {data.analyzers?.technical?.score?.toFixed(1) || "—"}
            </div>
            <div className="text-text-muted">{data.analyzers?.technical?.bias || "—"}</div>
          </div>

          {/* SMC */}
          <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
            <div className="text-text-muted uppercase tracking-wider">SMC / ICT</div>
            <div className={clsx("font-bold text-sm tabular",
              data.analyzers?.smc?.bias === "BULLISH" ? "text-accent-green" :
              data.analyzers?.smc?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
              {data.analyzers?.smc?.score?.toFixed(1) || "—"}
            </div>
            <div className="text-text-muted">{data.analyzers?.smc?.bias || "—"}</div>
          </div>

          {/* Gann */}
          <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
            <div className="text-text-muted uppercase tracking-wider">Gann</div>
            <div className={clsx("font-bold text-sm tabular",
              data.analyzers?.gann?.bias === "BULLISH" ? "text-accent-green" :
              data.analyzers?.gann?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
              {data.analyzers?.gann?.score?.toFixed(1) || "—"}
            </div>
            <div className="text-text-muted">
              S {data.analyzers?.gann?.nearest_support?.toFixed(0) || "—"} · R {data.analyzers?.gann?.nearest_resistance?.toFixed(0) || "—"}
            </div>
          </div>

          {/* Vedic / Cycle */}
          <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
            <div className="text-text-muted uppercase tracking-wider">
              {hideAstrology ? "Cycle" : "Vedic"}
            </div>
            <div className={clsx("font-bold text-sm tabular",
              data.analyzers?.vedic?.bias === "BULLISH" ? "text-accent-green" :
              data.analyzers?.vedic?.bias === "BEARISH" ? "text-accent-red" : "text-text-secondary")}>
              {data.analyzers?.vedic?.score?.toFixed(1) || "—"}
            </div>
            <div className="text-text-muted truncate">
              {hideAstrology
                ? (data.analyzers?.vedic?.bias || "—")
                : `${data.analyzers?.vedic?.nakshatra || "—"} · tara ${data.analyzers?.vedic?.tara || "—"}`}
            </div>
          </div>
        </div>

        {/* Second row — Quant indicators + Hora */}
        {(data.quant || data.context?.hora) && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] mt-2">
            {data.quant?.hurst != null && (
              <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
                <div className="text-text-muted uppercase tracking-wider">Hurst</div>
                <div className="font-bold text-sm tabular">{data.quant.hurst.toFixed(3)}</div>
                <div className="text-text-muted">
                  {data.quant.hurst > 0.55 ? "trending" : data.quant.hurst < 0.45 ? "mean-rev" : "random"}
                </div>
              </div>
            )}
            {data.quant?.z_score_20 != null && (
              <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
                <div className="text-text-muted uppercase tracking-wider">Z-20</div>
                <div className={clsx("font-bold text-sm tabular",
                  Math.abs(data.quant.z_score_20) > 2 ? "text-accent-red" : "text-text-secondary")}>
                  {data.quant.z_score_20 > 0 ? "+" : ""}{data.quant.z_score_20.toFixed(2)}σ
                </div>
                <div className="text-text-muted">
                  {Math.abs(data.quant.z_score_20) > 2 ? "extreme" :
                   Math.abs(data.quant.z_score_20) > 1 ? "stretched" : "normal"}
                </div>
              </div>
            )}
            {data.context?.hora && (
              <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
                <div className="text-text-muted uppercase tracking-wider">
                  {hideAstrology ? "Timing window" : "Current hora"}
                </div>
                <div className={clsx("font-bold text-sm",
                  data.context.hora.bias === "bullish" ? "text-accent-green" :
                  data.context.hora.bias === "bearish" ? "text-accent-red" : "text-text-secondary")}>
                  {hideAstrology
                    ? data.context.hora.bias?.toUpperCase()
                    : data.context.hora.ruler}
                </div>
                <div className="text-text-muted">
                  changes in {data.context.hora.next_change_in_minutes}m
                </div>
              </div>
            )}
            {data.gap_forecast?.direction && data.gap_forecast.direction !== "UNCERTAIN" && (
              <div className="bg-bg-base/40 rounded p-2 border border-bg-line/60">
                <div className="text-text-muted uppercase tracking-wider">Tomorrow gap</div>
                <div className={clsx("font-bold text-sm tabular",
                  data.gap_forecast.expected_gap_pct > 0 ? "text-accent-green" : "text-accent-red")}>
                  {data.gap_forecast.expected_gap_pct > 0 ? "+" : ""}{data.gap_forecast.expected_gap_pct}%
                </div>
                <div className="text-text-muted">
                  {data.gap_forecast.direction.replace("_", " ")} · {data.gap_forecast.confidence_pct}% conf
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Prominent link to full advanced analysis ── */}
      {data.symbol && (
        <Link href={`/symbol/${data.symbol}`}
          className="mt-4 flex items-center justify-between p-3 rounded-lg border border-accent-amber/30 bg-accent-amber/5 hover:bg-accent-amber/10 hover:border-accent-amber transition-colors group">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-accent-amber" />
            <div>
              <div className="text-[12px] font-bold text-accent-amber">View Full Advanced Analysis →</div>
              <div className="text-[10px] text-text-muted">
                7-engine breakdown · Gann levels · Camarilla pivots · Vibration · Master 144 ·
                Quant indicators (Hurst/GARCH/OU) · Options chain greeks · Per-horizon plans · Session split
              </div>
            </div>
          </div>
          <ArrowRight className="w-4 h-4 text-accent-amber group-hover:translate-x-1 transition-transform" />
        </Link>
      )}

      {/* Expandable details (inline, secondary) */}
      <button
        onClick={() => setShowDetails(!showDetails)}
        className="w-full text-[10px] text-text-muted hover:text-text-primary uppercase tracking-wider font-bold flex items-center justify-center gap-1 pt-3 mt-3 border-t border-bg-line"
      >
        {showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {showDetails ? "Hide" : "Show"} inline raw data
      </button>

      {showDetails && (
        <div className="mt-3 pt-3 border-t border-bg-line space-y-2 text-[11px]">
          {/* Engine vote breakdown */}
          {cb?.vote_breakdown && (
            <div>
              <span className="text-text-muted">Engine votes:</span>{" "}
              <span className="text-accent-green">{cb.vote_breakdown.BULLISH || 0} bullish</span>
              {" · "}
              <span className="text-text-secondary">{cb.vote_breakdown.NEUTRAL || 0} neutral</span>
              {" · "}
              <span className="text-accent-red">{cb.vote_breakdown.BEARISH || 0} bearish</span>
            </div>
          )}

          {/* Session split if available */}
          {data.session_split?.most_likely_pattern && (
            <div>
              <span className="text-text-muted">Expected pattern:</span>{" "}
              <strong>{data.session_split.most_likely_pattern}</strong>
            </div>
          )}

          {/* Gap forecast */}
          {data.gap_forecast?.direction && data.gap_forecast.direction !== "UNCERTAIN" && (
            <div>
              <span className="text-text-muted">Tomorrow's gap:</span>{" "}
              <strong className={data.gap_forecast.expected_gap_pct > 0 ? "text-accent-green" : "text-accent-red"}>
                {data.gap_forecast.direction.replace("_", " ")} {data.gap_forecast.expected_gap_pct > 0 ? "+" : ""}{data.gap_forecast.expected_gap_pct}%
              </strong>
            </div>
          )}

          {/* Quant regime */}
          {data.quant?.regime && (
            <div>
              <span className="text-text-muted">Quant regime:</span>{" "}
              <strong>{data.quant.regime.replace("_", " ")}</strong>
            </div>
          )}

          {/* Vedic */}
          {data.analyzers?.vedic?.nakshatra && (
            <div>
              <span className="text-text-muted">Vedic:</span>{" "}
              <strong>{data.analyzers.vedic.nakshatra}</strong> ruled by {data.analyzers.vedic.ruler}
              {" · "}tara {data.analyzers.vedic.tara}
            </div>
          )}

          {/* Hora */}
          {data.context?.hora?.ruler && (
            <div>
              <span className="text-text-muted">Current hora:</span>{" "}
              <strong>{data.context.hora.ruler}</strong> ({data.context.hora.bias})
              {" · "}next: {data.context.hora.next_ruler} in {data.context.hora.next_change_in_minutes}m
            </div>
          )}

          <div className="text-[9px] text-text-muted italic pt-2 border-t border-bg-line">
            Educational/analytical platform only. Not SEBI-registered advice.
            Past performance ≠ future results. Verify every recommendation before risking capital.
          </div>
        </div>
      )}

      </>}    {/* End of the SUSPECT-guard wrapper — when price_sanity says SUSPECT,
                 everything above this is skipped and only the red warning shows. */}
    </div>
  );
}


/**
 * RiskGuardNotice — renders the discipline-enforcer verdict.
 *
 * BLOCK   → red full-width banner; user should not take the trade
 * DOWNGRADE_WAIT → amber banner; explain why and let user decide
 * OK (with warnings) → small amber line listing the cautions
 * OK (no warnings) → green pill showing position-sizing summary
 */
function RiskGuardNotice({ rg }: { rg: any }) {
  // Verdict: BLOCK | DOWNGRADE_WAIT | OK
  const verdict = rg.verdict || "OK";
  const reasons: string[] = rg.reasons || [];
  const warnings: string[] = rg.warnings || [];

  if (verdict === "BLOCK") {
    return (
      <div className="mb-4 p-3 rounded bg-accent-red/10 border-2 border-accent-red/50 flex items-start gap-2">
        <Ban className="w-5 h-5 text-accent-red shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="text-[12px] font-bold text-accent-red uppercase tracking-wider mb-1">
            Risk Guard: Trade BLOCKED
          </div>
          <ul className="text-[11px] text-text-secondary space-y-0.5">
            {reasons.map((r, i) => <li key={i}>• {r}</li>)}
            {warnings.map((w, i) => <li key={`w${i}`}>• {w}</li>)}
          </ul>
          {rg.in_circuit_breaker && (
            <div className="mt-2 text-[10px] text-accent-red font-semibold">
              Loss circuit breaker active — {rg.recent_losses} losses in last 5 sessions.
              Trading resumes tomorrow.
            </div>
          )}
        </div>
      </div>
    );
  }

  if (verdict === "DOWNGRADE_WAIT" || warnings.length > 0) {
    return (
      <div className="mb-3 p-2.5 rounded bg-accent-amber/10 border border-accent-amber/40 flex items-start gap-2">
        <ShieldAlert className="w-4 h-4 text-accent-amber shrink-0 mt-0.5" />
        <div className="flex-1">
          <div className="text-[11px] font-bold text-accent-amber mb-0.5">
            Risk Guard: Caution
          </div>
          <ul className="text-[10px] text-text-secondary space-y-0.5">
            {warnings.map((w, i) => <li key={i}>{w}</li>)}
            {reasons.filter(r => !r.startsWith("Position sizing OK")).map((r, i) => (
              <li key={`r${i}`}>{r}</li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  // OK — show position-sizing summary as a green pill
  return (
    <div className="mb-3 p-2 rounded bg-accent-green/5 border border-accent-green/30 flex items-center justify-between text-[11px]">
      <div className="flex items-center gap-2 text-text-secondary">
        <Shield className="w-3.5 h-3.5 text-accent-green" />
        <span>
          Risk-OK · {rg.suggested_quantity} qty · ₹{Math.round(rg.risk_amount_rs).toLocaleString("en-IN")} risk
          ({rg.risk_pct_of_capital?.toFixed(2)}% of capital) · R:R {rg.risk_reward_ratio}:1
        </span>
      </div>
      {rg.portfolio_open_risk_pct > 0 && (
        <span className="text-text-muted text-[10px]">
          Portfolio: {rg.portfolio_open_risk_pct.toFixed(1)}% open · {rg.portfolio_room_remaining_pct.toFixed(1)}% room
        </span>
      )}
    </div>
  );
}


/**
 * VerdictCard — the single user-actionable card.
 *
 * Format:
 *   [BIG VERDICT PILL]   "Strong BUY signal"        [conviction stars]
 *                        "AI agrees (62%), 3/3 advanced-TA confluence"
 *   ─────────────────────────────────────────────────────────────────
 *   Entry  ₹2,847    SL  ₹2,820    T1  ₹2,890    Qty 23
 *   ─────────────────────────────────────────────────────────────────
 *   ⚠ What we don't know yet:
 *     · Historical-analog data still accumulating
 *     · AI meta-learner is in warmup (12/30 samples)
 *
 * No engine internals. No 8 different signals to synthesise. ONE decision.
 */
function VerdictCard({ verdict }: { verdict: any }) {
  const v: string = verdict.verdict || "WATCH";
  const conviction: string = verdict.conviction || "NONE";
  const plan = verdict.trade_plan;
  const sizing = verdict.sizing;
  const caveats: string[] = verdict.caveats || [];

  // Big colored pill style based on verdict
  const styleMap: Record<string, { bg: string; text: string; ring: string }> = {
    STRONG_BUY:  { bg: "bg-accent-green",        text: "text-white", ring: "ring-accent-green" },
    BUY:         { bg: "bg-accent-green/20",     text: "text-accent-green", ring: "ring-accent-green/40" },
    STRONG_SELL: { bg: "bg-accent-red",          text: "text-white", ring: "ring-accent-red" },
    SELL:        { bg: "bg-accent-red/20",       text: "text-accent-red", ring: "ring-accent-red/40" },
    WATCH:       { bg: "bg-accent-amber/15",     text: "text-accent-amber", ring: "ring-accent-amber/40" },
    WAIT:        { bg: "bg-bg-base",             text: "text-text-muted", ring: "ring-bg-line" },
    AVOID:       { bg: "bg-accent-red",          text: "text-white", ring: "ring-accent-red" },
  };
  const style = styleMap[v] || styleMap.WAIT;

  const convictionStars = conviction === "STRONG" ? 5 :
                          conviction === "MEDIUM" ? 4 :
                          conviction === "WEAK"   ? 2 : 0;

  const showPlan = plan && plan.entry && (v.includes("BUY") || v.includes("SELL"));

  return (
    <div className="mb-5 p-4 rounded-lg bg-bg-base/50 border-2 border-bg-line">
      {/* Top row: big pill + conviction stars */}
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="flex-1 min-w-0">
          <div className={clsx("inline-block px-4 py-1.5 rounded font-black text-lg tracking-wider",
              style.bg, style.text)}>
            {v.replace(/_/g, " ")}
          </div>
          <div className="mt-2 text-base font-semibold text-text-primary">
            {verdict.headline}
          </div>
          <div className="mt-1 text-[12px] text-text-secondary leading-relaxed">
            {verdict.one_line_reason}
          </div>
        </div>
        <div className="text-right shrink-0">
          {convictionStars > 0 && (
            <>
              <div className="text-[9px] uppercase font-bold text-text-muted tracking-wider mb-1">
                Conviction
              </div>
              <div className="flex justify-end">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Star key={i} className={clsx("w-3.5 h-3.5",
                    i < convictionStars ? "fill-accent-amber text-accent-amber" : "text-text-muted/30")} />
                ))}
              </div>
            </>
          )}
          <div className="mt-2 text-[10px] text-text-muted">
            <span className={clsx("font-bold",
              verdict.confidence_pct >= 70 ? "text-accent-green" :
              verdict.confidence_pct >= 55 ? "text-accent-amber" : "text-text-muted")}>
              {verdict.confidence_pct?.toFixed?.(0)}%
            </span>
            {" "}confidence
            {verdict.confidence_is_calibrated && (
              <span className="ml-1 text-[9px] uppercase text-accent-violet font-bold">
                calibrated
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Trade plan strip — only when actionable */}
      {showPlan && (
        <div className="space-y-2">
          {/* Trigger banner — shows WHY this entry, not just the number.
              e.g. "PULLBACK · Buy on pullback to Gann support ₹2,820–₹2,847" */}
          {plan.trigger_type && plan.trigger_type !== "MARKET" && (
            <div className={clsx(
              "flex items-start gap-2 px-3 py-2 rounded text-[11px] border",
              plan.trigger_type === "BREAKOUT"
                ? "bg-accent-amber/5 border-accent-amber/30 text-accent-amber"
                : "bg-accent-blue/5 border-accent-blue/30 text-accent-blue",
            )}>
              <span className="font-bold uppercase tracking-wider text-[10px] shrink-0">
                {plan.trigger_type}
              </span>
              <span className="text-text-primary">{plan.trigger_note}</span>
            </div>
          )}

          {/* Candle confirmation badge — surfaces whether momentum confirms direction */}
          {plan.candle_confirmation?.note && plan.candle_confirmation.required > 0 && (
            <div className={clsx(
              "flex items-center gap-1.5 text-[10px] px-2 py-1 rounded border w-fit",
              plan.candle_confirmation.confirmed
                ? "border-accent-green/30 text-accent-green bg-accent-green/5"
                : "border-accent-amber/30 text-accent-amber bg-accent-amber/5",
            )}>
              {plan.candle_confirmation.confirmed ? "✓" : "⚠"}{" "}
              {plan.candle_confirmation.note}
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 py-3 px-3 rounded bg-bg-surface border border-bg-line">
            <PlanCell label="Entry" value={plan.entry} />
            <PlanCell label="Stop loss" value={plan.stoploss} color="text-accent-red" />
            <PlanCell label="Target 1" value={plan.target_1} color="text-accent-green" />
            {plan.target_2 && <PlanCell label="Target 2" value={plan.target_2} color="text-accent-green" />}
            {sizing?.quantity != null && (
              <PlanCell label={`Qty (${sizing.risk_pct_of_capital?.toFixed(1)}% risk)`}
                        value={sizing.quantity}
                        asInt
                        color="text-accent-amber" />
            )}
          </div>

          {/* Entry-zone band — shows the acceptable price range for the trigger */}
          {plan.entry_zone && plan.entry_zone.low && plan.entry_zone.high && (
            <div className="text-[10px] text-text-muted px-1">
              Acceptable entry band: ₹{Number(plan.entry_zone.low).toLocaleString("en-IN")}
              {" – "}
              ₹{Number(plan.entry_zone.high).toLocaleString("en-IN")}
              {plan.entry_zone.anchor && plan.entry_zone.anchor !== "MARKET" && (
                <span className="ml-1 text-text-secondary">
                  (anchor: {plan.entry_zone.anchor.toLowerCase().replace(/_/g, " ")})
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Honest caveats — "what we don't know yet" */}
      {caveats.length > 0 && (
        <div className="mt-3 pt-3 border-t border-bg-line text-[10px] text-text-muted">
          <div className="flex items-center gap-1 text-[9px] uppercase font-bold tracking-wider mb-1">
            <Info className="w-3 h-3" />
            What we don't know yet
          </div>
          <ul className="space-y-0.5 leading-relaxed">
            {caveats.slice(0, 4).map((c: string, i: number) => (
              <li key={i}>· {c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}


function PlanCell({ label, value, color, asInt }:
                    { label: string; value: any; color?: string; asInt?: boolean }) {
  if (value == null) return <div />;
  const display = asInt
    ? String(Math.round(Number(value)))
    : `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return (
    <div>
      <div className="text-[9px] uppercase text-text-muted tracking-wider">{label}</div>
      <div className={clsx("text-sm font-bold tabular mt-0.5", color || "text-text-primary")}>
        {display}
      </div>
    </div>
  );
}
