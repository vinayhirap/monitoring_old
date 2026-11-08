"""W.D. Gann analysis engine.

Implements:
  - Square of 9 wheel (price levels at 45/90/135/180/225/270/315/360 degrees)
  - Gann Angles (1x1, 2x1, 1x2, 4x1, 1x4, 8x1, 1x8) from anchor pivot
  - Time cycles (30/45/60/90/120/144/180/270/360 calendar-day projections)
  - Price-time squaring (price = bar count or price = days)
  - Heuristic Gann score for confluence with other engines
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math


# ============================================================================
# Square of 9
# ============================================================================

def square_of_9_levels(price: float, levels: int = 8) -> dict:
    """For a given anchor price, return support/resistance levels at standard
    Gann angles around the price using sqrt(price) ± k * (angle/180) progression.

    Method:
      base = sqrt(price)
      for each angle a in [45,90,135,180,225,270,315,360]:
         step = a / 180
         resistance = (base + step * n)^2  for n in [1..levels]
         support    = (base - step * n)^2  for n in [1..levels]
    """
    base = math.sqrt(price)
    angles = [45, 90, 135, 180, 225, 270, 315, 360]
    supports = []
    resistances = []
    natural = []
    for a in angles:
        step = a / 180
        for n in range(1, levels + 1):
            r = (base + step * n) ** 2
            s_val = (base - step * n) ** 2
            resistances.append({"angle_deg": a, "n": n, "price": round(r, 2)})
            if base - step * n > 0:
                supports.append({"angle_deg": a, "n": n, "price": round(s_val, 2)})
        natural.append({"angle_deg": a, "factor": round(step, 4)})
    # Cardinal natural square levels (closest cluster)
    cardinal = []
    for k in range(-levels, levels + 1):
        if k == 0:
            continue
        for cardinal_step in (0.5, 1.0, 1.5, 2.0):
            v = (base + k * cardinal_step) ** 2
            if v > 0:
                cardinal.append({"step": cardinal_step, "k": k, "price": round(v, 2)})
    return {
        "anchor_price": price,
        "supports": sorted(supports, key=lambda x: -x["price"]),
        "resistances": sorted(resistances, key=lambda x: x["price"]),
        "natural_angles": natural,
        "cardinal_levels": cardinal[:32],
    }


# ============================================================================
# Gann Angles from anchor pivot
# ============================================================================

def gann_angles(anchor_price: float, anchor_date: date, asof: date,
                price_per_unit: float = 1.0) -> list[dict]:
    """Project Gann angles forward from an anchor pivot.

    price_per_unit defines the scale (e.g. 1 INR per day for slow stocks,
    or larger for high-priced indices). 1x1 = price_per_unit per day.
    """
    days = max(0, (asof - anchor_date).days)
    ratios = [
        ("1x8", 1 / 8),
        ("1x4", 1 / 4),
        ("1x3", 1 / 3),
        ("1x2", 1 / 2),
        ("1x1", 1),
        ("2x1", 2),
        ("3x1", 3),
        ("4x1", 4),
        ("8x1", 8),
    ]
    out = []
    for name, slope in ratios:
        delta = slope * price_per_unit * days
        out.append({
            "ratio": name,
            "slope_per_day": slope * price_per_unit,
            "support_line": round(anchor_price - delta, 2),
            "resistance_line": round(anchor_price + delta, 2),
            "days_elapsed": days,
        })
    return out


# ============================================================================
# Time cycles
# ============================================================================

DEFAULT_CYCLES = [30, 45, 60, 90, 120, 144, 180, 270, 360]


def time_cycles(anchor_date: date, cycles: list[int] | None = None) -> list[dict]:
    cycles = cycles or DEFAULT_CYCLES
    out = []
    for c in cycles:
        out.append({
            "cycle_days": c,
            "projected_date": (anchor_date + timedelta(days=c)).isoformat(),
            "significance": _cycle_significance(c),
        })
    return out


def _cycle_significance(c: int) -> str:
    table = {
        30:  "minor cycle (1 month)",
        45:  "first reversal window",
        60:  "secondary cycle",
        90:  "major quarterly cycle (square of 90°)",
        120: "trine harmonic",
        144: "Fibonacci x Gann square (12²)",
        180: "half-cycle reversal (180° opposition)",
        270: "three-quarter cycle",
        360: "full annual cycle (360° complete)",
    }
    return table.get(c, "custom cycle")


# ============================================================================
# Price-time squaring
# ============================================================================

def price_time_square(anchor_price: float, anchor_date: date, asof: date,
                       tick_per_day: float = 1.0) -> dict:
    """Detect when bar count squares with price.
    Square achieved when (price - anchor_price) ≈ days_elapsed * tick_per_day.
    """
    days = (asof - anchor_date).days
    expected_price = anchor_price + days * tick_per_day
    return {
        "anchor_price": anchor_price,
        "anchor_date": anchor_date.isoformat(),
        "asof": asof.isoformat(),
        "days_elapsed": days,
        "tick_per_day": tick_per_day,
        "squared_price": round(expected_price, 2),
        "comment": (
            "Reversal probability rises as live price meets squared_price "
            "near a major Gann time cycle date."
        ),
    }


# ============================================================================
# Score for confluence
# ============================================================================

@dataclass
class GannScore:
    score: float
    bias: str
    nearest_support: float | None
    nearest_resistance: float | None
    distance_to_support_pct: float | None
    distance_to_resistance_pct: float | None
    upcoming_cycle_dates: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def analyze(price: float, anchor_price: float | None = None,
            anchor_date: date | None = None, asof: date | None = None) -> GannScore:
    """Compute a Gann confluence score for a given live price."""
    if asof is None:
        asof = date.today()
    if anchor_price is None:
        anchor_price = price * 0.92      # assume recent swing low ~8% below
    if anchor_date is None:
        anchor_date = asof - timedelta(days=45)

    sq = square_of_9_levels(price)
    nearest_sup = max((s["price"] for s in sq["supports"] if s["price"] < price), default=None)
    nearest_res = min((r["price"] for r in sq["resistances"] if r["price"] > price), default=None)

    reasons: list[str] = []
    score = 50.0
    if nearest_sup is not None:
        d_sup_pct = (price - nearest_sup) / price * 100
        if d_sup_pct < 0.5:
            score += 12
            reasons.append(f"Price hugging Gann support {nearest_sup:.2f} ({d_sup_pct:.2f}% above)")
        elif d_sup_pct < 1.5:
            score += 6
            reasons.append(f"Close to Gann support {nearest_sup:.2f}")
    else:
        d_sup_pct = None

    if nearest_res is not None:
        d_res_pct = (nearest_res - price) / price * 100
        if d_res_pct < 0.5:
            score -= 8
            reasons.append(f"Price testing Gann resistance {nearest_res:.2f}")
        elif d_res_pct < 1.5:
            score -= 4
            reasons.append(f"Approaching Gann resistance {nearest_res:.2f}")
    else:
        d_res_pct = None

    cycles = time_cycles(anchor_date)
    upcoming = [c for c in cycles if c["projected_date"] >= asof.isoformat()][:5]

    # Days until next major cycle
    for c in upcoming[:1]:
        proj = date.fromisoformat(c["projected_date"])
        days_left = (proj - asof).days
        if 0 <= days_left <= 5:
            score += 5
            reasons.append(f"Major Gann cycle ({c['cycle_days']}d) hits in {days_left}d → reversal window")

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    return GannScore(
        score=score,
        bias=bias,
        nearest_support=nearest_sup,
        nearest_resistance=nearest_res,
        distance_to_support_pct=round(d_sup_pct, 2) if d_sup_pct is not None else None,
        distance_to_resistance_pct=round(d_res_pct, 2) if d_res_pct is not None else None,
        upcoming_cycle_dates=upcoming,
        reasons=reasons,
    )
