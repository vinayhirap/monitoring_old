"""Full confluence — one symbol, every layer, explicit mathematical formulas.

For ONE symbol, computes:

  • Technical: RSI(14), MACD(12,26,9), EMA(9/20/50/200), ATR(14), ADX(14), Bollinger(20,2)
  • Gann:    Square of 9 around spot (8 cardinal angles × 8 levels)
              Angles from anchor pivot (1x1, 2x1, 3x1, 4x1, 8x1 + inverse)
              Time cycles (30/45/60/90/120/144/180/270/360 days)
              Vibration: planetary longitude → price line resonance
              Master 144 / 52 / Hexagon nearest S/R
  • Nakshatra: symbol's intrinsic nakshatra + today's Moon nakshatra + tara
  • Planetary: all 9 graha positions + aspects + retrograde flags + eclipse
  • Hora:    current planetary hour + next benefic window
  • Numerology: Pythagorean + Chaldean roots

Then computes a unified score using documented formulas (cited inline).

Returns one structured object with EVERY number used, so the user can audit
exactly how the recommendation was assembled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
import math

import pandas as pd
import pytz

from app.config import settings
from app.engines import (
    technical, smc, fibonacci,
    gann, gann_vibration, gann_master,
    astrology, numerology, hora as hora_eng,
    nakshatra_screener,
)


# ---------------------------------------------------------------------------
# Mathematical helpers (explicit)
# ---------------------------------------------------------------------------

def _normalize_score(raw: float, lo: float = 0, hi: float = 100) -> float:
    """Clamp raw value into [lo, hi]. O(1)."""
    return max(lo, min(hi, raw))


def _weighted_geometric_mean(scores: list[tuple[float, float]]) -> float:
    """Geometric mean weighted by importance. Used because arithmetic mean
    over scores in [0,100] flattens extremes; geometric mean preserves them.

    Formula:  Π(s_i ^ w_i) where Σ w_i = 1

    Returns a value in [0, 100].
    """
    total_w = sum(w for _, w in scores) or 1
    product = 1.0
    for s, w in scores:
        product *= max(1e-6, s / 100) ** (w / total_w)
    return _normalize_score(product * 100)


def _cosine_similarity_bias(biases: list[str]) -> float:
    """Maps list of {BULLISH, BEARISH, NEUTRAL} votes to a [-1, +1] score.
    +1 = unanimous bullish, -1 = unanimous bearish, 0 = max disagreement.

    Formula: (n_bull - n_bear) / max(n_directional, 1)
    """
    bull = sum(1 for b in biases if b == "BULLISH")
    bear = sum(1 for b in biases if b == "BEARISH")
    total = bull + bear
    return (bull - bear) / max(total, 1)


def _harmonic_distance(price: float, level: float) -> float:
    """% distance between price and a target level. O(1)."""
    if price <= 0:
        return 0
    return (level - price) / price * 100


# ---------------------------------------------------------------------------
# Per-engine sub-scorers (each returns standardized 0-100 + bias + metadata)
# ---------------------------------------------------------------------------

def _technical_layer(df: pd.DataFrame) -> dict:
    t = technical.analyze(df)
    return {
        "score":       round(t.score, 2),
        "bias":        t.bias,
        "indicators":  t.indicators,
        "top_reasons": t.reasons[:3],
    }


def _smc_layer(df: pd.DataFrame) -> dict:
    s = smc.analyze(df)
    return {
        "score":       round(s.score, 2),
        "bias":        s.market_structure,
        "last_bos":    s.last_bos,
        "last_choch":  s.last_choch,
        "premium_discount": s.premium_discount,
        "top_reasons": s.reasons[:3],
    }


def _fibonacci_layer(df: pd.DataFrame) -> dict:
    f = fibonacci.analyze(df)
    return {
        "score":         round(f.score, 2),
        "bias":          f.bias,
        "swing_high":    f.swing_high,
        "swing_low":     f.swing_low,
        "nearest_level": f.nearest_level,
        "top_reasons":   f.reasons[:3],
    }


def _gann_layer(spot: float) -> dict:
    """Comprehensive Gann analysis — Square of 9 + angles + time cycles +
    vibration + master charts. All using documented Gann formulas."""
    g = gann.analyze(spot)
    sq9 = gann.square_of_9_levels(spot, levels=4)

    # Master 144 / 52 / Hexagon summary
    master = gann_master.summarise(spot, anchor_price=spot * 0.95).to_dict()

    # Vibration resonance
    vib = gann_vibration.harmonic_resonance(
        live_price=spot, anchor_price=spot * 0.92, tolerance_pct=0.6
    ).to_dict()

    # Forward time cycles from today (use today as anchor for forward projection)
    forward_cycles = gann.time_cycles(date.today())[:5]

    return {
        "score":                round(g.score, 2),
        "bias":                 g.bias,
        "nearest_support":      g.nearest_support,
        "nearest_resistance":   g.nearest_resistance,
        "distance_to_support_pct":    g.distance_to_support_pct,
        "distance_to_resistance_pct": g.distance_to_resistance_pct,
        "square_of_9_levels":   {
            "nearest_supports":    sq9["supports"][:4],
            "nearest_resistances": sq9["resistances"][:4],
        },
        "vibration_resonance":  {
            "score":              vib["score"],
            "bias":               vib["bias"],
            "active_harmonics":   vib["active_harmonics"][:3],
            "nearest_planet":     vib["nearest_planet"],
        },
        "master_charts":        master,
        "upcoming_time_cycles": forward_cycles,
        "top_reasons":          g.reasons[:3],
    }


def _astrology_layer(symbol: str, dt: datetime) -> dict:
    """Full astrology stack — planets, aspects, nakshatras, eclipses."""
    astro_match = astrology.symbol_astro_match(symbol, dt)
    positions = astrology.planet_positions(dt)
    sentiment = astrology.market_sentiment(dt).to_dict()
    phase = astrology.moon_phase(dt)
    aspects = astrology.aspects(positions)
    merc_retro = astrology.mercury_retrograde(dt)
    eclipse = astrology.eclipse_proximity_days(dt)

    # Today's Moon nakshatra → which sectors/symbols this favours
    moon_nak = nakshatra_screener.todays_moon_nakshatra(dt)

    return {
        "score":            round(astro_match["score"], 2),
        "bias":             astro_match["bias"],
        "symbol_nakshatra": astro_match["symbol_nakshatra"],
        "moon_nakshatra":   moon_nak,
        "tara_distance":    astro_match["tara_from_symbol"],
        "planet_positions": {
            name: {
                "longitude":  round(p.longitude, 4),
                "sign":       p.sign["name"],
                "nakshatra":  p.nakshatra["name"],
                "retrograde": p.retrograde,
            } for name, p in positions.items()
        },
        "active_aspects":   aspects[:5],
        "moon_phase":       phase,
        "mercury_retrograde": merc_retro,
        "eclipse_proximity": eclipse,
        "market_sentiment": {
            "score":   sentiment["score"],
            "bias":    sentiment["bias"],
            "headline": sentiment["headline"],
        },
        "top_reasons": astro_match["reasons"][:3],
    }


def _hora_layer() -> dict:
    h = hora_eng.current_hora().to_dict()
    try:
        buy_window  = hora_eng.next_window("BUY").to_dict()
        sell_window = hora_eng.next_window("SELL").to_dict()
    except Exception:
        buy_window = sell_window = None
    return {
        "current": {
            "ruler": h["ruler"], "bias": h["bias"],
            "weight": h["weight"],
            "next_ruler": h["next_ruler"],
            "next_change_minutes": h["next_change_in_minutes"],
        },
        "next_buy_window":  buy_window,
        "next_sell_window": sell_window,
    }


def _numerology_layer(symbol: str) -> dict:
    n = numerology.analyze(symbol)
    return {
        "score": round(n.score, 2),
        "bias":  n.bias,
        "pythagorean": n.pythagorean,
        "chaldean":    n.chaldean,
        "ruler":   n.planetary_ruler,
        "today_compat": n.compatibility_with_today,
        "top_reasons":  n.reasons[:2],
    }


# ---------------------------------------------------------------------------
# Public — full confluence analysis for ONE symbol
# ---------------------------------------------------------------------------

@dataclass
class FullConfluenceReport:
    symbol: str
    asof: str
    spot: float
    composite_score: float           # 0..100
    direction: str                   # BULLISH / BEARISH / NEUTRAL
    confidence_band: list[float]     # [lo, hi]
    cosine_bias: float               # [-1, +1] from cosine_similarity formula
    geometric_mean_score: float       # alternative weighted measure
    arithmetic_mean_score: float      # baseline
    engines: dict                    # each layer's full payload
    formulas_used: list[str]         # transparency
    raw_engine_scores: dict          # plain map for charting
    raw_engine_biases: dict
    disclaimer: str = (
        "Full-confluence composite. The mathematical formulas used are listed "
        "in `formulas_used`. Every number above is auditable. This is a "
        "research tool — not SEBI-registered investment advice."
    )

    def to_dict(self) -> dict:
        return self.__dict__


def full_analysis(symbol: str, df: pd.DataFrame) -> FullConfluenceReport:
    """Run every layer and combine using documented formulas."""
    dt = datetime.now(pytz.timezone(settings.astro_timezone))
    spot = float(df["close"].iloc[-1])

    # Layer-by-layer
    tech_l    = _technical_layer(df)
    smc_l     = _smc_layer(df)
    fib_l     = _fibonacci_layer(df)
    gann_l    = _gann_layer(spot)
    astro_l   = _astrology_layer(symbol, dt)
    hora_l    = _hora_layer()
    num_l     = _numerology_layer(symbol)

    # Score-bias pairs for aggregation
    layers = {
        "technical":  (tech_l["score"],  tech_l["bias"]),
        "smc":        (smc_l["score"],   smc_l["bias"]),
        "fibonacci":  (fib_l["score"],   fib_l["bias"]),
        "gann":       (gann_l["score"],  gann_l["bias"]),
        "astrology":  (astro_l["score"], astro_l["bias"]),
        "numerology": (num_l["score"],   num_l["bias"]),
    }

    # ---- Composite computations (three methods, side-by-side) ----

    # 1. Weighted arithmetic mean (the platform default)
    from app.engines.decision import _effective_weights
    w = _effective_weights()
    arithmetic = (
        w.get("technical", 0)  * tech_l["score"]  +
        w.get("smc", 0)        * smc_l["score"]   +
        w.get("options", 0)    * 50               +     # no options on this fast path
        w.get("astro", 0)      * astro_l["score"] +
        w.get("gann", 0)       * gann_l["score"]  +
        w.get("numerology", 0) * num_l["score"]
    )
    arithmetic = _normalize_score(arithmetic)

    # 2. Weighted geometric mean (preserves extremes)
    geom = _weighted_geometric_mean([
        (tech_l["score"],  w.get("technical", 0.30)),
        (smc_l["score"],   w.get("smc", 0.20)),
        (gann_l["score"],  w.get("gann", 0.12)),
        (astro_l["score"], w.get("astro", 0.12)),
        (num_l["score"],   w.get("numerology", 0.06)),
        (fib_l["score"],   0.10),                        # default Fib weight
    ])

    # 3. Cosine similarity of biases
    biases = [v[1] for v in layers.values()]
    cosine = _cosine_similarity_bias(biases)

    # Composite — average of arithmetic + geometric, biased by cosine direction
    composite = (arithmetic * 0.55 + geom * 0.45)
    if cosine > 0.5:
        composite = min(100, composite + 3)
    elif cosine < -0.5:
        composite = max(0, composite - 3)

    direction = ("BULLISH" if composite >= 60 else
                 "BEARISH" if composite <= 40 else "NEUTRAL")

    # Confidence band — width scales with disagreement
    bull = sum(1 for b in biases if b == "BULLISH")
    bear = sum(1 for b in biases if b == "BEARISH")
    agreement = max(bull, bear) / max(bull + bear, 1)
    half_width = (1 - agreement) * 12 + 4        # ±4 if unanimous, ±16 if split
    band = [round(max(0, composite - half_width), 1),
             round(min(100, composite + half_width), 1)]

    return FullConfluenceReport(
        symbol=symbol.upper(),
        asof=dt.isoformat(),
        spot=spot,
        composite_score=round(composite, 2),
        direction=direction,
        confidence_band=band,
        cosine_bias=round(cosine, 4),
        geometric_mean_score=round(geom, 2),
        arithmetic_mean_score=round(arithmetic, 2),
        engines={
            "technical":  tech_l,
            "smc":        smc_l,
            "fibonacci":  fib_l,
            "gann":       gann_l,
            "astrology":  astro_l,
            "hora":       hora_l,
            "numerology": num_l,
        },
        formulas_used=[
            "Arithmetic mean: Σ(w_i · score_i) with weights from active config",
            "Geometric mean:  Π(score_i ^ w_i) — preserves score extremes",
            "Cosine bias:     (n_bull - n_bear) / max(n_directional, 1) ∈ [-1, +1]",
            "Tara distance:   d = (moon_nak - symbol_nak + 27) mod 27",
            "Square of 9:     level_k = (√spot ± k·(angle°/180))²",
            "Gann angle:      price_n = anchor ± (slope · price_per_unit · days)",
            "Vibration:       price = anchor · (1 + longitude_deg/cycle_size)",
            "Confidence band: composite ± (1 - agreement_ratio) · 12pp",
        ],
        raw_engine_scores={k: v[0] for k, v in layers.items()},
        raw_engine_biases={k: v[1] for k, v in layers.items()},
    )
