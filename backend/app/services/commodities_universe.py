"""MCX commodity universe + Mundane astrology (planetary rulership of commodities).

Traditional Mundane astrology — each commodity has a primary ruling planet
that historically correlates with its price cycles:

    Gold        → Sun       (24-hr & solar-year cycles)
    Silver      → Moon      (synodic-month cycles, esp full/new moon turns)
    Copper      → Venus     (luxury/industrial demand cycles)
    Crude Oil   → Mars/Saturn (energy/conflict cycles; Saturn for long-term lows)
    Natural Gas → Mars      (volatile, war-correlated)
    Zinc        → Mars      (industrial, conflict)
    Aluminium   → Mercury   (industrial, transport)
    Nickel      → Saturn    (industrial, slow cycles)
    Lead        → Saturn    (heavy, slow)

The commodity's astrology score uses the same logic as equities but anchored
on the COMMODITY's ruling planet rather than the symbol's letter-vibration
nakshatra.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Commodity universe — Angel One MCX tradable symbols
# ---------------------------------------------------------------------------

# Symbol → (display name, ruling planet, secondary planet, category)
COMMODITIES: dict[str, dict] = {
    "GOLD":       {"display": "Gold",        "ruler": "Sun",     "second": "Venus",   "category": "Precious metals"},
    "GOLDM":      {"display": "Gold Mini",   "ruler": "Sun",     "second": "Venus",   "category": "Precious metals"},
    "SILVER":     {"display": "Silver",      "ruler": "Moon",    "second": "Venus",   "category": "Precious metals"},
    "SILVERM":    {"display": "Silver Mini", "ruler": "Moon",    "second": "Venus",   "category": "Precious metals"},
    "CRUDEOIL":   {"display": "Crude Oil",   "ruler": "Mars",    "second": "Saturn",  "category": "Energy"},
    "CRUDEOILM":  {"display": "Crude Oil Mini","ruler": "Mars",  "second": "Saturn",  "category": "Energy"},
    "NATURALGAS": {"display": "Natural Gas", "ruler": "Mars",    "second": "Mercury", "category": "Energy"},
    "NATGASMINI": {"display": "Nat Gas Mini","ruler": "Mars",    "second": "Mercury", "category": "Energy"},
    "COPPER":     {"display": "Copper",      "ruler": "Venus",   "second": "Mars",    "category": "Base metals"},
    "ZINC":       {"display": "Zinc",        "ruler": "Mars",    "second": "Saturn",  "category": "Base metals"},
    "ALUMINIUM":  {"display": "Aluminium",   "ruler": "Mercury", "second": "Saturn",  "category": "Base metals"},
    "NICKEL":     {"display": "Nickel",      "ruler": "Saturn",  "second": "Mars",    "category": "Base metals"},
    "LEAD":       {"display": "Lead",        "ruler": "Saturn",  "second": "Mars",    "category": "Base metals"},
}


def all_commodities() -> list[str]:
    return list(COMMODITIES.keys())


def info(symbol: str) -> dict | None:
    return COMMODITIES.get(symbol.upper())


def category_of(symbol: str) -> str:
    rec = COMMODITIES.get(symbol.upper())
    return rec["category"] if rec else "Other"


def ruling_planet(symbol: str) -> str | None:
    rec = COMMODITIES.get(symbol.upper())
    return rec["ruler"] if rec else None


# ---------------------------------------------------------------------------
# Commodity astrology score — uses ruling-planet status today instead of
# symbol-nakshatra letter hash (different from equity logic).
# ---------------------------------------------------------------------------

def commodity_astro_match(symbol: str, dt=None) -> dict:
    """Compute commodity-specific astrology score based on its ruling planet
    status today. Same shape as astrology.symbol_astro_match() so the
    aggregator can consume it without changes.
    """
    from datetime import datetime
    import pytz
    from app.config import settings
    from app.engines import astrology

    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))

    info_rec = info(symbol)
    if not info_rec:
        return {"symbol": symbol, "score": 50, "bias": "NEUTRAL",
                 "reasons": ["Not a recognized MCX commodity"]}

    positions = astrology.planet_positions(dt)
    sentiment = astrology.market_sentiment(dt)

    ruler_name = info_rec["ruler"]
    second_name = info_rec["second"]
    ruler = positions.get(ruler_name)
    second = positions.get(second_name)

    reasons: list[str] = []
    score = 50.0

    # 1. Primary ruler status — direct/retrograde
    if ruler is not None:
        if ruler.retrograde and ruler_name not in ("Rahu", "Ketu"):
            score -= 10
            reasons.append(f"{info_rec['display']}'s ruling planet {ruler_name} is RETROGRADE — sluggish bias")
        else:
            score += 8
            reasons.append(f"Ruling planet {ruler_name} is DIRECT — supportive of {info_rec['display']}")

    # 2. Primary ruler's nakshatra nature
    if ruler is not None:
        nak_nature = ruler.nakshatra["nature"]
        if nak_nature == "bullish":
            score += 7
            reasons.append(f"{ruler_name} in {ruler.nakshatra['name']} (bullish nakshatra)")
        elif nak_nature == "bearish":
            score -= 7
            reasons.append(f"{ruler_name} in {ruler.nakshatra['name']} (bearish nakshatra)")

    # 3. Secondary ruler — half weight
    if second is not None and second_name != ruler_name:
        if second.retrograde and second_name not in ("Rahu", "Ketu"):
            score -= 4
            reasons.append(f"Secondary ruler {second_name} is retrograde")
        else:
            score += 4

    # 4. Aspect between ruler and Sun (commodity demand cycle proxy)
    if ruler is not None and ruler_name != "Sun":
        sun = positions.get("Sun")
        if sun is not None:
            sep = abs(ruler.longitude - sun.longitude) % 360
            if sep > 180:
                sep = 360 - sep
            if sep < 8:
                score += 6
                reasons.append(f"{ruler_name} CONJUNCT Sun — strong demand cycle ({sep:.1f}°)")
            elif abs(sep - 120) < 8:
                score += 4
                reasons.append(f"{ruler_name} TRINE Sun — supportive aspect")
            elif abs(sep - 90) < 8:
                score -= 4
                reasons.append(f"{ruler_name} SQUARE Sun — tense aspect")
            elif abs(sep - 180) < 8:
                score -= 6
                reasons.append(f"{ruler_name} OPPOSITION Sun — peak tension")

    # 5. Market climate tilt
    if sentiment.bias == "BULLISH":
        score += 3
    elif sentiment.bias == "BEARISH":
        score -= 3

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    return {
        "symbol": symbol,
        "category": info_rec["category"],
        "display": info_rec["display"],
        "ruling_planet": ruler_name,
        "secondary_planet": second_name,
        "ruler_position": ruler.to_dict() if ruler is not None else None,
        "score": round(score, 2),
        "bias": bias,
        "reasons": reasons,
    }
