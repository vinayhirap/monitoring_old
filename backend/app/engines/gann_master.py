"""W.D. Gann — Master Charts.

In addition to the Square of 9 (already in `gann.py`), Gann taught three other
master charts heavily used in his published method:

  • Master 144 — a 12 × 12 grid; the number 144 = 12² is the "great cycle",
    used for major price *and* time projections. Levels at 1/8, 1/4, 1/3, 1/2,
    2/3, 3/4, 7/8 of 144 around an anchor.

  • Master 52 — a 4-row × 13-col chart (52 = 4×13 = weeks-in-year). Gann used
    it for *weekly* time-and-price counts. The 52-week swing is a classical
    cycle.

  • Hexagon chart — a 6-pointed star numbering 1, 7, 19, 37, 61, 91, … built
    by adding 6, 12, 18, … Each hex-ring is a major reversal band. Used for
    long-term price targets on index instruments.

These chart families *project* future price and time targets rather than
acting as live support/resistance — feed them into the time-cycle output
or the strategy notes as "watch dates" / "watch levels".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Master 144
# ---------------------------------------------------------------------------

MASTER_144_FRACTIONS = [
    ("1/8",   1 / 8),
    ("1/4",   1 / 4),
    ("1/3",   1 / 3),
    ("3/8",   3 / 8),
    ("1/2",   1 / 2),
    ("5/8",   5 / 8),
    ("2/3",   2 / 3),
    ("3/4",   3 / 4),
    ("7/8",   7 / 8),
    ("1/1",   1.0),
]


def master_144(anchor_price: float, range_factor: float | None = None) -> dict:
    """Master 144 price levels.

    The 144 grid is anchored at `anchor_price` (a major prior low for
    bullish projection, or major high for bearish). `range_factor` defaults
    to anchor_price/144 — that is, one grid unit ≈ 0.69% of price. Override
    for very high- or low-priced instruments.
    """
    unit = range_factor if range_factor else anchor_price / 144
    one_cycle = unit * 144

    up_levels = []
    down_levels = []
    for label, frac in MASTER_144_FRACTIONS:
        up_levels.append({
            "fraction": label,
            "price": round(anchor_price + one_cycle * frac, 2),
            "kind": "resistance",
        })
        down_price = anchor_price - one_cycle * frac
        if down_price > 0:
            down_levels.append({
                "fraction": label,
                "price": round(down_price, 2),
                "kind": "support",
            })

    return {
        "anchor_price": anchor_price,
        "unit": round(unit, 4),
        "one_cycle_range": round(one_cycle, 2),
        "resistances": up_levels,
        "supports": down_levels,
        "key_levels": [up_levels[i] for i in (1, 4, 6, 8)] +
                      [d for d in down_levels if d["fraction"] in ("1/4", "1/2", "3/4")],
    }


def master_144_time(anchor_date: date) -> list[dict]:
    """Master 144 time grid — date projections at 12, 24, 36, 48, 60, 72,
    90, 108, 120, 132, 144 trading-day-equivalent calendar days.
    """
    units = [12, 24, 36, 48, 60, 72, 90, 108, 120, 132, 144]
    out = []
    for u in units:
        out.append({
            "calendar_days": u,
            "projected_date": (anchor_date + timedelta(days=u)).isoformat(),
            "significance": _master144_time_meaning(u),
        })
    return out


def _master144_time_meaning(d: int) -> str:
    return {
        12:  "minor (12-day pulse)",
        24:  "1/6 of 144 — short cycle",
        36:  "1/4 of 144 — quarter-cycle reversal",
        48:  "1/3 of 144 — trine harmonic",
        60:  "secondary cycle (60-day)",
        72:  "1/2 of 144 — opposition harmonic",
        90:  "Square of 90 — major time-square",
        108: "3/4 of 144 — three-quarter cycle",
        120: "trine harmonic (120-day)",
        132: "approaching full 144",
        144: "FULL Master 144 — primary reversal candidate",
    }.get(d, f"{d}-day cycle")


# ---------------------------------------------------------------------------
# Master 52 (week-cycle chart)
# ---------------------------------------------------------------------------

def master_52(anchor_price: float) -> dict:
    """Master 52 levels — quarter-of-year price grid.
    Used for weekly swing projections.
    """
    unit = anchor_price / 52
    one_cycle = unit * 52
    levels = []
    for w in (13, 26, 39, 52, 65, 78, 91, 104):
        levels.append({
            "weeks": w,
            "up_price": round(anchor_price + unit * w, 2),
            "down_price": round(max(0.01, anchor_price - unit * w), 2),
            "label": _master52_label(w),
        })
    return {
        "anchor_price": anchor_price,
        "unit_per_week": round(unit, 4),
        "one_cycle_range": round(one_cycle, 2),
        "weekly_levels": levels,
    }


def master_52_time(anchor_date: date) -> list[dict]:
    """Forward weekly projections at the classical Gann turn-week numbers."""
    weeks = [4, 8, 13, 17, 21, 26, 30, 35, 39, 44, 49, 52]
    out = []
    for w in weeks:
        out.append({
            "weeks": w,
            "projected_date": (anchor_date + timedelta(weeks=w)).isoformat(),
            "significance": _master52_label(w),
        })
    return out


def _master52_label(w: int) -> str:
    return {
        4:  "monthly cycle",
        8:  "double-month",
        13: "quarter-year (1/4 of 52)",
        17: "1/3 of 52",
        21: "Fibonacci 21",
        26: "half-year (1/2 of 52)",
        30: "30-week cycle",
        35: "2/3 of 52",
        39: "3/4 of 52",
        44: "5/6 of 52",
        49: "11/12 of 52",
        52: "FULL annual cycle — major Gann turn",
        65: "5/4 cycle",
        78: "3/2 cycle",
        91: "7/4 cycle",
        104: "DOUBLE annual cycle",
    }.get(w, f"{w}-week cycle")


# ---------------------------------------------------------------------------
# Hexagon chart — six-sided spiral
# ---------------------------------------------------------------------------

def hexagon_chart(anchor_price: float, rings: int = 8) -> dict:
    """Build the hexagon chart around an anchor price.

    Construction: starting at 1 in the center, each successive ring of the
    hexagon adds 6, 12, 18, 24… so the corner-numbers grow as
       ring k corner = 1 + 6 * (1+2+...+k) = 1 + 3*k*(k+1)
    On the price scale we treat (corner-1) * unit as price-offset, where
    unit = anchor_price / center_scale.
    """
    unit = anchor_price / 100        # 1 hex-unit = 1% of price (heuristic)
    rings_out = []
    for k in range(1, rings + 1):
        corner = 1 + 3 * k * (k + 1)
        # six points on the ring — at multiples of 60°
        points = []
        for face in range(6):
            corner_face = corner - (face * k)
            up_price = anchor_price + (corner_face - 1) * unit
            down_price = anchor_price - (corner_face - 1) * unit
            points.append({
                "face_deg": face * 60,
                "corner_value": corner_face,
                "resistance": round(up_price, 2),
                "support": round(max(0.01, down_price), 2),
            })
        rings_out.append({
            "ring": k,
            "corner_master": corner,
            "ring_range_pct": round(corner * unit / anchor_price * 100, 2),
            "points": points,
        })

    # Major hex levels — corners of rings 3 / 6 are emphasised by Gann as
    # "Master Hexagon" turn levels.
    major = []
    for r in (3, 6):
        if r <= rings:
            corner = 1 + 3 * r * (r + 1)
            major.append({
                "ring": r,
                "label": f"Master Hex ring {r}",
                "price_up": round(anchor_price + (corner - 1) * unit, 2),
                "price_down": round(max(0.01, anchor_price - (corner - 1) * unit), 2),
                "interpretation": (
                    "Major reversal band — historically Gann used these for "
                    "Dow / S&P top-bottom projections"
                ),
            })

    return {
        "anchor_price": anchor_price,
        "unit": round(unit, 4),
        "rings": rings_out,
        "major_levels": major,
    }


# ---------------------------------------------------------------------------
# Combined Master-chart summary helper
# ---------------------------------------------------------------------------

@dataclass
class MasterChartSummary:
    anchor_price: float
    nearest_144_support: float | None
    nearest_144_resistance: float | None
    nearest_52_support: float | None
    nearest_52_resistance: float | None
    nearest_hex_support: float | None
    nearest_hex_resistance: float | None
    reasons: list[str]

    def to_dict(self) -> dict:
        return self.__dict__


def summarise(live_price: float, anchor_price: float) -> MasterChartSummary:
    """Quick S/R summary across all three master charts — used in the
    confluence aggregator.
    """
    m144 = master_144(anchor_price)
    m52 = master_52(anchor_price)
    hex_ = hexagon_chart(anchor_price)

    def _near(levels, side):
        candidates = []
        for r in levels:
            if side == "support" and r["price"] < live_price:
                candidates.append(r["price"])
            elif side == "resistance" and r["price"] > live_price:
                candidates.append(r["price"])
        if not candidates:
            return None
        if side == "support":
            return max(candidates)
        return min(candidates)

    s144 = _near(m144["supports"], "support")
    r144 = _near(m144["resistances"], "resistance")

    # Flatten m52 weekly levels for S/R
    m52_flat = []
    for lvl in m52["weekly_levels"]:
        m52_flat.append({"price": lvl["down_price"], "kind": "support"})
        m52_flat.append({"price": lvl["up_price"], "kind": "resistance"})
    s52 = _near([r for r in m52_flat if r["kind"] == "support"], "support")
    r52 = _near([r for r in m52_flat if r["kind"] == "resistance"], "resistance")

    # Flatten hex
    hex_flat = []
    for ring in hex_["rings"]:
        for p in ring["points"]:
            hex_flat.append({"price": p["support"], "kind": "support"})
            hex_flat.append({"price": p["resistance"], "kind": "resistance"})
    s_hex = _near([r for r in hex_flat if r["kind"] == "support"], "support")
    r_hex = _near([r for r in hex_flat if r["kind"] == "resistance"], "resistance")

    reasons: list[str] = []
    for label, sup, res in (
        ("M144", s144, r144), ("M52", s52, r52), ("Hex", s_hex, r_hex),
    ):
        if sup is not None:
            reasons.append(f"{label} support {sup:.2f}")
        if res is not None:
            reasons.append(f"{label} resistance {res:.2f}")

    return MasterChartSummary(
        anchor_price=anchor_price,
        nearest_144_support=s144,
        nearest_144_resistance=r144,
        nearest_52_support=s52,
        nearest_52_resistance=r52,
        nearest_hex_support=s_hex,
        nearest_hex_resistance=r_hex,
        reasons=reasons,
    )
