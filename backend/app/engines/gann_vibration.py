"""W.D. Gann — Law of Vibration.

Gann taught that every stock has a natural "vibration rate" tied to its
listing date / first-trade price, and that price moves trace harmonic
ratios of planetary longitudes converted onto the price scale.

The classical conversion is:
    price_unit = (planet_longitude_deg / 360) * cycle_size
where cycle_size is the master scale (often 360 for liquid equities, or a
multiple/fraction for higher- or lower-priced instruments).

This module computes:
  • planet_longitude_to_price(p)        — degree-to-price conversion at a given
                                          cycle scale, for all 9 graha
  • symbol_vibration(symbol)            — symbol's "natural number" via Gann's
                                          letter-to-number mapping, mapped to
                                          ruling planet + base vibration rate
  • harmonic_resonance(price, planets)  — resonance score: how close is live
                                          price to a planetary degree-converted
                                          price level? Values near 0 ° / 90 °
                                          / 180 ° / 270 ° are "hot" (reversal
                                          windows per Gann)
  • next_vibration_dates(symbol, dt)    — forward dates when the symbol's
                                          ruling planet returns to a harmonic
                                          longitude (square/trine/opposition
                                          to its natal longitude)

Disclaimer: the Law of Vibration is a heuristic confluence layer. It does
not predict markets. Use with technical/SMC confirmation only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable
import math

import pytz

from app.config import settings
from app.engines import astrology


# ---------------------------------------------------------------------------
# Gann's letter → number table (his published Chaldean variant).
# A=1 B=2 C=3 D=4 E=5 F=8 G=3 H=5 I=1 J=1 K=2 L=3 M=4 N=5 O=7 P=8 Q=1 R=2
# S=3 T=4 U=6 V=6 W=6 X=5 Y=1 Z=7. Reduce to a digital root 1..9.
# Each digit maps to a ruling planet (Gann's "natural number" system):
#   1 Sun  2 Moon  3 Jupiter  4 Rahu  5 Mercury  6 Venus  7 Ketu  8 Saturn  9 Mars
# ---------------------------------------------------------------------------

GANN_LETTER_VALUES = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 8, "G": 3, "H": 5, "I": 1,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "O": 7, "P": 8, "Q": 1, "R": 2,
    "S": 3, "T": 4, "U": 6, "V": 6, "W": 6, "X": 5, "Y": 1, "Z": 7,
}

ROOT_TO_PLANET = {
    1: "Sun",      2: "Moon",   3: "Jupiter", 4: "Rahu",
    5: "Mercury",  6: "Venus",  7: "Ketu",    8: "Saturn", 9: "Mars",
}

# Harmonic angles Gann treated as reversal/acceleration points
HARMONIC_ANGLES = [0, 45, 90, 120, 135, 180, 225, 240, 270, 315, 360]
PRIMARY_HARMONICS = {0, 90, 180, 270, 360}    # strongest (cardinal)


def _digital_root(n: int) -> int:
    while n > 9:
        n = sum(int(c) for c in str(n))
    return max(1, n)


# ---------------------------------------------------------------------------
# Symbol → vibration
# ---------------------------------------------------------------------------

@dataclass
class SymbolVibration:
    symbol: str
    raw_sum: int
    root: int                     # 1..9
    ruling_planet: str
    base_vibration: float         # cycle_size suggested for this symbol
    cycle_days: int               # planetary mean cycle in days
    vibration_interpretation: str

    def to_dict(self) -> dict:
        return self.__dict__


# Mean synodic / sidereal cycles (days) — used as Gann time vibration.
PLANET_CYCLE_DAYS = {
    "Sun":     365.25,
    "Moon":    27.32,
    "Mercury": 87.97,
    "Venus":   224.70,
    "Mars":    686.97,
    "Jupiter": 4332.59,
    "Saturn":  10759.22,
    "Rahu":    6798.38,
    "Ketu":    6798.38,
}

# Heuristic vibration interpretation per ruling planet.
VIBRATION_INTERPRETATION = {
    "Sun":     "Leadership / large-cap energy. Trending instrument; respect 360° anniversary dates.",
    "Moon":    "Fast-cycling, mood-driven. Best for intraday — watch 27-day lunar return.",
    "Mercury": "Commerce/communication. IT, broking, media. Reversals near Mercury stations.",
    "Venus":   "Luxury, autos, FMCG. Smooth uptrends; Venus retrograde = consolidation.",
    "Mars":    "Energy, defence, metals. Sharp moves; Mars-Saturn aspects = capitulation.",
    "Jupiter": "Banking, finance, expansion. Most auspicious vibration for wealth.",
    "Saturn":  "PSU, infra, heavy. Slow trends; Saturn return ≈ 7 yr major reversal.",
    "Rahu":    "Speculative, tech/crypto. Manic upside followed by collapse — handle with care.",
    "Ketu":    "Detachment / dissolution. Sudden breaks; pharma, isolated themes.",
}


def symbol_vibration(symbol: str) -> SymbolVibration:
    """Compute symbol's Gann vibration profile."""
    clean = "".join(c for c in symbol.upper() if c.isalpha())
    raw = sum(GANN_LETTER_VALUES.get(c, 0) for c in clean)
    root = _digital_root(raw) if raw else 1
    planet = ROOT_TO_PLANET[root]
    cycle_days = PLANET_CYCLE_DAYS[planet]
    # Base vibration: scale price-cycle to the planet's mean motion.
    # cycle_size in price-units (degrees-on-price) defaults to 360 for liquid
    # stocks; we expose it so the caller can override per instrument.
    base_vibration = 360.0
    return SymbolVibration(
        symbol=symbol,
        raw_sum=raw,
        root=root,
        ruling_planet=planet,
        base_vibration=base_vibration,
        cycle_days=int(round(cycle_days)),
        vibration_interpretation=VIBRATION_INTERPRETATION[planet],
    )


# ---------------------------------------------------------------------------
# Planet-longitude → price conversion
# ---------------------------------------------------------------------------

def planet_longitude_to_price(longitude_deg: float, anchor_price: float,
                              cycle_size: float = 360.0) -> dict:
    """Convert a planetary longitude (0..360°) onto the price scale.

    Gann's formula (one common reading):
        price_at_longitude = anchor_price * (1 + (longitude_deg / 360))
    but for short-cycle instruments the multiplier is the cycle_size scaled
    onto sqrt(price) — same family as Square-of-9 progression:
        price_at_longitude = (sqrt(anchor) + longitude_deg / 180) ** 2

    Returns both the linear and Square-of-9 readings so the caller can match
    whichever fits the instrument's volatility regime.
    """
    long_norm = longitude_deg % 360
    linear = anchor_price * (1 + long_norm / cycle_size)
    base = math.sqrt(anchor_price) if anchor_price > 0 else 0
    sq9 = (base + long_norm / 180) ** 2 if base else anchor_price
    return {
        "longitude_deg": round(long_norm, 4),
        "anchor_price": anchor_price,
        "linear_price": round(linear, 2),
        "square9_price": round(sq9, 2),
    }


def all_planet_price_levels(anchor_price: float,
                            dt: datetime | None = None,
                            cycle_size: float = 360.0) -> list[dict]:
    """For each of the 9 graha, return its current longitude converted to a
    price level. Use these as additional Gann-vibration S/R levels.
    """
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))
    pos = astrology.planet_positions(dt)
    out = []
    for name, p in pos.items():
        conv = planet_longitude_to_price(p.longitude, anchor_price, cycle_size)
        out.append({
            "planet": name,
            "longitude_deg": conv["longitude_deg"],
            "linear_price": conv["linear_price"],
            "square9_price": conv["square9_price"],
            "retrograde": p.retrograde,
        })
    return out


# ---------------------------------------------------------------------------
# Harmonic resonance — is the current price "vibrating" with planetary lines?
# ---------------------------------------------------------------------------

@dataclass
class VibrationResonance:
    score: float                          # 0..100 (higher = stronger resonance)
    bias: str                             # BULLISH / BEARISH / NEUTRAL
    nearest_planet: str | None
    nearest_distance_pct: float | None
    active_harmonics: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def harmonic_resonance(live_price: float, anchor_price: float,
                       symbol: str | None = None,
                       dt: datetime | None = None,
                       tolerance_pct: float = 0.6) -> VibrationResonance:
    """Score how strongly the live price is resonating with current planet-
    converted price lines. A 'hot' resonance at a primary harmonic (0/90/180/
    270/360) is treated as a reversal/acceleration zone.
    """
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))

    levels = all_planet_price_levels(anchor_price, dt)
    sym_vib = symbol_vibration(symbol) if symbol else None

    reasons: list[str] = []
    score = 50.0
    active: list[dict] = []
    nearest_planet = None
    nearest_dist = None

    for lvl in levels:
        # Test both square9 and linear readings
        for kind, price in (("sq9", lvl["square9_price"]), ("lin", lvl["linear_price"])):
            if price <= 0:
                continue
            dist_pct = abs(live_price - price) / live_price * 100
            if nearest_dist is None or dist_pct < nearest_dist:
                nearest_dist = dist_pct
                nearest_planet = lvl["planet"]
            if dist_pct <= tolerance_pct:
                # Identify which harmonic angle this is closest to
                degrees = lvl["longitude_deg"]
                nearest_angle = min(HARMONIC_ANGLES, key=lambda a: abs(a - degrees))
                is_primary = nearest_angle in PRIMARY_HARMONICS
                bump = 12 if is_primary else 5
                # Direction bias: bullish planets (Jupiter, Venus, Sun) push score up
                polarity = astrology.PLANET_POLARITY.get(lvl["planet"], 0)
                score += bump * (1 + polarity / 2)
                active.append({
                    "planet": lvl["planet"],
                    "harmonic_deg": nearest_angle,
                    "primary": is_primary,
                    "price_line": price,
                    "kind": kind,
                    "distance_pct": round(dist_pct, 3),
                })
                reasons.append(
                    f"Price resonating with {lvl['planet']} @ {nearest_angle}° "
                    f"line {price:.2f} ({kind}, {dist_pct:.2f}% off)"
                )

    # Boost / penalise based on the symbol's own ruling planet
    if sym_vib:
        for a in active:
            if a["planet"] == sym_vib.ruling_planet:
                score += 8
                reasons.append(
                    f"Resonance hits {symbol}'s own ruling planet "
                    f"{sym_vib.ruling_planet} — natal vibration activation"
                )
                break

    score = max(0.0, min(100.0, score))
    if score >= 65:
        bias = "BULLISH"
    elif score <= 35:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return VibrationResonance(
        score=score,
        bias=bias,
        nearest_planet=nearest_planet,
        nearest_distance_pct=round(nearest_dist, 3) if nearest_dist is not None else None,
        active_harmonics=active[:8],
        reasons=reasons[:6],
    )


# ---------------------------------------------------------------------------
# Forward vibration dates — when the symbol's planet returns harmonic
# ---------------------------------------------------------------------------

def next_vibration_dates(symbol: str, dt: datetime | None = None,
                          horizon_days: int = 90) -> list[dict]:
    """Scan forward up to `horizon_days` and find dates where the symbol's
    ruling planet hits a primary harmonic (0/90/180/270) relative to its
    longitude *now*. These are Gann's classic "anniversary / harmonic-return"
    reversal candidates.
    """
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))
    sym = symbol_vibration(symbol)
    ruler = sym.ruling_planet
    if ruler in ("Rahu", "Ketu"):
        # Lunar nodes are very slow; use Moon's faster cycle instead
        ruler = "Moon"

    start_pos = astrology.planet_positions(dt).get(ruler)
    if start_pos is None:
        return []
    start_long = start_pos.longitude

    results = []
    last_long = start_long
    cursor = dt
    for d in range(1, horizon_days + 1):
        cursor = dt + timedelta(days=d)
        pos = astrology.planet_positions(cursor).get(ruler)
        if pos is None:
            continue
        cur = pos.longitude
        for target_offset in (90, 180, 270, 360):
            target_long = (start_long + target_offset) % 360
            # Detect crossing target_long between last_long and cur
            if _crossed(last_long, cur, target_long):
                results.append({
                    "date": cursor.date().isoformat(),
                    "planet": ruler,
                    "harmonic_deg": target_offset,
                    "longitude_at_event": round(cur, 4),
                    "interpretation": (
                        f"{ruler} reaches {target_offset}° from {symbol}'s natal "
                        f"vibration → reversal / acceleration candidate"
                    ),
                })
        last_long = cur
        if len(results) >= 8:
            break
    return results


def _crossed(prev: float, cur: float, target: float, tol: float = 1.5) -> bool:
    """Return True if longitude path from prev→cur passes within `tol` deg of
    target. Handles 360° wrap.
    """
    def _circdist(a, b):
        d = abs(a - b) % 360
        return min(d, 360 - d)
    return _circdist(prev, target) <= tol or _circdist(cur, target) <= tol
