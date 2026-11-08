"""Vedic astrology engine — Swiss Ephemeris (sidereal Lahiri).

Computes planetary positions, Nakshatras, aspects, Moon phase, Mercury retrograde,
and a heuristic market-sentiment score.

Disclaimer: outputs are an *alternative analytical layer* / confluence score,
not a guaranteed market forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable
import math

import pytz
import swisseph as swe

from app.config import settings


# ============================================================================
# Constants
# ============================================================================

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# 27 Nakshatras with ruling planet & financial nature (heuristic)
NAKSHATRAS = [
    ("Ashwini",          "Ketu",    "neutral"),
    ("Bharani",          "Venus",   "bullish"),
    ("Krittika",         "Sun",     "bearish"),    # cutting/sharp
    ("Rohini",           "Moon",    "bullish"),    # wealth, growth
    ("Mrigashira",       "Mars",    "neutral"),
    ("Ardra",            "Rahu",    "bearish"),    # storm, volatility
    ("Punarvasu",        "Jupiter", "bullish"),    # renewal
    ("Pushya",           "Saturn",  "bullish"),    # most auspicious for wealth
    ("Ashlesha",         "Mercury", "bearish"),    # serpentine, tricky
    ("Magha",            "Ketu",    "neutral"),
    ("Purva Phalguni",   "Venus",   "bullish"),
    ("Uttara Phalguni",  "Sun",     "bullish"),
    ("Hasta",            "Moon",    "bullish"),    # craft, gain
    ("Chitra",           "Mars",    "neutral"),
    ("Swati",            "Rahu",    "neutral"),    # wind/markets variable
    ("Vishakha",         "Jupiter", "bullish"),
    ("Anuradha",         "Saturn",  "bullish"),
    ("Jyeshtha",         "Mercury", "bearish"),
    ("Mula",             "Ketu",    "bearish"),    # destruction/roots
    ("Purva Ashadha",    "Venus",   "bullish"),
    ("Uttara Ashadha",   "Sun",     "bullish"),
    ("Shravana",         "Moon",    "neutral"),
    ("Dhanishta",        "Mars",    "bullish"),    # wealth
    ("Shatabhisha",      "Rahu",    "bearish"),
    ("Purva Bhadrapada", "Jupiter", "bearish"),
    ("Uttara Bhadrapada","Saturn",  "neutral"),
    ("Revati",           "Mercury", "bullish"),
]

PLANETS = {
    "Sun":      swe.SUN,
    "Moon":     swe.MOON,
    "Mercury":  swe.MERCURY,
    "Venus":    swe.VENUS,
    "Mars":     swe.MARS,
    "Jupiter":  swe.JUPITER,
    "Saturn":   swe.SATURN,
    "Rahu":     swe.MEAN_NODE,        # mean lunar node
    "Ketu":     swe.MEAN_NODE,        # 180° from Rahu
}

# Heuristic market polarity per planet (for aggregate sentiment)
PLANET_POLARITY = {
    "Sun":     +0.5,
    "Moon":    +0.3,    # cycles volatility
    "Mercury": +0.4,    # commerce
    "Venus":   +1.0,    # wealth/luxury
    "Mars":    -0.3,    # aggression/sells
    "Jupiter": +1.2,    # expansion/wealth
    "Saturn":  -0.8,    # restriction/contraction
    "Rahu":    -0.6,    # speculative bubbles + crashes
    "Ketu":    -0.4,    # detachment/sudden moves
}

ASPECT_ORBS = {
    0: 8,      # conjunction
    60: 4,     # sextile
    90: 6,     # square
    120: 6,    # trine
    180: 8,    # opposition
}

ASPECT_NATURE = {
    0:   "neutral",
    60:  "bullish",
    90:  "bearish",
    120: "bullish",
    180: "bearish",
}

# Set ephemeris mode once. Use Moshier (built-in, no external SE1 data files
# required) to keep installs frictionless. Accuracy is ~0.01" for outer planets
# and ~1" for Moon — plenty for sentiment-grade market analysis.
_BASE_FLAG = swe.FLG_SIDEREAL | swe.FLG_SPEED | swe.FLG_MOSEPH
swe.set_sid_mode(swe.SIDM_LAHIRI)


# ---------------------------------------------------------------------------
# Caching — astrology is slow (Swiss Ephemeris × 9 planets per call) and
# the entire universe scan only needs one snapshot per hour.
# Cache by (year, month, day, hour) so values refresh at the top of each hour.
# ---------------------------------------------------------------------------
from functools import lru_cache

def _cache_key(dt: datetime | None) -> tuple:
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))
    return (dt.year, dt.month, dt.day, dt.hour)


# ============================================================================
# Helpers
# ============================================================================

def _to_jd_ut(dt: datetime) -> float:
    """Convert tz-aware (or assumed UTC) datetime to Julian Day UT."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc = dt.astimezone(timezone.utc)
    return swe.julday(
        utc.year, utc.month, utc.day,
        utc.hour + utc.minute / 60 + utc.second / 3600,
        swe.GREG_CAL,
    )


def _nakshatra_for(longitude: float) -> dict:
    """Return nakshatra info for sidereal longitude (degrees 0..360)."""
    long_norm = longitude % 360
    span = 360 / 27               # 13.3333°
    pada_span = span / 4          # 3.3333°
    idx = int(long_norm / span)
    name, ruler, nature = NAKSHATRAS[idx]
    pada = int((long_norm - idx * span) / pada_span) + 1
    return {
        "name": name,
        "index": idx + 1,
        "ruler": ruler,
        "nature": nature,
        "pada": pada,
        "degree_in_nakshatra": round(long_norm - idx * span, 4),
    }


def _sign_for(longitude: float) -> dict:
    long_norm = longitude % 360
    idx = int(long_norm / 30)
    return {"name": SIGNS[idx], "index": idx + 1, "degree_in_sign": round(long_norm - idx * 30, 4)}


# ============================================================================
# Core calculations
# ============================================================================

@dataclass
class PlanetPosition:
    name: str
    longitude: float
    sign: dict
    nakshatra: dict
    speed: float
    retrograde: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "longitude": round(self.longitude, 4),
            "sign": self.sign,
            "nakshatra": self.nakshatra,
            "speed": round(self.speed, 4),
            "retrograde": self.retrograde,
        }


_positions_cache: dict[tuple, dict] = {}

def planet_positions(dt: datetime) -> dict[str, PlanetPosition]:
    key = _cache_key(dt)
    if key in _positions_cache:
        return _positions_cache[key]
    jd = _to_jd_ut(dt)
    out = {}
    for name, code in PLANETS.items():
        result, _err = swe.calc_ut(jd, code, _BASE_FLAG)
        lon, _lat, _dist, lon_speed, *_ = result
        if name == "Ketu":
            lon = (lon + 180) % 360
            lon_speed = -lon_speed
        out[name] = PlanetPosition(
            name=name,
            longitude=lon,
            sign=_sign_for(lon),
            nakshatra=_nakshatra_for(lon),
            speed=lon_speed,
            retrograde=lon_speed < 0,
        )
    # cap cache to last 8 hours so it can't grow unbounded
    if len(_positions_cache) > 8:
        _positions_cache.pop(next(iter(_positions_cache)))
    _positions_cache[key] = out
    return out


_sentiment_cache: dict[tuple, "AstroSentiment"] = {}


def moon_phase(dt: datetime) -> dict:
    jd = _to_jd_ut(dt)
    sun, _ = swe.calc_ut(jd, swe.SUN, _BASE_FLAG)
    moon, _ = swe.calc_ut(jd, swe.MOON, _BASE_FLAG)
    angle = (moon[0] - sun[0]) % 360
    illumination = (1 - math.cos(math.radians(angle))) / 2
    if angle < 22.5 or angle >= 337.5:
        name = "New Moon"
    elif angle < 67.5:
        name = "Waxing Crescent"
    elif angle < 112.5:
        name = "First Quarter"
    elif angle < 157.5:
        name = "Waxing Gibbous"
    elif angle < 202.5:
        name = "Full Moon"
    elif angle < 247.5:
        name = "Waning Gibbous"
    elif angle < 292.5:
        name = "Last Quarter"
    else:
        name = "Waning Crescent"
    tithi_index = int(angle / 12) + 1   # 1..30
    return {
        "phase": name,
        "elongation_deg": round(angle, 2),
        "illumination_pct": round(illumination * 100, 2),
        "tithi": tithi_index,
        "paksha": "Shukla" if tithi_index <= 15 else "Krishna",
    }


def aspects(positions: dict[str, PlanetPosition], orb_factor: float = 1.0) -> list[dict]:
    """Detect classical aspects between planet pairs."""
    names = list(positions.keys())
    out = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            sep = abs(positions[a].longitude - positions[b].longitude) % 360
            if sep > 180:
                sep = 360 - sep
            for target_angle, base_orb in ASPECT_ORBS.items():
                if abs(sep - target_angle) <= base_orb * orb_factor:
                    out.append({
                        "planet_a": a,
                        "planet_b": b,
                        "aspect": target_angle,
                        "orb": round(abs(sep - target_angle), 2),
                        "nature": ASPECT_NATURE[target_angle],
                    })
    return out


def mercury_retrograde(dt: datetime) -> bool:
    jd = _to_jd_ut(dt)
    res, _ = swe.calc_ut(jd, swe.MERCURY, _BASE_FLAG)
    return res[3] < 0


def eclipse_proximity_days(dt: datetime, window: int = 30) -> dict:
    """Cheap eclipse proximity: distance to nearest solar/lunar eclipse within ±window days.
    Some pyswisseph builds require external SE1 data files for these — wrap in try/except.
    """
    jd = _to_jd_ut(dt)
    out: dict = {"solar_days": None, "lunar_days": None}
    try:
        retflag, tret = swe.sol_eclipse_when_glob(jd - window, swe.FLG_MOSEPH, 0)
        if retflag >= 0 and tret:
            out["solar_days"] = round(tret[0] - jd, 2)
    except Exception:
        pass
    try:
        retflag, tret = swe.lun_eclipse_when(jd - window, swe.FLG_MOSEPH, 0)
        if retflag >= 0 and tret:
            out["lunar_days"] = round(tret[0] - jd, 2)
    except Exception:
        pass
    return out


# ============================================================================
# Market-sentiment aggregator
# ============================================================================

@dataclass
class AstroSentiment:
    score: float                  # 0..100 (higher = bullish)
    bias: str                     # BULLISH / BEARISH / NEUTRAL
    headline: str
    bullish_factors: list[str] = field(default_factory=list)
    bearish_factors: list[str] = field(default_factory=list)
    intraday_windows: list[dict] = field(default_factory=list)
    volatility_pct: float = 0.0
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "bias": self.bias,
            "headline": self.headline,
            "bullish_factors": self.bullish_factors,
            "bearish_factors": self.bearish_factors,
            "intraday_windows": self.intraday_windows,
            "volatility_pct": round(self.volatility_pct, 2),
            "raw": self.raw,
        }


def market_sentiment(dt: datetime | None = None) -> AstroSentiment:
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))

    key = _cache_key(dt)
    if key in _sentiment_cache:
        return _sentiment_cache[key]

    pos = planet_positions(dt)
    asp = aspects(pos)
    phase = moon_phase(dt)
    merc_retro = mercury_retrograde(dt)
    ecl = eclipse_proximity_days(dt)

    bull: list[str] = []
    bear: list[str] = []
    score = 50.0
    vol = 30.0

    # Moon nakshatra polarity
    moon_nak = pos["Moon"].nakshatra
    if moon_nak["nature"] == "bullish":
        score += 6
        bull.append(f"Moon in {moon_nak['name']} ({moon_nak['ruler']}-ruled, wealth-favorable)")
    elif moon_nak["nature"] == "bearish":
        score -= 6
        bear.append(f"Moon in {moon_nak['name']} ({moon_nak['ruler']}-ruled, volatile)")

    # Aspect-weighted bias
    for a in asp:
        weight = (PLANET_POLARITY.get(a["planet_a"], 0) + PLANET_POLARITY.get(a["planet_b"], 0)) / 2
        if a["nature"] == "bullish":
            score += abs(weight) * 2
            bull.append(f"{a['planet_a']} {a['aspect']}° {a['planet_b']} (orb {a['orb']}°) — supportive")
        elif a["nature"] == "bearish":
            score -= abs(weight) * 2
            bear.append(f"{a['planet_a']} {a['aspect']}° {a['planet_b']} (orb {a['orb']}°) — tense")

    # Mercury retrograde — comms / orders
    if merc_retro:
        score -= 5
        vol += 10
        bear.append("Mercury retrograde — execution/comms risk; expect order errors & whipsaws")

    # Moon phase & paksha
    if phase["paksha"] == "Shukla":
        score += 3
        bull.append(f"Shukla paksha (waxing) — accumulation bias; tithi {phase['tithi']}")
    else:
        score -= 2
        bear.append(f"Krishna paksha (waning) — distribution bias; tithi {phase['tithi']}")

    if phase["phase"] in ("New Moon", "Full Moon"):
        vol += 15
        bear.append(f"{phase['phase']} — heightened reversal & volatility risk")

    # Eclipse proximity
    if ecl["solar_days"] is not None and abs(ecl["solar_days"]) < 10:
        score -= 6
        vol += 12
        bear.append(f"Solar eclipse within {ecl['solar_days']}d — major reversal window")
    if ecl["lunar_days"] is not None and abs(ecl["lunar_days"]) < 7:
        score -= 4
        vol += 10
        bear.append(f"Lunar eclipse within {ecl['lunar_days']}d — emotional reversals")

    # Saturn / Rahu retrograde flags
    for p in ("Saturn", "Rahu"):
        if pos[p].retrograde:
            score -= 3
            bear.append(f"{p} retrograde — long-term restrictive influence")

    # Jupiter direct → bullish bias for capital flows
    if not pos["Jupiter"].retrograde:
        score += 4
        bull.append("Jupiter direct — favorable for capital expansion")

    # Clamp
    score = max(0.0, min(100.0, score))
    vol = max(0.0, min(100.0, vol))

    if score >= 60:
        bias = "BULLISH"
    elif score <= 40:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    headline = (
        f"{bias.title()} planetary climate — Moon in {moon_nak['name']} "
        f"({phase['phase']}, {phase['paksha']} paksha)"
        + (" • Mercury Rx" if merc_retro else "")
    )

    # Intraday timing windows: hours where Moon changes nakshatra/sign or strong aspects perfect.
    # For MVP we surface the start of the next nakshatra transition for the Moon.
    moon_long = pos["Moon"].longitude
    span = 360 / 27
    next_nak_deg = (int(moon_long / span) + 1) * span
    deg_to_next = (next_nak_deg - moon_long) % 360
    moon_speed_deg_per_hr = pos["Moon"].speed / 24 if pos["Moon"].speed else 0.55
    hours_to_next = deg_to_next / moon_speed_deg_per_hr if moon_speed_deg_per_hr else None
    intraday = []
    if hours_to_next is not None and hours_to_next < 24:
        intraday.append({
            "event": "Moon enters next nakshatra",
            "hours_from_now": round(hours_to_next, 2),
            "expected_effect": "short-term sentiment shift; possible reversal",
        })

    result = AstroSentiment(
        score=score,
        bias=bias,
        headline=headline,
        bullish_factors=bull,
        bearish_factors=bear,
        intraday_windows=intraday,
        volatility_pct=vol,
        raw={
            "planets": {k: v.to_dict() for k, v in pos.items()},
            "moon_phase": phase,
            "aspects": asp,
            "mercury_retrograde": merc_retro,
            "eclipse": ecl,
        },
    )
    if len(_sentiment_cache) > 8:
        _sentiment_cache.pop(next(iter(_sentiment_cache)))
    _sentiment_cache[key] = result
    return result


def symbol_astro_match(symbol: str, dt: datetime | None = None) -> dict:
    """Per-symbol astrology score: how aligned is `symbol` with the *current*
    planetary climate.

    Heuristic:
      • Derive a 'symbol nakshatra' by hashing the symbol into one of the 27
        nakshatras (deterministic per symbol).
      • Compare its ruling planet with currently strong planets (Jupiter direct,
        Moon's nakshatra ruler, etc.).
      • Penalise if the symbol's planetary lord is currently retrograde or
        afflicted.
      • Bonus if today's Moon is in the same nakshatra (or 9th/19th from it —
        traditional anuradha/janma triads).

    Returns:
        { score: 0..100, bias: BULLISH/BEARISH/NEUTRAL,
          symbol_nakshatra: {...}, reasons: [...] }
    """
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))

    # Deterministic mapping symbol → nakshatra index 0..26
    sym_clean = "".join(c for c in symbol.upper() if c.isalpha())
    sym_seed = sum(ord(c) * (i + 1) for i, c in enumerate(sym_clean)) if sym_clean else 0
    sym_nak_idx = sym_seed % 27
    sym_nak_name, sym_nak_ruler, sym_nak_nature = NAKSHATRAS[sym_nak_idx]

    positions = planet_positions(dt)
    moon_nak = positions["Moon"].nakshatra
    sentiment = market_sentiment(dt)

    reasons: list[str] = []
    score = 50.0

    # 1) Intrinsic nakshatra nature
    if sym_nak_nature == "bullish":
        score += 8
        reasons.append(f"{symbol} symbol-nakshatra {sym_nak_name} is wealth-favorable")
    elif sym_nak_nature == "bearish":
        score -= 8
        reasons.append(f"{symbol} symbol-nakshatra {sym_nak_name} is volatile")

    # 2) Moon transit synchrony
    distance = (moon_nak["index"] - 1 - sym_nak_idx) % 27
    if distance == 0:
        score += 14
        reasons.append(f"Moon today in {moon_nak['name']} = {symbol}'s nakshatra (janma — high activation)")
    elif distance in (8, 16):     # 9th & 17th from janma — sympathetic triads
        score += 7
        reasons.append(f"Moon in {moon_nak['name']} — sympathetic ({distance + 1}th from {symbol} nakshatra)")
    elif distance in (2, 5, 11, 20):  # classically tense placements
        score -= 6
        reasons.append(f"Moon in {moon_nak['name']} — {distance + 1}th tara from {symbol}: caution")

    # 3) Ruling planet status
    ruler = sym_nak_ruler
    if ruler in positions:
        p = positions[ruler]
        if p.retrograde and ruler not in ("Rahu", "Ketu"):
            score -= 6
            reasons.append(f"{symbol}'s ruling planet {ruler} is retrograde — sluggish")
        else:
            score += 4
            reasons.append(f"{symbol}'s ruling planet {ruler} is direct — vitality")

    # 4) Tilt by overall market climate
    if sentiment.bias == "BULLISH":
        score += 4
    elif sentiment.bias == "BEARISH":
        score -= 4

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    return {
        "symbol": symbol,
        "score": round(score, 2),
        "bias": bias,
        "symbol_nakshatra": {
            "name": sym_nak_name,
            "index": sym_nak_idx + 1,
            "ruler": sym_nak_ruler,
            "nature": sym_nak_nature,
        },
        "moon_nakshatra": moon_nak,
        "tara_from_symbol": distance + 1,
        "reasons": reasons,
    }


def transits_snapshot(dt: datetime | None = None) -> dict:
    """Lightweight payload for the /astrology/transits endpoint."""
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))
    pos = planet_positions(dt)
    return {
        "asof": dt.isoformat(),
        "timezone": settings.astro_timezone,
        "ayanamsa": settings.astro_ayanamsa,
        "planets": {k: v.to_dict() for k, v in pos.items()},
        "moon_phase": moon_phase(dt),
        "mercury_retrograde": mercury_retrograde(dt),
    }
