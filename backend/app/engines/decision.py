"""AI decision aggregator.

Combines all engine scores into a final trade signal using weighted confluence.
Weights are configurable; technical & options dominate, astro/numerology/gann
add confluence boost.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Literal

import pandas as pd

from app.config import settings
from app.engines import technical, smc, astrology, numerology, gann, options


# Default weights — must sum to 1.0
DEFAULT_WEIGHTS = {
    "technical": 0.30,
    "smc":       0.20,
    "options":   0.20,
    "astro":     0.12,
    "gann":      0.12,
    "numerology": 0.06,
}


def _effective_weights() -> dict:
    """Returns persisted (tuned) weights if `/data/engine_weights.json` exists,
    otherwise the DEFAULT_WEIGHTS. Allows the optimizer to apply changes
    without code edits."""
    try:
        from app.engines.weight_optimizer import load_weights
        persisted = load_weights()
        if persisted and abs(sum(persisted.values()) - 1.0) < 0.05:
            # ensure all keys present
            merged = dict(DEFAULT_WEIGHTS)
            merged.update(persisted)
            return merged
    except Exception:
        pass
    return DEFAULT_WEIGHTS


def _signal_label(score: float) -> str:
    if score >= 75:
        return "STRONG_BUY"
    if score >= 60:
        return "BUY"
    if score <= 25:
        return "STRONG_SELL"
    if score <= 40:
        return "SELL"
    return "NEUTRAL"


def _trend_label(score: float) -> str:
    if score >= 60:
        return "BULLISH"
    if score <= 40:
        return "BEARISH"
    return "SIDEWAYS"


def _allocation_pct(confidence: float, max_pct: float) -> float:
    """Linear scale: 50% confidence -> 0; 100% confidence -> max_pct."""
    if confidence <= 50:
        return 0.0
    return round((confidence - 50) / 50 * max_pct, 2)


def aggregate(
    symbol: str,
    df: pd.DataFrame,
    spot: float | None = None,
    options_chain: list[dict] | None = None,
    options_expiry: date | None = None,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = 100_000,
    weights: dict | None = None,
) -> dict:
    """Run all engines and produce a final aggregated signal."""
    weights = weights or _effective_weights()
    if spot is None:
        spot = float(df["close"].iloc[-1])

    # Engines
    tech = technical.analyze(df)
    smc_res = smc.analyze(df)
    astro_res = astrology.market_sentiment(datetime.now())
    num_res = numerology.analyze(symbol)
    gann_res = gann.analyze(spot)
    if options_chain:
        opt_expiry = options_expiry or (date.today() + timedelta(days=7))
        opt_res = options.analyze(symbol, spot, opt_expiry, options_chain)
    elif settings.live_only:
        # LIVE_ONLY: skip the options engine entirely rather than fabricate a chain
        opt_res = options.OptionsAnalytics(
            pcr=0, max_pain=0, bias="NEUTRAL",
            support_wall=None, resistance_wall=None,
            suggested_strategy="Live chain not yet wired — no options analysis",
            institutional_view="n/a",
            greeks_atm={}, score=50,
            reasons=["LIVE_ONLY=true and no live chain supplied — skipping synthetic"],
        )
    else:
        # Paper-mode only: synthetic chain
        synth = options.synthetic_chain(symbol, spot)
        opt_res = options.analyze(symbol, spot, date.today() + timedelta(days=7), synth)

    # Weighted confluence
    weighted_score = (
        weights["technical"]  * tech.score +
        weights["smc"]        * smc_res.score +
        weights["options"]    * opt_res.score +
        weights["astro"]      * astro_res.score +
        weights["gann"]       * gann_res.score +
        weights["numerology"] * num_res.score
    )
    confidence = round(weighted_score, 2)
    signal = _signal_label(confidence)
    trend = _trend_label(confidence)

    # Entry / SL / Targets — based on ATR + Gann
    atr_val = tech.indicators["atr14"]
    if signal in ("BUY", "STRONG_BUY"):
        entry = round(spot, 2)
        stoploss = round(spot - 1.5 * atr_val, 2)
        targets = [round(spot + k * atr_val, 2) for k in (1.5, 2.5, 4.0)]
    elif signal in ("SELL", "STRONG_SELL"):
        entry = round(spot, 2)
        stoploss = round(spot + 1.5 * atr_val, 2)
        targets = [round(spot - k * atr_val, 2) for k in (1.5, 2.5, 4.0)]
    else:
        entry = round(spot, 2)
        stoploss = round(spot - 1.0 * atr_val, 2)
        targets = [round(spot + k * atr_val, 2) for k in (1.0, 2.0)]

    risk = abs(entry - stoploss)
    reward = abs(targets[0] - entry) if targets else risk
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    capital_pct = _allocation_pct(confidence, settings.risk_max_position_pct)

    reasons = {
        "technical":  "; ".join(tech.reasons[:5]),
        "smc":        "; ".join(smc_res.reasons[:4]),
        "astrology":  astro_res.headline + " — " + ("; ".join(astro_res.bullish_factors[:3])
                                                     if astro_res.bias == "BULLISH"
                                                     else "; ".join(astro_res.bearish_factors[:3])),
        "gann":       "; ".join(gann_res.reasons[:3]) or "no Gann edge currently",
        "numerology": "; ".join(num_res.reasons[:3]),
        "options":    f"PCR {opt_res.pcr}, max-pain {opt_res.max_pain}, {opt_res.suggested_strategy} | {opt_res.institutional_view}",
    }

    return {
        "symbol": symbol,
        "exchange": "NSE",
        "timeframe": "1d",
        "horizon": horizon,
        "asof": datetime.now().isoformat(),
        "signal": signal,
        "trend": trend,
        "confidence": confidence,
        "entry": entry,
        "stoploss": stoploss,
        "targets": targets,
        "risk_reward": rr,
        "capital_allocation_pct": capital_pct,
        "engines": {
            "technical":  {"score": round(tech.score, 2),    "bias": tech.bias,         "reason": reasons["technical"], "details": tech.indicators},
            "smc":        {"score": round(smc_res.score, 2), "bias": smc_res.market_structure, "reason": reasons["smc"], "details": {"bos": smc_res.last_bos, "choch": smc_res.last_choch, "premium_discount": smc_res.premium_discount}},
            "astrology":  {"score": round(astro_res.score, 2), "bias": astro_res.bias,    "reason": reasons["astrology"], "details": {"volatility_pct": astro_res.volatility_pct, "intraday_windows": astro_res.intraday_windows}},
            "gann":       {"score": round(gann_res.score, 2),"bias": gann_res.bias,      "reason": reasons["gann"], "details": {"nearest_support": gann_res.nearest_support, "nearest_resistance": gann_res.nearest_resistance, "upcoming_cycles": gann_res.upcoming_cycle_dates}},
            "numerology": {"score": round(num_res.score, 2), "bias": num_res.bias,       "reason": reasons["numerology"], "details": {"pythagorean": num_res.pythagorean, "today": num_res.today_date_number}},
            "options":    {"score": round(opt_res.score, 2), "bias": opt_res.bias,       "reason": reasons["options"], "details": {"max_pain": opt_res.max_pain, "pcr": opt_res.pcr, "support_wall": opt_res.support_wall, "resistance_wall": opt_res.resistance_wall, "atm": opt_res.greeks_atm}},
        },
        "reasons": reasons,
        "disclaimer": (
            "Educational/analytical use only. Not SEBI-registered advice. "
            "Astrology & numerology are confluence layers, not guaranteed predictors."
        ),
    }
