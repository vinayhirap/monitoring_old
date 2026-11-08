"""Session forecast split — separates *gap direction* from *close-vs-prior-close*.

Today's chart that the user pasted showed exactly the failure mode this fixes:
NIFTY had a small gap-up, ran to a high, then sold off to roughly flat. The
single "BULLISH 63%" label couldn't distinguish:

  • "expected to gap UP at next open"           ← intraday-trading signal
  • "expected to close ABOVE today's close"     ← daily holders signal
  • "expected to trade ABOVE today's intraday high" ← breakout signal

This module emits three separate signals so the user knows which question
they're getting an answer to.

Inputs needed:
  • OHLCV (daily bars)
  • Optional intraday bars
  • The gap_forecast result (we built it earlier)
  • The decision aggregator's daily confidence
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np
import pandas as pd


@dataclass
class SessionForecast:
    # 1. Gap forecast — what'll happen at next session OPEN
    gap_direction: str                   # GAP_UP / GAP_DOWN / FLAT / UNCERTAIN
    gap_pct_expected: float              # signed
    gap_confidence_pct: float

    # 2. Close-vs-prior-close — what daily holders care about
    daily_direction: str                 # BULLISH / BEARISH / NEUTRAL
    daily_close_above_prior_prob_pct: float

    # 3. Breakout forecast — does it punch through TODAY's intraday high/low?
    breakout_direction: str              # BREAKOUT_UP / BREAKOUT_DOWN / RANGE_BOUND
    breakout_confidence_pct: float
    expected_range_pct: float            # expected (high - low) / close × 100

    # 4. Recommended trading bias per session type
    intraday_bias: str                   # what intraday traders should lean
    swing_bias: str                      # what daily holders should lean

    # 5. Composite scenario narrative
    most_likely_pattern: str             # e.g. "gap-up then sell off to flat" / "trend day up" / "range-bound"

    interpretation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Breakout-direction estimator (based on prior day pattern + ATR-implied range)
# ---------------------------------------------------------------------------

def _breakout_estimator(df: pd.DataFrame, daily_bias_score: float) -> dict:
    """Estimate breakout probability based on:
      • ATR-relative range expansion vs prior N days
      • Close position in prior bar's range (closing strong/weak)
      • Daily bias direction
    """
    if len(df) < 20:
        return {"direction": "RANGE_BOUND", "confidence": 30, "expected_range_pct": 1.0}

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)

    # ATR-based expected range
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.iloc[-14:].mean()
    last_close = c.iloc[-1]
    expected_range_pct = float(atr / last_close * 100) if last_close > 0 else 1.0

    # Closing strength of prior bar
    prior_h, prior_l, prior_c = h.iloc[-1], l.iloc[-1], c.iloc[-1]
    prior_range = prior_h - prior_l
    if prior_range > 0:
        close_position = (prior_c - prior_l) / prior_range
    else:
        close_position = 0.5

    # Recent range expansion? compare last bar range to 20-bar median
    median_range = tr.iloc[-20:].median()
    expansion_ratio = (prior_range / median_range) if median_range > 0 else 1.0

    # Direction call
    bull_score = daily_bias_score
    if close_position > 0.7:
        bull_score += 8
    elif close_position < 0.3:
        bull_score -= 8
    if expansion_ratio > 1.5:                 # already in expansion regime
        confidence_boost = 10
    else:
        confidence_boost = 0

    if bull_score >= 65:
        direction = "BREAKOUT_UP"
        confidence = min(80, bull_score - 50 + confidence_boost)
    elif bull_score <= 35:
        direction = "BREAKOUT_DOWN"
        confidence = min(80, 50 - bull_score + confidence_boost)
    else:
        direction = "RANGE_BOUND"
        confidence = 40 + confidence_boost

    return {
        "direction": direction,
        "confidence": round(float(confidence), 1),
        "expected_range_pct": round(expected_range_pct, 3),
        "close_position_prior": round(float(close_position), 3),
        "expansion_ratio": round(float(expansion_ratio), 3),
    }


# ---------------------------------------------------------------------------
# Pattern classifier — combines gap, breakout, daily bias into a narrative
# ---------------------------------------------------------------------------

def _classify_pattern(gap_direction: str, gap_pct: float,
                      breakout_direction: str, daily_direction: str) -> str:
    """Returns a human-readable pattern label."""
    if daily_direction == "BULLISH":
        if gap_direction == "GAP_UP" and breakout_direction == "BREAKOUT_UP":
            return "TREND DAY UP — gap up, ride higher, close near high"
        elif gap_direction == "GAP_UP" and breakout_direction == "RANGE_BOUND":
            return "GAP & FADE — gap up then mean-revert; daily close still positive"
        elif gap_direction == "GAP_DOWN" and breakout_direction == "BREAKOUT_UP":
            return "REVERSAL DAY — gap down, V-shape recovery, close green"
        elif gap_direction == "FLAT":
            return "GRIND HIGHER — flat open, steady drift up"
        else:
            return "MIXED BULLISH — ends up but path uncertain"
    elif daily_direction == "BEARISH":
        if gap_direction == "GAP_DOWN" and breakout_direction == "BREAKOUT_DOWN":
            return "TREND DAY DOWN — gap down, slide lower, close near low"
        elif gap_direction == "GAP_UP" and breakout_direction == "BREAKOUT_DOWN":
            return "TRAP & DROP — gap up then heavy selling, close red"
        elif gap_direction == "GAP_DOWN" and breakout_direction == "RANGE_BOUND":
            return "GAP & STABILIZE — gap down then sideways; daily close still red"
        else:
            return "MIXED BEARISH — ends down but path uncertain"
    else:
        if breakout_direction == "RANGE_BOUND":
            return "RANGE-BOUND — no breakout either way; fade extremes"
        else:
            return "INSIDE DAY — small range, low conviction"


# ---------------------------------------------------------------------------
# Public — synthesize all three sub-forecasts
# ---------------------------------------------------------------------------

def analyze(df: pd.DataFrame, daily_confidence: float, daily_direction: str,
             gap_forecast_dict: dict | None = None) -> SessionForecast:
    """Take the daily forecast + gap forecast (already built earlier) and
    decompose into intraday / overnight / breakout sub-signals.
    """
    # 1. Gap component — reuse what gap_forecast.py already produced
    if gap_forecast_dict and not gap_forecast_dict.get("error"):
        gap_dir = gap_forecast_dict.get("direction", "UNCERTAIN")
        gap_pct = float(gap_forecast_dict.get("expected_gap_pct", 0))
        gap_conf = float(gap_forecast_dict.get("confidence_pct", 0))
    else:
        gap_dir, gap_pct, gap_conf = "UNCERTAIN", 0.0, 30.0

    # 2. Daily close component — directly from the decision aggregator
    daily_prob = float(daily_confidence)
    if daily_direction == "BULLISH":
        daily_close_above_prior = daily_prob
    elif daily_direction == "BEARISH":
        daily_close_above_prior = 100 - daily_prob
    else:
        daily_close_above_prior = 50.0

    # 3. Breakout component
    br = _breakout_estimator(df, daily_bias_score=daily_prob if daily_direction != "BEARISH" else 100 - daily_prob)

    # 4. Trading bias per session type
    # Intraday traders care about: gap + breakout (path matters)
    # Swing traders care about: daily close (end-of-day matters)
    if gap_dir == "GAP_UP" and br["direction"] == "BREAKOUT_UP":
        intraday_bias = "LONG"
    elif gap_dir == "GAP_DOWN" and br["direction"] == "BREAKOUT_DOWN":
        intraday_bias = "SHORT"
    elif gap_dir == "GAP_UP" and br["direction"] == "RANGE_BOUND":
        intraday_bias = "FADE_OPENING_LONG"      # sell the gap up
    elif gap_dir == "GAP_DOWN" and br["direction"] == "RANGE_BOUND":
        intraday_bias = "FADE_OPENING_SHORT"     # buy the gap down
    elif br["direction"] == "RANGE_BOUND":
        intraday_bias = "RANGE_TRADE"
    else:
        intraday_bias = "WAIT"

    swing_bias = (
        "LONG"  if daily_close_above_prior >= 60 else
        "SHORT" if daily_close_above_prior <= 40 else
        "FLAT"
    )

    # 5. Pattern
    pattern = _classify_pattern(gap_dir, gap_pct, br["direction"], daily_direction)

    # 6. Interpretation
    interp = [
        f"Gap forecast: {gap_dir.replace('_', ' ')} {gap_pct:+.2f}% (confidence {gap_conf:.0f}%)",
        f"Daily close-vs-prior-close: {daily_close_above_prior:.1f}% probability of closing above prior close",
        f"Breakout: {br['direction'].replace('_', ' ')} (confidence {br['confidence']:.0f}%, expected range {br['expected_range_pct']:.2f}%)",
        f"Pattern: {pattern}",
        "",
        f"→ Intraday traders: {intraday_bias.replace('_', ' ')}",
        f"→ Swing traders:    {swing_bias}",
    ]

    # Specific warning for the case the user just hit:
    if gap_dir == "GAP_UP" and br["direction"] == "RANGE_BOUND" and daily_direction == "BULLISH":
        interp.append(
            "⚠ Pattern alert: 'gap & fade' likely. The chart may LOOK red as it falls "
            "from the gap-up high, but it can still close green vs prior close. "
            "Intraday traders fade the gap; swing traders hold."
        )
    elif gap_dir == "GAP_DOWN" and daily_direction == "BULLISH":
        interp.append(
            "⚠ Pattern alert: bullish day starting with a gap DOWN. The chart will look bad early; "
            "recovery expected by close. Intraday traders may scalp the dip."
        )

    return SessionForecast(
        gap_direction=gap_dir,
        gap_pct_expected=round(gap_pct, 3),
        gap_confidence_pct=round(gap_conf, 1),
        daily_direction=daily_direction,
        daily_close_above_prior_prob_pct=round(daily_close_above_prior, 1),
        breakout_direction=br["direction"],
        breakout_confidence_pct=br["confidence"],
        expected_range_pct=br["expected_range_pct"],
        intraday_bias=intraday_bias,
        swing_bias=swing_bias,
        most_likely_pattern=pattern,
        interpretation=interp,
    )
