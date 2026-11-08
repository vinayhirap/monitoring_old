"""Fractal Fibonacci — nested recursive Fib levels + extensions.

Direct port of the Pine Script approach:

  1. Primary fib levels between swing_high (val0) and swing_low (val1):
       0.236, 0.382, 0.5, 0.618, 0.786
  2. Extension levels above swing_high:
       1.145848, 1.309, 1.485748, 1.618
  3. Extension levels below swing_low (inverse):
       -1.145848, -1.309, -1.485748, -1.618
  4. INSIDE each adjacent-pair band, compute another set of 0.236/0.382/0.5
     /0.618/0.786 sub-levels. Bands used:
         [0    – 0.786]
         [0.786 – 0.618]
         [0.618 – 0.5]
         [0.5  – 0.382]
         [0.382 – 0.236]
         [0.236 – 1]
         [1    – 1.145848]   (extension band)
     This creates a fractal grid: ~5 primary + 4 extensions + (5 sub-fibs × 7
     bands) ≈ 45 total levels.

Why nested Fib matters:
  • Single-level Fib hits ~50-55% as confluence; nested hits more often
    (price often reacts at sub-band ratios, not just the main 0.618 etc.)
  • The "golden ratio of the golden ratio" pattern is well-documented in
    Elliott-wave + harmonic trading literature

Honest limit: more levels = more "always near a level" — careful with
overfitting interpretation. Use the *nearest cluster* of levels (where
3+ ratios converge within ±0.3%) as the actually-meaningful zones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import math

import pandas as pd


# Primary Fibonacci ratios (between low and high)
PRIMARY_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)

# Extension ratios (above high or below low)
EXTENSION_RATIOS = (0.145848, 0.309, 0.485748, 0.618)

# Sub-fibonacci ratios used inside each band (same as primary)
SUB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)


def _level_between(low: float, high: float, ratio: float) -> float:
    """Standard Fib retracement: low + ratio * (high - low)."""
    return low + ratio * (high - low)


@dataclass
class FractalFibLevel:
    price: float
    label: str                       # "P_0.382" or "S_0-786_0.5" etc.
    category: str                    # primary / extension / sub / inverse_extension
    distance_pct: float              # signed: positive = above spot

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class FractalFibReport:
    swing_high: float
    swing_low: float
    swing_range: float
    spot: float
    levels: list[dict]
    nearest_above: dict | None
    nearest_below: dict | None
    confluence_zones: list[dict]     # bands where 3+ levels cluster within 0.3%
    interpretation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _detect_swings(df: pd.DataFrame, lookback: int = 100) -> tuple[float, float]:
    """Find the latest meaningful swing high + swing low from OHLCV."""
    sample = df.tail(lookback) if len(df) > lookback else df
    h = float(sample["high"].astype(float).max())
    l = float(sample["low"].astype(float).min())
    return h, l


def compute(df: pd.DataFrame, lookback: int = 100) -> FractalFibReport:
    """Compute the full fractal-Fib grid."""
    if df is None or df.empty:
        return FractalFibReport(
            swing_high=0, swing_low=0, swing_range=0, spot=0,
            levels=[], nearest_above=None, nearest_below=None,
            confluence_zones=[], interpretation=["No data"],
        )
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    spot = float(df["close"].iloc[-1])
    swing_high, swing_low = _detect_swings(df, lookback)
    rng = swing_high - swing_low
    if rng <= 0:
        return FractalFibReport(
            swing_high=swing_high, swing_low=swing_low, swing_range=0, spot=spot,
            levels=[], nearest_above=None, nearest_below=None,
            confluence_zones=[],
            interpretation=["Zero range — cannot compute Fib levels"],
        )

    out: list[FractalFibLevel] = []

    # 1. Primary Fib levels
    for r in PRIMARY_RATIOS:
        p = _level_between(swing_low, swing_high, r)
        out.append(FractalFibLevel(
            price=round(p, 2), label=f"P_{r}", category="primary",
            distance_pct=round((p - spot) / spot * 100, 3),
        ))
    # Endpoints
    out.append(FractalFibLevel(price=round(swing_low, 2),  label="P_0.0",  category="primary",
                                 distance_pct=round((swing_low - spot) / spot * 100, 3)))
    out.append(FractalFibLevel(price=round(swing_high, 2), label="P_1.0", category="primary",
                                 distance_pct=round((swing_high - spot) / spot * 100, 3)))

    # 2. Extension levels above high
    for r in EXTENSION_RATIOS:
        p = swing_high + r * rng
        out.append(FractalFibLevel(
            price=round(p, 2), label=f"E_+{1 + r}", category="extension",
            distance_pct=round((p - spot) / spot * 100, 3),
        ))

    # 3. Inverse extension levels below low
    for r in EXTENSION_RATIOS:
        p = swing_low - r * rng
        out.append(FractalFibLevel(
            price=round(p, 2), label=f"E_-{1 + r}", category="inverse_extension",
            distance_pct=round((p - spot) / spot * 100, 3),
        ))

    # 4. Nested sub-fib bands — recursive
    bands = [
        ("0-786",      swing_low,                                       _level_between(swing_low, swing_high, 0.786)),
        ("786-618",    _level_between(swing_low, swing_high, 0.618),    _level_between(swing_low, swing_high, 0.786)),
        ("618-0.5",    _level_between(swing_low, swing_high, 0.5),      _level_between(swing_low, swing_high, 0.618)),
        ("0.5-0.382",  _level_between(swing_low, swing_high, 0.382),    _level_between(swing_low, swing_high, 0.5)),
        ("0.382-236",  _level_between(swing_low, swing_high, 0.236),    _level_between(swing_low, swing_high, 0.382)),
        ("236-1",      _level_between(swing_low, swing_high, 0.236),    swing_high),
        ("1+ext",      swing_high,                                      swing_high + 0.145848 * rng),
    ]
    for band_name, lo, hi in bands:
        if hi <= lo:
            lo, hi = hi, lo
        for r in SUB_RATIOS:
            p = _level_between(lo, hi, r)
            out.append(FractalFibLevel(
                price=round(p, 2),
                label=f"S_{band_name}_{r}",
                category="sub",
                distance_pct=round((p - spot) / spot * 100, 3),
            ))

    # ----- Nearest above & below -----
    above = sorted([l for l in out if l.price > spot], key=lambda x: x.price)
    below = sorted([l for l in out if l.price < spot], key=lambda x: -x.price)
    nearest_above = above[0].to_dict() if above else None
    nearest_below = below[0].to_dict() if below else None

    # ----- Confluence zones (clusters of 3+ levels within 0.3% band) -----
    # Group adjacent levels by price proximity
    all_prices = sorted(out, key=lambda x: x.price)
    clusters: list[list[FractalFibLevel]] = []
    cluster: list[FractalFibLevel] = []
    for lvl in all_prices:
        if not cluster:
            cluster.append(lvl); continue
        # if within 0.3% of cluster's first member, group
        if abs(lvl.price - cluster[0].price) / cluster[0].price < 0.003:
            cluster.append(lvl)
        else:
            if len(cluster) >= 3:
                clusters.append(cluster)
            cluster = [lvl]
    if len(cluster) >= 3:
        clusters.append(cluster)

    confluence_zones = []
    for c in clusters:
        prices = [l.price for l in c]
        confluence_zones.append({
            "low": round(min(prices), 2),
            "high": round(max(prices), 2),
            "midpoint": round(sum(prices) / len(prices), 2),
            "n_levels": len(c),
            "labels": [l.label for l in c],
            "distance_pct_from_spot": round((sum(prices) / len(prices) - spot) / spot * 100, 3),
        })
    # sort by absolute distance from spot
    confluence_zones.sort(key=lambda z: abs(z["distance_pct_from_spot"]))

    # ----- Interpretation -----
    # Count headline: 5 primary ratios + 2 endpoints (0.0/1.0) + 4 ext above
    # + 4 ext below = 15 non-nested. Anything beyond that is a nested sub-level.
    NON_NESTED = 5 + 2 + 4 + 4
    interp = [
        f"Swing high ₹{swing_high:.2f} · Swing low ₹{swing_low:.2f} · Range ₹{rng:.2f}",
        f"Total levels computed: {len(out)} "
        f"(5 primary + 2 endpoints + 4+4 extensions + {len(out) - NON_NESTED} nested sub-levels)",
    ]
    if nearest_above:
        interp.append(f"Nearest above: ₹{nearest_above['price']} ({nearest_above['label']}, "
                       f"{nearest_above['distance_pct']:+.2f}% away)")
    if nearest_below:
        interp.append(f"Nearest below: ₹{nearest_below['price']} ({nearest_below['label']}, "
                       f"{nearest_below['distance_pct']:+.2f}% away)")
    if confluence_zones:
        top = confluence_zones[0]
        interp.append(
            f"⚡ Strongest cluster: ₹{top['low']}–₹{top['high']} ({top['n_levels']} levels overlap) "
            f"— {top['distance_pct_from_spot']:+.2f}% from spot"
        )
        if len(confluence_zones) > 1:
            interp.append(f"  Other clusters: {len(confluence_zones) - 1} additional confluence zones")

    return FractalFibReport(
        swing_high=round(swing_high, 2),
        swing_low=round(swing_low, 2),
        swing_range=round(rng, 2),
        spot=round(spot, 2),
        levels=[l.to_dict() for l in out],
        nearest_above=nearest_above,
        nearest_below=nearest_below,
        confluence_zones=confluence_zones[:8],     # top 8 confluence zones
        interpretation=interp,
    )
