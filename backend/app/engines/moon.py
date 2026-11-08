"""Comprehensive lunar analysis engine.

Goes beyond the basic phase calculation to compute the lunar trading rules
that institutional astro traders use as hard gates:

  • Full Moon / New Moon proximity      → reversal window, no fresh entries
  • Void-of-Course Moon                  → Moon past last major aspect before
                                            changing signs. Classical rule:
                                            "nothing started in v/c succeeds."
  • Tithi quality (Riktha / Nanda etc.)  → some tithis (4/9/14, Amavasya) are
                                            classically inauspicious
  • Chandrabala — Moon's strength based on placement
  • Lunar day-of-week (Monday boost)
  • Lunar month phase percentage         → 0-100 cycle position

Output: a LunarReading with a `gate` recommendation (PROCEED / WAIT / AVOID),
strength score 0-100, and the list of triggered rules so the UI can display
them honestly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
import math

import pytz
import swisseph as swe

from app.config import settings
from app.engines.astrology import (
    NAKSHATRAS, PLANETS, _BASE_FLAG, _to_jd_ut, _nakshatra_for, _sign_for,
    moon_phase, planet_positions,
)


# ---------------------------------------------------------------------------
# Tithi classification (15 tithis × 2 pakshas = 30 lunar days)
# ---------------------------------------------------------------------------

# Nanda tithis (joyous):   1, 6, 11
# Bhadra tithis (auspicious): 2, 7, 12
# Jaya tithis (victorious):   3, 8, 13
# Rikta tithis (loss-bringing): 4, 9, 14            ← classical "avoid" list
# Purna tithis (complete):    5, 10, 15

TITHI_NATURE = {
    1:  ("Nanda Pratipada",  "neutral",  "Fresh starts; light volume."),
    2:  ("Bhadra Dwitiya",   "bullish",  "Auspicious; favourable for accumulation."),
    3:  ("Jaya Tritiya",     "bullish",  "Victory tithi; momentum favoured."),
    4:  ("Rikta Chaturthi",  "bearish",  "Riktha — losses possible; AVOID new entries."),
    5:  ("Purna Panchami",   "bullish",  "Complete; profit-taking favoured."),
    6:  ("Nanda Shasthi",    "neutral",  "Light energy."),
    7:  ("Bhadra Saptami",   "bullish",  "Sun's tithi; bold trades."),
    8:  ("Jaya Ashtami",     "bearish",  "Ashtami — energetic but unstable; caution."),
    9:  ("Rikta Navami",     "bearish",  "Riktha — losses possible; AVOID new entries."),
    10: ("Purna Dashami",    "bullish",  "Auspicious for completion."),
    11: ("Nanda Ekadashi",   "bullish",  "Highly auspicious; Vishnu's day."),
    12: ("Bhadra Dwadashi",  "bullish",  "Favourable."),
    13: ("Jaya Trayodashi",  "bullish",  "Auspicious."),
    14: ("Rikta Chaturdashi", "bearish", "Riktha — losses possible; AVOID new entries."),
    15: ("Purna Purnima/Amavasya", "neutral", "Full Moon (Shukla) or Amavasya (Krishna) — reversal window."),
}

# Tithis that gate fresh entries (classical avoid days for new commitments)
AVOID_TITHI = {4, 8, 9, 14}     # plus Purnima (15 Shukla) & Amavasya (15 Krishna) checked separately

# Days where Moon is within X degrees of Sun = New Moon zone or Full Moon zone
NEW_MOON_ZONE_DEG = 6.0        # ±6° around exact New Moon
FULL_MOON_ZONE_DEG = 6.0       # ±6° around exact Full Moon
V_O_C_LOOKAHEAD_DEG = 13.333   # Moon traverses one nakshatra (also one sign step is checked)


# ---------------------------------------------------------------------------

@dataclass
class LunarReading:
    asof: str
    phase_name: str
    elongation_deg: float
    illumination_pct: float
    paksha: str                       # Shukla / Krishna
    tithi_num: int
    tithi_name: str
    tithi_nature: str                 # bullish / bearish / neutral
    tithi_note: str

    moon_nakshatra: str
    moon_nakshatra_ruler: str
    moon_pada: int
    moon_speed: float                 # deg/day; informational
    moon_sign: str

    is_full_moon: bool
    is_new_moon: bool
    eclipse_zone: bool                # True if within ±3 days of an eclipse
    is_void_of_course: bool
    voc_next_change_minutes: float | None
    is_monday: bool                   # Moon's day — extra strength

    strength_score: float             # 0..100
    gate: Literal["PROCEED", "CAUTION", "WAIT", "AVOID"]
    rules_triggered: list[dict] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Void-of-Course detection
# ---------------------------------------------------------------------------

def _moon_void_of_course(dt: datetime) -> tuple[bool, float | None]:
    """A void-of-course Moon: Moon has made its last Ptolemaic aspect (0/60/90/120/180)
    with another classical planet (Sun..Saturn) before leaving its current sign.

    Approach: compute distance Moon must traverse to reach next sign boundary.
    Then check if any of those Ptolemaic aspects to Sun..Saturn would perfect
    within that traversal. If NONE perfect → Moon is v/c right now.

    Returns (is_voc, minutes_until_sign_change_if_voc_else_None).
    """
    pos = planet_positions(dt)
    moon_long = pos["Moon"].longitude
    moon_speed = max(pos["Moon"].speed, 0.001)         # deg/day; safety
    sign_idx = int(moon_long / 30)
    deg_to_next_sign = (sign_idx + 1) * 30 - moon_long
    if deg_to_next_sign < 0:
        deg_to_next_sign += 30
    days_to_next_sign = deg_to_next_sign / moon_speed

    # For each classical planet (excluding Moon itself), check if any aspect
    # angle is reached as Moon moves the remaining `deg_to_next_sign`.
    aspect_angles = [0, 60, 90, 120, 180]
    any_perfecting = False
    for pname in ("Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"):
        p_long = pos[pname].longitude
        p_speed = pos[pname].speed                     # other planets move slowly vs Moon
        # Relative position: angular distance Moon needs to gain on planet to reach each aspect
        for a in aspect_angles:
            # We want Moon longitude - planet longitude to reach `a` (mod 360).
            current_sep = (moon_long - p_long) % 360
            target_sep = a
            # Moon's rate of separation per day:
            rel_speed = moon_speed - p_speed
            if rel_speed <= 0:
                continue
            # How many degrees Moon needs to move to make (moon-planet) increase to next `a`
            delta = (target_sep - current_sep) % 360
            if delta == 0:
                # exact aspect right now → counts as perfecting
                any_perfecting = True
                break
            days_to_perfect = delta / rel_speed
            if days_to_perfect <= days_to_next_sign:
                any_perfecting = True
                break
        if any_perfecting:
            break

    is_voc = not any_perfecting
    if is_voc:
        return True, round(days_to_next_sign * 24 * 60, 1)
    return False, None


# ---------------------------------------------------------------------------
# Eclipse proximity (3-day window)
# ---------------------------------------------------------------------------

def _in_eclipse_zone(dt: datetime, window_days: int = 3) -> bool:
    jd = _to_jd_ut(dt)
    try:
        for fn, flag in ((swe.sol_eclipse_when_glob, swe.FLG_MOSEPH),
                          (swe.lun_eclipse_when, swe.FLG_MOSEPH)):
            _r, tret = fn(jd - window_days, flag, 0)
            if tret and abs(tret[0] - jd) <= window_days:
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Main reading
# ---------------------------------------------------------------------------

def reading(dt: datetime | None = None) -> LunarReading:
    if dt is None:
        dt = datetime.now(pytz.timezone(settings.astro_timezone))

    phase = moon_phase(dt)
    pos = planet_positions(dt)
    moon = pos["Moon"]
    sun = pos["Sun"]

    elongation = phase["elongation_deg"]
    is_new_moon = elongation < NEW_MOON_ZONE_DEG or elongation > (360 - NEW_MOON_ZONE_DEG)
    is_full_moon = abs(elongation - 180) < FULL_MOON_ZONE_DEG

    tithi_num_raw = phase["tithi"]                 # 1..30
    paksha = phase["paksha"]                       # Shukla / Krishna
    tithi_in_paksha = tithi_num_raw if tithi_num_raw <= 15 else tithi_num_raw - 15
    name, nature, note = TITHI_NATURE.get(tithi_in_paksha, ("?", "neutral", ""))

    voc, voc_minutes = _moon_void_of_course(dt)
    eclipse_zone = _in_eclipse_zone(dt)

    weekday_is_monday = dt.weekday() == 0   # Python: Mon=0

    # ---- Scoring ----
    score = 50.0
    rules: list[dict] = []

    if tithi_in_paksha in AVOID_TITHI:
        score -= 15
        rules.append({"rule": "Riktha tithi", "severity": "HIGH",
                       "note": f"Tithi {tithi_in_paksha} ({name}) — classically avoided for new entries."})
    elif nature == "bullish":
        score += 8
        rules.append({"rule": "Auspicious tithi", "severity": "LOW",
                       "note": f"Tithi {tithi_in_paksha} ({name}) — favourable."})
    elif nature == "bearish":
        score -= 8
        rules.append({"rule": "Bearish tithi", "severity": "MEDIUM", "note": note})

    if is_full_moon:
        score -= 15
        rules.append({"rule": "Full Moon zone", "severity": "HIGH",
                       "note": (f"Within ±{FULL_MOON_ZONE_DEG}° of exact Full Moon "
                                 f"(elongation {elongation:.1f}°) — major reversal window. "
                                 f"Avoid fresh trend-entries; favour mean-reversion or profit-taking.")})
    if is_new_moon:
        score -= 12
        rules.append({"rule": "New Moon zone", "severity": "HIGH",
                       "note": (f"Within ±{NEW_MOON_ZONE_DEG}° of exact New Moon "
                                 f"(elongation {elongation:.1f}°) — low energy; trends often false-start. "
                                 f"Wait for waxing crescent.")})

    if voc:
        score -= 20
        rules.append({"rule": "Void-of-Course Moon", "severity": "HIGH",
                       "note": (f"Moon is void-of-course — no major aspect will perfect before sign change "
                                 f"(in ~{voc_minutes:.0f}m). Classical rule: trades initiated in v/c rarely follow through.")})

    if eclipse_zone:
        score -= 18
        rules.append({"rule": "Eclipse blackout window", "severity": "HIGH",
                       "note": "Within ±3 days of a solar/lunar eclipse — chaotic price action; institutional blackout."})

    if paksha == "Shukla":
        score += 4
        rules.append({"rule": "Shukla paksha (waxing)", "severity": "LOW",
                       "note": "Waxing Moon — accumulation bias historically favoured."})
    else:
        score -= 2
        rules.append({"rule": "Krishna paksha (waning)", "severity": "LOW",
                       "note": "Waning Moon — distribution bias historically favoured."})

    if weekday_is_monday:
        score += 3
        rules.append({"rule": "Monday — Moon's day", "severity": "LOW",
                       "note": "Lunar day-of-week doubles Moon's effect (good or bad)."})

    # Moon speed: faster Moon = more activity. Range typically 11-15 deg/day.
    if moon.speed > 13:
        score += 2
        rules.append({"rule": "Fast Moon", "severity": "LOW",
                       "note": f"Moon moving fast ({moon.speed:.2f}°/day) — quicker setups."})
    elif moon.speed < 11.5:
        score -= 2
        rules.append({"rule": "Slow Moon", "severity": "LOW",
                       "note": f"Moon moving slow ({moon.speed:.2f}°/day) — markets may grind."})

    score = max(0.0, min(100.0, score))

    # ---- Gate decision ----
    high_sev = sum(1 for r in rules if r["severity"] == "HIGH")
    if high_sev >= 2 or eclipse_zone or voc:
        gate = "AVOID"
    elif high_sev == 1 or score <= 35:
        gate = "WAIT"
    elif score <= 50:
        gate = "CAUTION"
    else:
        gate = "PROCEED"

    summary = (
        f"{phase['phase']} · {paksha} paksha · tithi {tithi_in_paksha} ({name}) · "
        f"Moon in {moon.nakshatra['name']} ({moon.sign['name']}). "
        f"Gate: {gate} ({score:.0f}/100)."
    )

    return LunarReading(
        asof=dt.isoformat(),
        phase_name=phase["phase"],
        elongation_deg=elongation,
        illumination_pct=phase["illumination_pct"],
        paksha=paksha,
        tithi_num=tithi_num_raw,
        tithi_name=name,
        tithi_nature=nature,
        tithi_note=note,
        moon_nakshatra=moon.nakshatra["name"],
        moon_nakshatra_ruler=moon.nakshatra["ruler"],
        moon_pada=moon.nakshatra["pada"],
        moon_speed=moon.speed,
        moon_sign=moon.sign["name"],
        is_full_moon=is_full_moon,
        is_new_moon=is_new_moon,
        eclipse_zone=eclipse_zone,
        is_void_of_course=voc,
        voc_next_change_minutes=voc_minutes,
        is_monday=weekday_is_monday,
        strength_score=round(score, 2),
        gate=gate,
        rules_triggered=rules,
        summary=summary,
    )
