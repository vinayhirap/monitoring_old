"""Gann "natural squares" — integer perfect-square price levels.

Direct port of the Pine Script approach:

    base_n  = floor(sqrt(spot))            # nearest integer below sqrt(spot)
    zero    = base_n²                       # nearest perfect square below spot
    upper_k = (base_n + k)²                 # k-th perfect square above
    lower_k = (base_n - k)²                 # k-th perfect square below

Why this matters separately from the existing Square-of-9 engine:

The platform's `gann.py` Square of 9 uses
    level = (√anchor ± k·(angle°/180))²
which generates levels at 45°/90°/135°/etc. — a sub-set of "all squares
on the spiral."

The natural-squares approach takes ONLY the integer corners of that
spiral — i.e. price levels where √price is a whole number. Gann
traditionally taught that these "natural number" lines are stronger S/R
than fractional-angle lines because they're where price commonly
"rests" between cycles.

Example for spot ₹23,792:
    sqrt(23792) ≈ 154.24
    base = 154
    zero level  = 154² = 23,716
    upper k=1   = 155² = 24,025
    upper k=2   = 156² = 24,336
    lower k=1   = 153² = 23,409
    lower k=2   = 152² = 23,104

Distance between adjacent levels grows as price grows (because (n+1)² −
n² = 2n+1) — which is also why Gann said high-priced indices respect
fewer levels than low-priced stocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass
class NaturalSquaresReport:
    spot: float
    base_n: int                      # floor(sqrt(spot))
    zero_level: float                # base_n²
    distance_above_zero_pct: float
    upper_levels: list[dict]         # [{k, n, price, distance_pct}, ...]
    lower_levels: list[dict]
    nearest_resistance: float | None
    nearest_support: float | None
    distance_to_resistance_pct: float | None
    distance_to_support_pct: float | None
    interpretation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def compute(spot: float, levels: int = 4) -> NaturalSquaresReport:
    """Compute integer-perfect-square levels around `spot`.

    levels: how many perfect squares above + below to compute.
    Returns the zero level (largest square below spot), the upper ladder,
    and the lower ladder.
    """
    if spot <= 0:
        return NaturalSquaresReport(
            spot=spot, base_n=0, zero_level=0,
            distance_above_zero_pct=0,
            upper_levels=[], lower_levels=[],
            nearest_resistance=None, nearest_support=None,
            distance_to_resistance_pct=None, distance_to_support_pct=None,
            interpretation=["Invalid spot price"],
        )

    base_n = int(math.floor(math.sqrt(spot)))
    zero = base_n * base_n
    distance_above_zero_pct = (spot - zero) / zero * 100 if zero > 0 else 0

    uppers: list[dict] = []
    for k in range(1, levels + 1):
        n = base_n + k
        price = n * n
        uppers.append({
            "k": k, "n": n, "price": round(float(price), 2),
            "distance_pct": round((price - spot) / spot * 100, 3),
        })

    lowers: list[dict] = []
    seen_n: set[int] = set()
    for k in range(1, levels + 1):
        n = base_n - k
        if n < 1:
            break       # nothing lower than 1² = 1 is meaningful
        if n in seen_n:
            continue    # never emit the same perfect square twice
        seen_n.add(n)
        price = n * n
        if price >= zero:    # don't repeat the zero level itself
            continue
        lowers.append({
            "k": k, "n": n, "price": round(float(price), 2),
            "distance_pct": round((spot - price) / spot * 100, 3),
        })

    # The zero level itself acts as nearest support (spot is above it by definition)
    nearest_sup = zero
    distance_sup_pct = (spot - zero) / spot * 100 if spot > 0 else None
    nearest_res = uppers[0]["price"] if uppers else None
    distance_res_pct = uppers[0]["distance_pct"] if uppers else None

    # ----- Human interpretation -----
    interp: list[str] = []
    interp.append(
        f"Base integer n={base_n} (since √{spot:.2f} ≈ {math.sqrt(spot):.3f})"
    )
    interp.append(
        f"Zero level (n²): ₹{zero:.2f} — spot is {distance_above_zero_pct:+.2f}% above"
    )
    if distance_above_zero_pct < 0.5:
        interp.append("→ Price is HUGGING the zero square — strong support, watch for bounce")
    elif distance_above_zero_pct > 90:
        interp.append("→ Price has stretched far above the zero square — approaching upper square")
    interp.append(
        f"Nearest perfect-square resistance: ₹{nearest_res:.2f} (n²={uppers[0]['n']}²)"
        if uppers else "No upper level"
    )
    interp.append(
        f"Nearest perfect-square support:    ₹{nearest_sup:.2f} (n²={base_n}²)"
    )

    # Gap analysis — how dense are the squares at this price?
    if uppers and lowers:
        upper_gap = uppers[0]["price"] - spot
        lower_gap = spot - lowers[0]["price"] if lowers else (spot - zero)
        interp.append(
            f"Level density: next upper {upper_gap:.2f} away, next lower {lower_gap:.2f} away "
            f"(higher density = stronger Gann influence at this price band)"
        )

    return NaturalSquaresReport(
        spot=round(spot, 2),
        base_n=base_n,
        zero_level=round(float(zero), 2),
        distance_above_zero_pct=round(distance_above_zero_pct, 3),
        upper_levels=uppers,
        lower_levels=lowers,
        nearest_resistance=nearest_res,
        nearest_support=nearest_sup,
        distance_to_resistance_pct=distance_res_pct,
        distance_to_support_pct=round(distance_sup_pct, 3) if distance_sup_pct else None,
        interpretation=interp,
    )
