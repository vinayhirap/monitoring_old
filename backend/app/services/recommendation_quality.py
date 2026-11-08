"""Recommendation Quality — the clarity layer.

Why this exists:

A `/api/symbol/{ticker}` response contains roughly 8 independent quality
signals: rule-based confidence, calibrated confidence, AI P(win),
risk-guard verdict, price-sanity verdict, conviction-quality, historical
analog stats, stop-loss method. Asking the user to synthesise these into
"should I take this trade?" is unfair.

This module is the responsibility-bearing layer. It ingests all signals
and emits ONE clear verdict the user can act on:

  STRONG_BUY · BUY · WATCH · WAIT · SELL · STRONG_SELL · AVOID

Plus one short reason. Plus an honest list of what the system does NOT
know yet (e.g. "AI is still learning — only 12 of 30 samples").

Design philosophy:
  • If price data is suspect → AVOID, no exceptions
  • If risk guard blocks → AVOID
  • If R:R below 1.2:1 → WAIT (math doesn't favour the trade)
  • If signal conviction is high AND confluence agrees → STRONG_*
  • If signals conflict → WATCH (look, don't trade yet)
  • If confidence < 50 → WAIT (no edge)

The verdict is calibrated to be CONSERVATIVE. Marginal setups become WATCH,
not BUY. The platform is honest about uncertainty rather than dressing
weak signals as actionable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Verdict = Literal[
    "STRONG_BUY", "BUY", "WATCH", "WAIT",
    "SELL", "STRONG_SELL", "AVOID",
]
Conviction = Literal["STRONG", "MEDIUM", "WEAK", "NONE"]


@dataclass
class RecommendationQuality:
    """Single verdict that a user can act on. Everything below this object
    is justification + details for the curious."""
    verdict: Verdict
    conviction: Conviction
    headline: str                   # 1-line user-facing summary
    one_line_reason: str            # the single most load-bearing reason
    confidence_pct: float           # the number we display (calibrated if available)
    confidence_is_calibrated: bool
    # Trust signals — surfaced for honest UI display
    trust_signals: dict = field(default_factory=dict)
    # List of things the system doesn't know yet
    caveats: list[str] = field(default_factory=list)
    # Trade plan (entry/SL/T1) when actionable; None when verdict is WAIT/AVOID
    trade_plan: dict | None = None
    # Risk guard verdict pass-through (so UI can show sizing if OK)
    sizing: dict | None = None

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# The decision rules — read top to bottom; FIRST match wins
# ---------------------------------------------------------------------------

def assess(symbol_data: dict) -> RecommendationQuality:
    """Take the full /api/symbol/{ticker} response and produce ONE verdict.

    This is the only place that needs to know about all 8 sub-signals.
    Callers (frontend, alerts, Telegram bot) just read `verdict` + headline.
    """
    # ---- Extract all signals defensively ----
    direction        = symbol_data.get("direction", "NEUTRAL")
    confidence       = float(symbol_data.get("confidence", 50) or 50)
    confidence_raw   = float(symbol_data.get("confidence_raw", confidence) or confidence)
    is_calibrated    = bool(symbol_data.get("confidence_is_calibrated", False))
    price_sanity     = (symbol_data.get("price_sanity") or {}).get("verdict", "OK")
    risk_guard       = (symbol_data.get("risk_guard") or {})
    risk_verdict     = risk_guard.get("verdict", "OK")
    risk_rr          = risk_guard.get("risk_reward_ratio")
    risk_reasons     = risk_guard.get("reasons") or []
    risk_warnings    = risk_guard.get("warnings") or []
    confidence_band  = symbol_data.get("confidence_band") or {}
    conviction_qual  = confidence_band.get("conviction_quality", "")
    advanced_ta      = symbol_data.get("advanced_ta") or {}
    ata_confluence   = advanced_ta.get("confluence_count", 0)
    ata_bias         = advanced_ta.get("composite_bias")
    historical_analog = symbol_data.get("historical_analog") or {}
    ha_outcomes      = historical_analog.get("outcomes") or {}
    ha_n             = ha_outcomes.get("n", 0)
    ha_win_rate      = ha_outcomes.get("win_rate", 0)
    ha_ready         = bool(historical_analog.get("has_enough_data"))
    meta_learner     = symbol_data.get("meta_learner") or {}
    ai_p_win         = meta_learner.get("p_win", 0.5)
    ai_trustworthy   = bool(meta_learner.get("is_trustworthy", False))

    strategy         = symbol_data.get("strategy") or {}
    stop_loss        = symbol_data.get("stop_loss_analysis") or {}

    trust_signals = {
        "price_sanity":           price_sanity,
        "calibrated":             is_calibrated,
        "ai_trustworthy":         ai_trustworthy,
        "historical_data":        ha_ready,
        "ai_p_win":               round(ai_p_win * 100, 1) if ai_trustworthy else None,
        "advanced_ta_confluence": f"{ata_confluence}/3",
        "rule_based_confidence":  round(confidence, 1),
        "risk_reward":            risk_rr,
    }

    # ===== HARD BLOCKS — any one of these and we AVOID the trade =====

    # 1. Price data can't be trusted → user must not act on this
    if price_sanity == "SUSPECT":
        return RecommendationQuality(
            verdict="AVOID",
            conviction="NONE",
            headline="DO NOT TRADE — price data is suspect",
            one_line_reason=(
                "The price the platform sees doesn't match the live broker price. "
                "Likely a stale instrument mapping. Refresh scrip master and retry."
            ),
            confidence_pct=0,
            confidence_is_calibrated=False,
            trust_signals=trust_signals,
            caveats=["Price sanity check FAILED — see red banner above for details"],
            trade_plan=None,
        )

    # 2. Risk guard fully blocked (e.g. loss circuit breaker, no viable sizing)
    if risk_verdict == "BLOCK":
        reason = (risk_reasons[0] if risk_reasons else "Risk guard refused this setup")
        return RecommendationQuality(
            verdict="AVOID",
            conviction="NONE",
            headline="BLOCKED by risk guard",
            one_line_reason=reason,
            confidence_pct=confidence,
            confidence_is_calibrated=is_calibrated,
            trust_signals=trust_signals,
            caveats=risk_reasons + risk_warnings,
            trade_plan=None,
        )

    # ===== SOFT GATES — these reduce to WATCH or WAIT =====

    # 3. No directional signal at all
    if direction == "NEUTRAL" or direction == "SIDEWAYS":
        return RecommendationQuality(
            verdict="WATCH",
            conviction="NONE",
            headline="No clear direction — watch only",
            one_line_reason="The engines don't agree on direction right now. Wait for a clearer setup.",
            confidence_pct=confidence,
            confidence_is_calibrated=is_calibrated,
            trust_signals=trust_signals,
            caveats=_default_caveats(ha_ready, ai_trustworthy, is_calibrated),
            trade_plan=None,
        )

    # 4. Confidence below acting threshold
    if confidence < 50:
        return RecommendationQuality(
            verdict="WAIT",
            conviction="NONE",
            headline=f"No edge ({confidence:.0f}% confidence)",
            one_line_reason=(
                f"Confidence is {confidence:.0f}% — below the 50% acting threshold. "
                f"The system has no measurable edge on this setup right now."
            ),
            confidence_pct=confidence,
            confidence_is_calibrated=is_calibrated,
            trust_signals=trust_signals,
            caveats=_default_caveats(ha_ready, ai_trustworthy, is_calibrated),
            trade_plan=None,
        )

    # 5. Engines conflict — no single direction has confluence
    if conviction_qual in ("CONFLICTED", "MIXED"):
        return RecommendationQuality(
            verdict="WATCH",
            conviction="WEAK",
            headline="Engines disagree — watch only",
            one_line_reason=(
                "Multiple engines are pulling in opposite directions. "
                "Confluence is poor — wait for them to align."
            ),
            confidence_pct=confidence,
            confidence_is_calibrated=is_calibrated,
            trust_signals=trust_signals,
            caveats=_default_caveats(ha_ready, ai_trustworthy, is_calibrated),
            trade_plan=None,
        )

    # 6. Risk guard wants us to wait (e.g. R:R below 1.2)
    if risk_verdict == "DOWNGRADE_WAIT":
        reason = (risk_warnings[0] if risk_warnings
                    else f"Reward:risk ratio only {risk_rr}:1 — math doesn't favour the trade")
        return RecommendationQuality(
            verdict="WAIT",
            conviction="WEAK",
            headline=f"Wait — R:R {risk_rr}:1",
            one_line_reason=reason,
            confidence_pct=confidence,
            confidence_is_calibrated=is_calibrated,
            trust_signals=trust_signals,
            caveats=_default_caveats(ha_ready, ai_trustworthy, is_calibrated),
            trade_plan=None,
        )

    # ===== ACTIONABLE — verdict + conviction =====

    is_buy = (direction == "BULLISH")
    base_verdict = "BUY" if is_buy else "SELL"

    # Promote to STRONG when multiple high-quality signals agree
    promotions = 0
    promotion_reasons: list[str] = []

    # Promotion 1: ATA confluence 3/3
    if ata_confluence == 3 and ata_bias == direction:
        promotions += 1
        promotion_reasons.append("3/3 advanced-TA confluence")

    # Promotion 2: AI prediction agrees AND is trustworthy
    if ai_trustworthy:
        ai_says_bull = ai_p_win > 0.55
        ai_says_bear = ai_p_win < 0.45
        if (is_buy and ai_says_bull) or (not is_buy and ai_says_bear):
            promotions += 1
            promotion_reasons.append(f"AI agrees ({ai_p_win*100:.0f}%)")

    # Promotion 3: Historical analogs strongly favour this direction
    if ha_ready and ha_n >= 8 and ha_win_rate >= 0.60:
        promotions += 1
        promotion_reasons.append(f"Historical analogs win {ha_win_rate*100:.0f}% of the time")

    # Promotion 4: Calibrated + high confidence
    if is_calibrated and confidence >= 70:
        promotions += 1
        promotion_reasons.append(f"Calibrated confidence {confidence:.0f}%")

    # Map promotions to conviction + verdict
    if promotions >= 3:
        conviction: Conviction = "STRONG"
        verdict_str = f"STRONG_{base_verdict}"
    elif promotions >= 2:
        conviction = "MEDIUM"
        verdict_str = base_verdict
    elif promotions >= 1:
        conviction = "WEAK"
        verdict_str = base_verdict
    elif confidence >= 60:
        conviction = "WEAK"
        verdict_str = base_verdict
    else:
        # Borderline — show as WATCH
        return RecommendationQuality(
            verdict="WATCH",
            conviction="WEAK",
            headline=f"Soft {base_verdict.lower()} bias — watch for confirmation",
            one_line_reason=(
                f"Direction is {direction.lower()} at {confidence:.0f}% but no engine "
                f"is strongly confirming yet. Wait for confluence or take a small starter position."
            ),
            confidence_pct=confidence,
            confidence_is_calibrated=is_calibrated,
            trust_signals=trust_signals,
            caveats=_default_caveats(ha_ready, ai_trustworthy, is_calibrated),
            trade_plan=None,
        )

    # Build the one-line reason — chain the strongest promotions
    if promotion_reasons:
        one_line_reason = (
            f"{conviction.title()} {base_verdict.lower()} signal — "
            + ", ".join(promotion_reasons[:2])
            + "."
        )
    else:
        one_line_reason = (
            f"{base_verdict.title()} signal at {confidence:.0f}% confidence — "
            f"rule-based composite without external confirmation yet."
        )

    headline = {
        "STRONG_BUY":  "Strong BUY signal",
        "BUY":         "BUY signal",
        "STRONG_SELL": "Strong SELL signal",
        "SELL":        "SELL signal",
    }.get(verdict_str, verdict_str)

    # Trade plan — pulled from strategy + risk_guard sizing.
    # Now includes the smart-entry trigger context (PULLBACK / BREAKOUT / MARKET)
    # so the UI can render "Buy on pullback to ₹X (Gann support)" rather than
    # echoing the LTP back as the entry price.
    trade_plan = None
    if strategy.get("entry"):
        trade_plan = {
            "entry":      strategy.get("entry"),
            "stoploss":   strategy.get("stoploss"),
            "target_1":   (strategy.get("targets") or [None])[0],
            "target_2":   (strategy.get("targets") or [None, None])[1]
                            if len(strategy.get("targets") or []) > 1 else None,
            "target_3":   (strategy.get("targets") or [None, None, None])[2]
                            if len(strategy.get("targets") or []) > 2 else None,
            "sl_method":  stop_loss.get("recommended_method", "ATR"),
            # Smart-entry geometry — added in strategy.py:_smart_entry
            "trigger_type":         strategy.get("trigger_type", "MARKET"),
            "trigger_note":         strategy.get("trigger_note", ""),
            "entry_zone":           strategy.get("entry_zone") or {},
            "candle_confirmation":  strategy.get("candle_confirmation") or {},
        }

    sizing = None
    if risk_verdict == "OK":
        sizing = {
            "quantity":            risk_guard.get("suggested_quantity"),
            "risk_amount_rs":      risk_guard.get("risk_amount_rs"),
            "risk_pct_of_capital": risk_guard.get("risk_pct_of_capital"),
            "rr":                  risk_rr,
        }

    return RecommendationQuality(
        verdict=verdict_str,    # type: ignore
        conviction=conviction,
        headline=headline,
        one_line_reason=one_line_reason,
        confidence_pct=confidence,
        confidence_is_calibrated=is_calibrated,
        trust_signals=trust_signals,
        caveats=_default_caveats(ha_ready, ai_trustworthy, is_calibrated)
                  + (risk_warnings if risk_warnings else []),
        trade_plan=trade_plan,
        sizing=sizing,
    )


# ---------------------------------------------------------------------------
# Caveats — surfaced honestly so users understand what the system isn't sure of
# ---------------------------------------------------------------------------

def _default_caveats(ha_ready: bool, ai_trustworthy: bool,
                       is_calibrated: bool) -> list[str]:
    caveats = []
    if not ha_ready:
        caveats.append(
            "Historical-analog data is still accumulating — "
            "we don't have enough past similar setups to compare yet."
        )
    if not ai_trustworthy:
        caveats.append(
            "AI meta-learner is still in warmup — "
            "needs more closed signals before its predictions are shown."
        )
    if not is_calibrated:
        caveats.append(
            "Confidence number is the raw rule-based composite — "
            "not yet validated against actual win rates."
        )
    return caveats
