"""Fibonacci engine.

Auto-detects the dominant swing (recent significant high → low or low → high)
and computes:
  • Retracement levels: 23.6%, 38.2%, 50%, 61.8%, 78.6%
  • Extension levels: 127.2%, 161.8%, 261.8%
  • Distance of current price to each Fib level
  • Bias score based on price reaction at golden-ratio levels (38.2/50/61.8)

Plays a key role in Stage 1 of the gated pipeline — stocks at or near a
golden-ratio level get an esoteric/geometric edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import pandas as pd
import numpy as np


GOLDEN = {0.382, 0.5, 0.618}
RETRACE_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]
EXTENSION_LEVELS = [1.272, 1.618, 2.618]


@dataclass
class FibAnalysis:
    swing_high: float
    swing_low: float
    swing_direction: str         # UP (low→high recent) or DOWN
    swing_high_date: str
    swing_low_date: str
    current_price: float

    retracements: list[dict] = field(default_factory=list)
    extensions: list[dict] = field(default_factory=list)
    nearest_level: dict | None = None
    distance_to_nearest_pct: float | None = None
    at_golden_ratio: bool = False

    score: float = 50.0          # 0..100 (bullish bias if at support of golden ratio in UP swing)
    bias: str = "NEUTRAL"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _find_swing(df: pd.DataFrame, lookback: int = 60) -> tuple[float, str, float, str, str]:
    """Find dominant swing within last `lookback` bars.
    Returns: (high, high_date, low, low_date, direction)
    """
    seg = df.tail(lookback)
    hi_idx = seg["high"].idxmax()
    lo_idx = seg["low"].idxmin()
    hi = float(seg.loc[hi_idx, "high"])
    lo = float(seg.loc[lo_idx, "low"])
    # direction = whichever came last
    direction = "UP" if hi_idx > lo_idx else "DOWN"
    return hi, str(hi_idx)[:10], lo, str(lo_idx)[:10], direction


def analyze(df: pd.DataFrame, lookback: int = 60) -> FibAnalysis:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if len(df) < lookback + 5:
        lookback = max(20, len(df) - 5)

    hi, hi_date, lo, lo_date, direction = _find_swing(df, lookback)
    price = float(df["close"].iloc[-1])
    rng = hi - lo
    if rng <= 0:
        return FibAnalysis(swing_high=hi, swing_low=lo, swing_direction=direction,
                           swing_high_date=hi_date, swing_low_date=lo_date,
                           current_price=price)

    retraces = []
    extensions = []
    # In an UP swing, retracements pull back from high toward low.
    if direction == "UP":
        for r in RETRACE_LEVELS:
            level = hi - r * rng
            retraces.append({"ratio": r, "level": round(level, 2), "type": "retracement"})
        for e in EXTENSION_LEVELS:
            level = hi + (e - 1) * rng
            extensions.append({"ratio": e, "level": round(level, 2), "type": "extension"})
    else:
        # DOWN swing: retracements rally from low toward high
        for r in RETRACE_LEVELS:
            level = lo + r * rng
            retraces.append({"ratio": r, "level": round(level, 2), "type": "retracement"})
        for e in EXTENSION_LEVELS:
            level = lo - (e - 1) * rng
            extensions.append({"ratio": e, "level": round(level, 2), "type": "extension"})

    all_levels = retraces + extensions
    nearest = min(all_levels, key=lambda x: abs(x["level"] - price))
    dist_pct = abs(nearest["level"] - price) / price * 100
    at_golden = nearest["ratio"] in GOLDEN and dist_pct <= 1.0

    reasons = []
    score = 50.0
    if at_golden:
        if direction == "UP":
            score += 18
            reasons.append(f"Price at golden-ratio retracement {nearest['ratio']} of UP swing — high-probability long")
        else:
            score -= 18
            reasons.append(f"Price at golden-ratio retracement {nearest['ratio']} of DOWN swing — high-probability short")
    elif dist_pct <= 0.5:
        # Hugging any fib level
        if direction == "UP" and nearest["type"] == "retracement":
            score += 8
            reasons.append(f"Price hugging Fib {nearest['ratio']} retracement {nearest['level']:.2f} — long support")
        elif direction == "DOWN" and nearest["type"] == "retracement":
            score -= 8
            reasons.append(f"Price hugging Fib {nearest['ratio']} retracement {nearest['level']:.2f} — short resistance")
        elif nearest["type"] == "extension":
            if direction == "UP":
                score -= 5
                reasons.append(f"Hit Fib extension {nearest['ratio']} — profit-take zone, expect pullback")
            else:
                score += 5
                reasons.append(f"Hit Fib extension {nearest['ratio']} — short cover zone, expect bounce")

    # Boundary check: price beyond the swing
    if (direction == "UP" and price > hi) or (direction == "DOWN" and price < lo):
        score = max(score, 60) if direction == "UP" else min(score, 40)
        reasons.append(f"Price has broken the swing {direction}-side — trend extension")

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    return FibAnalysis(
        swing_high=round(hi, 2),
        swing_low=round(lo, 2),
        swing_direction=direction,
        swing_high_date=hi_date,
        swing_low_date=lo_date,
        current_price=round(price, 2),
        retracements=retraces,
        extensions=extensions,
        nearest_level=nearest,
        distance_to_nearest_pct=round(dist_pct, 3),
        at_golden_ratio=at_golden,
        score=score,
        bias=bias,
        reasons=reasons,
    )
