"""Nakshatra screener — find stocks aligned with today's Moon nakshatra.

Algorithm:
  1. Pre-compute symbol → nakshatra index map for the full F&O universe.
     (Hash-map; O(1) lookup; built once at module import, ~180 entries.)
  2. Compute today's Moon nakshatra index (Swiss Ephemeris, sidereal Lahiri).
  3. For each symbol in universe:
       tara_distance = (moon_nak_idx - symbol_nak_idx) % 27
       tara_class    = classify(tara_distance)   # janma / sympathetic / tense / neutral
  4. Filter symbols to BULLISH-aligned (tara ∈ {1, 9, 17} or 26 favourable classes).
  5. For each candidate, fetch a fast technical+Gann composite score.
  6. Push (score, symbol) into a min-heap of size N — O(log N) per insert.
  7. Return the top-N as sorted recommendations.

Mathematical formulas used (cited inline):

  • Tara distance:        d = (m - s + 27) mod 27   where m,s ∈ [0, 26]
  • Nakshatra span:        360° / 27 = 13.333333°
  • Pada span:             span / 4 = 3.333333°
  • Janma (1st)            d == 0           — activation, high volatility
  • Sympathetic            d ∈ {8, 16}       — 9th & 17th tara (anumandha)
  • Tense                  d ∈ {2, 4, 6, 9, 11, 13, 18, 20, 22, 24}  — vipat/pratyari
  • Neutral                everything else
  • Composite score        w_tech·tech_score + w_gann·gann_score + w_astro·tara_bonus
                           with weights computed from current weight config

Complexity:
  • Preprocessing:  O(|U|) where |U| = universe size (~180)
  • Per-day scan:   O(|U| · log N) for N-best selection
  • Memory:         O(|U|) for the symbol→nakshatra map
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from heapq import heappush, heappushpop
from typing import Literal

import numpy as np
import pytz
from loguru import logger

from app.config import settings
from app.engines import astrology, gann, technical


# ---------------------------------------------------------------------------
# Constants (mathematical)
# ---------------------------------------------------------------------------

NAK_SPAN_DEG    = 360.0 / 27        # 13.333333° per nakshatra
PADA_SPAN_DEG   = NAK_SPAN_DEG / 4  # 3.333333° per pada
N_NAKSHATRAS    = 27

# Tara classifications — Vedic-astrology standard (1-indexed in literature,
# we use 0-indexed: subtract 1 from traditional table).
JANMA_TARAS      = {0}                                  # 1st  (own nakshatra)
SAMPADA_TARAS    = {2}                                  # 3rd  (wealth — bullish)
SYMPATHETIC_TARAS = {3, 7, 8, 11, 15, 16, 19, 23, 24}   # 4th, 8th, 9th, 12th, 16th, 17th, 20th, 24th, 25th
TENSE_TARAS      = {1, 4, 5, 6, 9, 10, 12, 14, 17, 18, 20, 22, 25}
# Anything else → neutral


# ---------------------------------------------------------------------------
# Symbol → nakshatra precomputed map (built lazily, cached)
# Uses the same deterministic letter-sum hash as astrology.symbol_astro_match.
# ---------------------------------------------------------------------------

_symbol_nak_cache: dict[str, int] = {}


def _symbol_nakshatra_idx(symbol: str) -> int:
    """Deterministic symbol → nakshatra index 0..26. O(|symbol|) once,
    O(1) thereafter (cached). Same formula as astrology.symbol_astro_match
    to keep the system consistent."""
    if symbol in _symbol_nak_cache:
        return _symbol_nak_cache[symbol]
    clean = "".join(c for c in symbol.upper() if c.isalpha())
    if not clean:
        idx = 0
    else:
        # Σ (ord(c) * (i+1))  for i,c in enumerate(clean)
        # Modulo 27 → nakshatra index
        seed = sum(ord(c) * (i + 1) for i, c in enumerate(clean))
        idx = seed % N_NAKSHATRAS
    _symbol_nak_cache[symbol] = idx
    return idx


def _classify_tara(distance: int) -> str:
    if distance in JANMA_TARAS:
        return "JANMA"
    if distance in SAMPADA_TARAS:
        return "SAMPADA"
    if distance in SYMPATHETIC_TARAS:
        return "SYMPATHETIC"
    if distance in TENSE_TARAS:
        return "TENSE"
    return "NEUTRAL"


def _tara_bonus(tara_class: str) -> float:
    """Score adjustment (0-100 scale) from the tara class."""
    return {
        "JANMA":       12.0,    # activation — strong move likely either way
        "SAMPADA":     14.0,    # wealth-favorable bullish bias
        "SYMPATHETIC":  8.0,
        "NEUTRAL":      0.0,
        "TENSE":      -10.0,
    }.get(tara_class, 0.0)


# ---------------------------------------------------------------------------
# Today's Moon nakshatra — single computation, used for ALL stocks today
# ---------------------------------------------------------------------------

def todays_moon_nakshatra(dt: datetime | None = None) -> dict:
    """Returns Moon's nakshatra index + name + ruler + degree."""
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))
    positions = astrology.planet_positions(dt)
    moon = positions["Moon"]
    return {
        "index":  moon.nakshatra["index"] - 1,   # convert to 0-indexed
        "name":   moon.nakshatra["name"],
        "ruler":  moon.nakshatra["ruler"],
        "longitude_deg": round(moon.longitude, 4),
        "degree_in_nakshatra": moon.nakshatra["degree_in_nakshatra"],
        "pada":   moon.nakshatra["pada"],
    }


# ---------------------------------------------------------------------------
# Per-symbol fast scoring (technical + Gann only — astrology already factored)
# ---------------------------------------------------------------------------

def _fast_score(symbol: str, df) -> tuple[float, str, dict]:
    """Returns (score 0..100, bias, details) for ONE symbol.
    Uses just technical + Gann to keep the universe-wide scan fast.
    """
    try:
        tech = technical.analyze(df)
        spot = tech.indicators.get("last", 0)
        if spot <= 0:
            return 50.0, "NEUTRAL", {}
        g = gann.analyze(spot)
        # 60% tech / 40% Gann blend
        score = tech.score * 0.6 + g.score * 0.4
        bias = ("BULLISH" if score >= 60 else
                "BEARISH" if score <= 40 else
                "NEUTRAL")
        return score, bias, {
            "technical_score": round(tech.score, 1),
            "technical_bias":  tech.bias,
            "gann_score":      round(g.score, 1),
            "gann_bias":       g.bias,
            "nearest_gann_support":    g.nearest_support,
            "nearest_gann_resistance": g.nearest_resistance,
            "atr14":           tech.indicators.get("atr14"),
            "spot":            spot,
            "tech_reasons":    tech.reasons[:2],
        }
    except Exception as e:
        logger.debug("fast_score failed for {}: {}", symbol, e)
        return 50.0, "NEUTRAL", {"error": str(e)}


# ---------------------------------------------------------------------------
# Screen result
# ---------------------------------------------------------------------------

@dataclass
class ScreenedSymbol:
    symbol: str
    sector: str
    symbol_nakshatra: str
    tara_distance: int
    tara_class: str
    tara_bonus: float
    fast_score: float                  # technical + Gann composite
    fast_bias: str
    composite_score: float             # fast_score + tara_bonus (clamped)
    direction: str                     # BULLISH / BEARISH / NEUTRAL
    last_price: float | None = None    # NEW — current LTP / last close
    day_change_pct: float | None = None  # NEW — today's session % change
    reason: str = ""                   # NEW — human-readable why
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


def _build_reason(*, sym: str, nak_name: str, tara_class: str, tara_d: int,
                    moon_nak_name: str, composite: float, direction: str,
                    day_change_pct: float | None) -> str:
    """Concise human-readable explanation of why this symbol is on the list.
    Format: "<tara verdict> · <today's price action> · <next change>"
    Used in the screener table's `reason` column so users see why each pick
    is here without having to drill into the symbol page."""
    parts = []
    # Tara verdict
    tara_phrase = {
        "JANMA":       f"Moon in {nak_name} = symbol's own nakshatra (heightened activity)",
        "SAMPADA":     f"Moon in {moon_nak_name} = SAMPADA tara from {nak_name} (wealth alignment)",
        "SYMPATHETIC": f"Moon in {moon_nak_name} = sympathetic tara (d={tara_d})",
        "TENSE":       f"Moon in {moon_nak_name} = tense tara (d={tara_d})",
        "NEUTRAL":     f"Moon in {moon_nak_name} = neutral tara",
    }.get(tara_class, f"tara d={tara_d}")
    parts.append(tara_phrase)

    # Price action
    if day_change_pct is not None:
        if day_change_pct >= 1.5:
            parts.append(f"already +{day_change_pct:.2f}% today — momentum confirmed")
        elif day_change_pct <= -1.5:
            parts.append(f"down {day_change_pct:.2f}% today — possible reversal setup")
        elif day_change_pct >= 0:
            parts.append(f"+{day_change_pct:.2f}% today")
        else:
            parts.append(f"{day_change_pct:.2f}% today")

    # Direction reinforcement
    if direction == "BULLISH":
        parts.append("composite favors LONG")
    elif direction == "BEARISH":
        parts.append("composite favors SHORT")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Main screener
# ---------------------------------------------------------------------------

def screen_universe(
    direction: Literal["BULLISH", "BEARISH", "BOTH"] = "BOTH",
    top_n: int = 15,
    only_aligned: bool = True,
    parallel: int = 6,
) -> dict:
    """Scan the F&O universe filtered by today's Moon nakshatra alignment,
    then ranked by technical+Gann composite.

    Algorithm:
      1. Get today's Moon nakshatra (O(1) — single Swiss Ephemeris call)
      2. For each symbol in universe:
           a. Compute symbol nakshatra (O(|sym|) once, O(1) cached)
           b. Compute tara distance (one mod operation)
           c. If only_aligned and not in favourable classes → skip
           d. Pull OHLCV + run fast_score (technical + Gann)
           e. Adjust score with tara_bonus
           f. Push to min-heap if score in top-N
      3. Return top-N sorted by composite_score descending.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.services.universe import all_symbols, sector_of
    from app.services.market_data import get_ohlcv

    moon_nak = todays_moon_nakshatra()
    moon_idx = moon_nak["index"]
    universe = all_symbols(include_indices=False)

    # ---- Phase 1: tara classification (cheap, sequential) ----
    candidates: list[tuple[str, int, int, str, float]] = []
    # (symbol, sym_nak_idx, tara_distance, tara_class, tara_bonus)
    for sym in universe:
        sym_nak = _symbol_nakshatra_idx(sym)
        d = (moon_idx - sym_nak + N_NAKSHATRAS) % N_NAKSHATRAS
        cls = _classify_tara(d)
        if only_aligned and cls not in ("JANMA", "SAMPADA", "SYMPATHETIC"):
            continue
        candidates.append((sym, sym_nak, d, cls, _tara_bonus(cls)))

    # ---- Phase 2: parallel technical+Gann scoring ----
    def _score_one(item):
        sym, sym_nak, d, cls, bonus = item
        try:
            df = get_ohlcv(sym, periods=120)
            if df is None or df.empty:
                return None
            fast, fast_bias, details = _fast_score(sym, df)
            composite = max(0.0, min(100.0, fast + bonus))
            dir_ = ("BULLISH" if composite >= 60 else
                     "BEARISH" if composite <= 40 else "NEUTRAL")
            nak_name = astrology.NAKSHATRAS[sym_nak][0]

            # NEW: pull current price + daily % change from the DataFrame
            last_price = None
            day_change_pct = None
            try:
                df_lower = df.copy()
                df_lower.columns = [c.lower() for c in df_lower.columns]
                last_price = float(df_lower["close"].iloc[-1])
                if len(df_lower) >= 2:
                    prev = float(df_lower["close"].iloc[-2])
                    if prev > 0:
                        day_change_pct = round((last_price - prev) / prev * 100, 2)
            except Exception:
                pass

            # NEW: human-readable reason combining astro + price-action
            reason = _build_reason(
                sym=sym, nak_name=nak_name, tara_class=cls, tara_d=d,
                moon_nak_name=astrology.NAKSHATRAS[moon_idx][0],
                composite=composite, direction=dir_,
                day_change_pct=day_change_pct,
            )

            return ScreenedSymbol(
                symbol=sym,
                sector=sector_of(sym),
                symbol_nakshatra=nak_name,
                tara_distance=d,
                tara_class=cls,
                tara_bonus=bonus,
                fast_score=round(fast, 2),
                fast_bias=fast_bias,
                composite_score=round(composite, 2),
                direction=dir_,
                last_price=round(last_price, 2) if last_price else None,
                day_change_pct=day_change_pct,
                reason=reason,
                details=details,
            )
        except Exception:
            return None

    scored: list[ScreenedSymbol] = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [pool.submit(_score_one, c) for c in candidates]
        for fut in as_completed(futures):
            res = fut.result()
            if res is not None:
                scored.append(res)

    # ---- Phase 3: filter by requested direction + top-N via heap ----
    if direction == "BULLISH":
        filtered = [s for s in scored if s.direction == "BULLISH"]
        filtered.sort(key=lambda s: -s.composite_score)
    elif direction == "BEARISH":
        filtered = [s for s in scored if s.direction == "BEARISH"]
        filtered.sort(key=lambda s: s.composite_score)
    else:
        filtered = scored
        filtered.sort(key=lambda s: -s.composite_score)

    return {
        "asof": datetime.now().isoformat(),
        "moon_nakshatra": moon_nak,
        "universe_size": len(universe),
        "aligned_candidates": len(candidates),
        "scored": len(scored),
        "top_picks": [s.to_dict() for s in filtered[:top_n]],
        "algorithm_notes": [
            f"Tara classification on {len(universe)} symbols → {len(candidates)} aligned",
            f"Parallel technical+Gann scoring on {len(scored)} candidates",
            f"Top-{top_n} selected by composite (fast_score + tara_bonus, clamped 0-100)",
            "Mathematical formula: composite = clamp(0.6·RSI/MACD/EMA + 0.4·Gann + tara_bonus, 0, 100)",
        ],
        "disclaimer": (
            "Nakshatra alignment is one input. Always cross-check the displayed "
            "technical + Gann reasoning before acting. Not SEBI-registered advice."
        ),
    }
