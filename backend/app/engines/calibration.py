"""Calibration self-check engine.

This is the single most important engineering tool for an honest trading
system. It answers ONE question: when the platform says "65% BULLISH",
does the market actually close green 65% of the time?

Method:
  1. For each historical bar in the lookback window, replay the forecast
     using only data available up to (and including) that bar — strict
     walk-forward, no look-ahead bias.
  2. Compute the predicted direction + confidence for the NEXT bar.
  3. Compare to what the next bar's close vs current close actually did.
  4. Bucket predictions by confidence (50-55, 55-60, 60-65, 65-70, 70+).
  5. For each bucket, compute realized win-rate.
  6. Plot the calibration curve: predicted_prob vs realized_rate.
     A perfectly calibrated system has the curve on the diagonal.

The result is a single output the user can read:
   "Your 60-65% confidence calls closed green 52% of the time over the
    last 200 days. The system is OVER-confident by 8 percentage points
    at this conviction level. Suggested correction: scale confidences
    down by ~12%, OR treat 65% labels as 55% in size decisions."

This is what distinguishes a *measured* trading system from a *marketed* one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
import math

import numpy as np
import pandas as pd
from loguru import logger


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------

@dataclass
class CalibrationBucket:
    range_low: float          # predicted confidence bucket lower bound
    range_high: float
    n_predictions: int
    realized_rate: float      # 0..1 — fraction that actually closed in predicted direction
    expected_rate: float      # midpoint of the bucket (e.g. 0.625 for 60-65)
    calibration_gap: float    # realized - expected (signed). Positive = under-confident.
    avg_pnl_pct_when_right: float
    avg_pnl_pct_when_wrong: float

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class CalibrationReport:
    symbol: str
    method: str                          # "headline_confidence" / "technical_only" / etc.
    bars_used: int
    n_predictions: int
    overall_accuracy: float               # 0..1
    brier_score: float                    # 0=perfect, 0.25=random
    log_loss: float
    buckets: list[CalibrationBucket]
    is_calibrated: bool                   # |max gap| < 5pp
    suggested_confidence_multiplier: float  # apply to future predictions
    avg_overconfidence_pp: float          # average (expected - realized) in pp
    rating: str                           # WELL_CALIBRATED / SLIGHTLY_OVER / OVERCONFIDENT / SEVERELY_OVERCONFIDENT
    interpretation: list[str]
    raw_predictions: list[dict] = field(default_factory=list)   # for plotting

    def to_dict(self) -> dict:
        return {
            **self.__dict__,
            "buckets": [b.to_dict() if hasattr(b, "to_dict") else b for b in self.buckets],
        }


# ---------------------------------------------------------------------------
# Confidence buckets — standard convention
# ---------------------------------------------------------------------------

BUCKETS: list[tuple[float, float]] = [
    (0.50, 0.55),
    (0.55, 0.60),
    (0.60, 0.65),
    (0.65, 0.70),
    (0.70, 0.75),
    (0.75, 0.80),
    (0.80, 1.00),
]


# ---------------------------------------------------------------------------
# Walk-forward predictor (lightweight — uses the technical engine subset
# to avoid heavy astrology recompute over hundreds of days)
# ---------------------------------------------------------------------------

def _predict_one_bar(df_slice: pd.DataFrame) -> tuple[str, float] | None:
    """Return (direction, confidence_0_to_1) for the bar AFTER the slice's last bar.

    Lightweight predictor — uses TECHNICAL + GANN + FIBONACCI only (no astrology
    per-bar, which would be ~30x slower because of Swiss Ephemeris). This is
    the fast walk-forward path. The astrology layer's contribution is roughly
    static over short backtest windows anyway.

    Returns None if insufficient data or any sub-engine fails.
    """
    if len(df_slice) < 40:
        return None
    try:
        from app.engines import technical, gann, fibonacci

        tech = technical.analyze(df_slice)
        spot = tech.indicators.get("last")
        if not spot:
            return None
        g = gann.analyze(spot)
        fib = fibonacci.analyze(df_slice)

        # Weighted blend of the three fast engines
        score = (tech.score * 0.55 + g.score * 0.25 + fib.score * 0.20)
        if score >= 60:
            direction = "BULLISH"
            confidence = score / 100
        elif score <= 40:
            direction = "BEARISH"
            confidence = (100 - score) / 100        # confidence in BEARISH call
        else:
            return None                              # NEUTRAL → skip, no directional bet
        return direction, max(0.5, min(0.95, confidence))
    except Exception as e:
        logger.debug("calibration: predict failed: {}", e)
        return None


# ---------------------------------------------------------------------------
# Main calibration routine
# ---------------------------------------------------------------------------

def calibrate(df: pd.DataFrame, symbol: str = "?",
              lookback_bars: int = 200,
              warmup_bars: int = 50,
              method: str = "headline_confidence") -> CalibrationReport:
    """Walk-forward calibration check.

    df         : OHLCV DataFrame with at least 250 bars
    lookback   : how many recent bars to test on (each one becomes a prediction)
    warmup     : minimum history required before generating predictions
    """
    if df is None or df.empty or "close" not in df.columns:
        return _empty_report(symbol, method, "No OHLCV data")
    if len(df) < warmup_bars + 30:
        return _empty_report(symbol, method,
                             f"Need at least {warmup_bars + 30} bars; have {len(df)}")

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    closes = df["close"].astype(float).values
    n = len(df)
    start = max(warmup_bars, n - lookback_bars)

    predictions: list[dict] = []
    bar_errors = 0
    for i in range(start, n - 1):           # leave room for next bar's close
        try:
            slice_ = df.iloc[: i + 1]
            pred = _predict_one_bar(slice_)
            if pred is None:
                continue
            direction, conf = pred

            cur_close = closes[i]
            next_close = closes[i + 1]
            if cur_close <= 0:
                continue
            realized_up = next_close > cur_close
            pnl_pct = (next_close - cur_close) / cur_close * 100

            if direction == "BULLISH":
                predicted_up = True
                prob_up = conf
            elif direction == "BEARISH":
                predicted_up = False
                prob_up = 1 - conf
            else:
                continue

            correct = predicted_up == realized_up
            predictions.append({
                "bar_idx": i,
                "predicted_direction": direction,
                "predicted_confidence": round(conf, 4),
                "predicted_prob_up": round(prob_up, 4),
                "realized_up": realized_up,
                "realized_pnl_pct": round(pnl_pct, 4),
                "correct": correct,
            })
        except Exception as e:
            bar_errors += 1
            logger.debug("calibration bar {} failed: {}", i, e)
            if bar_errors > 20:
                logger.warning("calibration: too many bar errors, stopping early")
                break
            continue

    if not predictions:
        return _empty_report(symbol, method, "No directional predictions emitted in window")

    # Overall accuracy
    accuracy = sum(1 for p in predictions if p["correct"]) / len(predictions)

    # Brier score: mean( (predicted_prob - realized_outcome)^2 )
    brier = float(np.mean([
        (p["predicted_prob_up"] - (1.0 if p["realized_up"] else 0.0)) ** 2
        for p in predictions
    ]))

    # Log loss
    eps = 1e-9
    ll = -float(np.mean([
        ((1.0 if p["realized_up"] else 0.0) * math.log(max(p["predicted_prob_up"], eps)) +
         (1.0 - (1.0 if p["realized_up"] else 0.0)) * math.log(max(1 - p["predicted_prob_up"], eps)))
        for p in predictions
    ]))

    # Bucket by predicted confidence
    buckets: list[CalibrationBucket] = []
    overconfidence_total = 0.0
    overconfidence_n = 0
    for low, high in BUCKETS:
        in_bucket = [p for p in predictions
                     if low <= max(p["predicted_prob_up"], 1 - p["predicted_prob_up"]) < high]
        if not in_bucket:
            continue
        # For each prediction, "realized" is whether the predicted direction came true
        realized = sum(1 for p in in_bucket if p["correct"]) / len(in_bucket)
        expected = (low + high) / 2
        gap = realized - expected
        pnl_right = float(np.mean([abs(p["realized_pnl_pct"]) for p in in_bucket if p["correct"]])) if any(p["correct"] for p in in_bucket) else 0.0
        pnl_wrong = float(np.mean([abs(p["realized_pnl_pct"]) for p in in_bucket if not p["correct"]])) if any(not p["correct"] for p in in_bucket) else 0.0
        buckets.append(CalibrationBucket(
            range_low=low, range_high=high,
            n_predictions=len(in_bucket),
            realized_rate=round(realized, 4),
            expected_rate=round(expected, 4),
            calibration_gap=round(gap, 4),
            avg_pnl_pct_when_right=round(pnl_right, 4),
            avg_pnl_pct_when_wrong=round(pnl_wrong, 4),
        ))
        if len(in_bucket) >= 5:   # only weight buckets with enough samples
            overconfidence_total += -gap * len(in_bucket)
            overconfidence_n += len(in_bucket)

    avg_overconf_pp = (overconfidence_total / max(overconfidence_n, 1)) * 100

    # Is the system calibrated? Max bucket gap < 5pp = yes
    max_gap = max((abs(b.calibration_gap) for b in buckets), default=0)
    is_calibrated = max_gap < 0.05

    # Auto-correction multiplier
    # If system is overconfident by avg X pp, shrink confidences toward 0.5 by factor
    # We aim to map predicted_confidence c → 0.5 + (c - 0.5) * multiplier
    # such that mean predicted ≈ mean realized.
    if not is_calibrated and avg_overconf_pp > 0:
        # Solve: mean_realized = 0.5 + (mean_predicted - 0.5) * m
        mean_predicted = float(np.mean([max(p["predicted_prob_up"], 1 - p["predicted_prob_up"]) for p in predictions]))
        mean_realized = accuracy
        denom = mean_predicted - 0.5
        if abs(denom) > 1e-6:
            multiplier = (mean_realized - 0.5) / denom
            multiplier = max(0.4, min(1.0, multiplier))
        else:
            multiplier = 1.0
    else:
        multiplier = 1.0

    # Rating
    if avg_overconf_pp < 3:
        rating = "WELL_CALIBRATED"
    elif avg_overconf_pp < 7:
        rating = "SLIGHTLY_OVERCONFIDENT"
    elif avg_overconf_pp < 12:
        rating = "OVERCONFIDENT"
    else:
        rating = "SEVERELY_OVERCONFIDENT"

    # Interpretation
    interp = [
        f"Walk-forward tested {len(predictions)} predictions on last {n - start} bars",
        f"Overall directional accuracy: {accuracy * 100:.1f}%",
        f"Brier score: {brier:.4f} (0 = perfect, 0.25 = random coinflip)",
        f"Log-loss: {ll:.4f} (lower is better)",
        f"Average overconfidence across buckets: {avg_overconf_pp:+.1f} pp",
        f"Calibration rating: {rating.replace('_', ' ')}",
    ]
    if not is_calibrated:
        interp.append(
            f"→ Recommendation: confidence labels are overstated by ~{avg_overconf_pp:.0f}pp. "
            f"Multiply incoming confidences by {multiplier:.2f} for honest sizing. "
            f"OR mentally treat a '65%' label as '{50 + (65 - 50) * multiplier:.0f}%'."
        )
    else:
        interp.append(
            "→ Confidence labels appear well-calibrated. A 65% label means roughly 65% hit rate."
        )

    # Bucket commentary
    for b in buckets:
        bias = "OVER" if b.calibration_gap < -0.03 else "UNDER" if b.calibration_gap > 0.03 else "OK"
        interp.append(
            f"  • {int(b.range_low*100)}-{int(b.range_high*100)}%: "
            f"n={b.n_predictions}, realized {b.realized_rate*100:.0f}% "
            f"({bias} by {abs(b.calibration_gap)*100:.1f}pp)"
        )

    return CalibrationReport(
        symbol=symbol,
        method=method,
        bars_used=n,
        n_predictions=len(predictions),
        overall_accuracy=round(accuracy, 4),
        brier_score=round(brier, 4),
        log_loss=round(ll, 4),
        buckets=buckets,
        is_calibrated=is_calibrated,
        suggested_confidence_multiplier=round(multiplier, 4),
        avg_overconfidence_pp=round(avg_overconf_pp, 2),
        rating=rating,
        interpretation=interp,
        raw_predictions=predictions[-50:],     # last 50 for plotting (cap response size)
    )


def _empty_report(symbol: str, method: str, msg: str) -> CalibrationReport:
    return CalibrationReport(
        symbol=symbol, method=method,
        bars_used=0, n_predictions=0,
        overall_accuracy=0, brier_score=0, log_loss=0,
        buckets=[], is_calibrated=False,
        suggested_confidence_multiplier=1.0,
        avg_overconfidence_pp=0, rating="INSUFFICIENT_DATA",
        interpretation=[msg],
    )


# ---------------------------------------------------------------------------
# Apply correction to a fresh prediction
# ---------------------------------------------------------------------------

def apply_correction(predicted_confidence: float,
                      multiplier: float) -> float:
    """Map raw confidence → calibrated confidence using the multiplier from
    the latest calibration run.
        calibrated = 0.5 + (raw - 0.5) * multiplier
    """
    return 0.5 + (predicted_confidence - 0.5) * multiplier
