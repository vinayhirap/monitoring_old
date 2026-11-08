"""Forecast engine — forward-looking 7/14-day outlook.

For any future date the engine computes:
  • Moon's nakshatra & sign  (changes ~once/day — sentiment shift)
  • Day-lord (weekday) hora climate
  • Tara (relationship between Moon's nakshatra that day and the symbol's nakshatra)
  • Numerology compatibility of (symbol root) with (that date's date number)
  • Gann time-cycle proximity (does any 30/45/60/90/144/180/360-day cycle hit?)
  • Major aspects forming/breaking
  • Mercury retrograde / eclipse proximity
  • Best 1-3 hora windows during NSE hours (09:15–15:30 IST)

Daily bias score is the weighted blend → BULLISH / BEARISH / NEUTRAL per day.

Market outlook lists ingresses, nakshatra transitions, Mercury Rx turns and
eclipse dates in the lookahead window.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
import pytz
import swisseph as swe

from app.config import settings
from app.engines import astrology, numerology, gann, hora as hora_eng
from app.engines.astrology import NAKSHATRAS, PLANETS, planet_positions, _to_jd_ut


# ---------------------------------------------------------------------------
# Per-day per-symbol bias
# ---------------------------------------------------------------------------

@dataclass
class DailyBias:
    date: str                       # YYYY-MM-DD
    weekday: str                    # Monday..Sunday
    day_lord: str                   # ruler of the first hora that day (Sun/Moon/...)
    moon_nakshatra: str
    moon_pada: int
    tara_from_symbol: int           # 1..27 — 1 is janma (most activating)
    symbol_nakshatra: str
    score: float                    # 0..100 (>50 bullish)
    bias: str                       # BULLISH/BEARISH/NEUTRAL
    grade: str                      # AVOID / WEAK / OK / GOOD / EXCELLENT
    intraday_windows: list[dict]    # [{ruler, bias, start_hhmm, end_hhmm}, ...]
    events: list[str]               # key events that day (nakshatra change, ingress, etc.)
    reasons: list[str]


@dataclass
class SymbolOutlook:
    symbol: str
    symbol_nakshatra: str
    symbol_nakshatra_ruler: str
    symbol_root_number: int
    asof: str
    days: list[dict]                # list of DailyBias.to_dict()
    best_buy_day: str | None        # ISO date
    best_sell_day: str | None
    summary: str

    def to_dict(self) -> dict:
        return self.__dict__


# Mapping symbol → its nakshatra (mirror of astrology.symbol_astro_match logic)
def _symbol_nakshatra_index(symbol: str) -> int:
    sym_clean = "".join(c for c in symbol.upper() if c.isalpha())
    sym_seed = sum(ord(c) * (i + 1) for i, c in enumerate(sym_clean)) if sym_clean else 0
    return sym_seed % 27


def _grade(score: float) -> str:
    if score >= 75: return "EXCELLENT"
    if score >= 60: return "GOOD"
    if score >= 45: return "OK"
    if score >= 30: return "WEAK"
    return "AVOID"


def _date_number(d: date) -> int:
    return numerology._digit_sum(d.day + d.month + d.year)


def _intraday_hora_windows(d: date, limit: int = 3) -> list[dict]:
    """Sample hora at NSE open + 11:30 + 14:30 to identify the daytime hora climate."""
    tz = pytz.timezone(settings.astro_timezone)
    samples = [
        d.strftime("%Y-%m-%d") + " 09:30",
        d.strftime("%Y-%m-%d") + " 11:30",
        d.strftime("%Y-%m-%d") + " 14:00",
    ]
    out = []
    seen = set()
    for s in samples:
        try:
            dt_naive = datetime.strptime(s, "%Y-%m-%d %H:%M")
            dt = tz.localize(dt_naive)
            h = hora_eng.current_hora(dt)
            tag = (h.ruler, h.bias)
            if tag in seen:
                continue
            seen.add(tag)
            # estimate window end: + duration_minutes
            end_dt = dt + timedelta(minutes=h.duration_minutes)
            out.append({
                "ruler": h.ruler,
                "bias": h.bias,
                "weight": h.weight,
                "start": dt.strftime("%H:%M"),
                "end": end_dt.strftime("%H:%M") if end_dt.day == dt.day else "15:30",
                "notes": h.notes,
            })
        except Exception:
            continue
    # Rank by bias × weight (favourable first)
    rank_map = {"bullish": 1, "neutral": 0, "bearish": -1}
    out.sort(key=lambda w: -rank_map.get(w["bias"], 0) * w["weight"])
    return out[:limit]


def _events_on(d: date, prev_pos: dict | None) -> tuple[list[str], dict]:
    """Detect notable astro events on date d. Returns (events_list, positions_today)."""
    tz = pytz.timezone(settings.astro_timezone)
    noon = tz.localize(datetime.combine(d, datetime.min.time().replace(hour=12)))
    pos = planet_positions(noon)
    events: list[str] = []
    if prev_pos:
        # Moon nakshatra change
        if pos["Moon"].nakshatra["name"] != prev_pos["Moon"].nakshatra["name"]:
            events.append(f"Moon enters {pos['Moon'].nakshatra['name']} ({pos['Moon'].nakshatra['ruler']})")
        # Any planet sign change (ingress)
        for p in ("Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"):
            if pos[p].sign["name"] != prev_pos[p].sign["name"]:
                events.append(f"{p} ingresses {pos[p].sign['name']}")
        # Retrograde turn
        for p in ("Mercury", "Venus", "Mars", "Jupiter", "Saturn"):
            if pos[p].retrograde != prev_pos[p].retrograde:
                evt = "stations retrograde" if pos[p].retrograde else "turns direct"
                events.append(f"{p} {evt}")
    return events, pos


def _daily_bias_for(
    symbol: str, symbol_nak_idx: int, symbol_root: int,
    d: date, prev_pos: dict | None,
    gann_cycle_dates: set[str],
) -> tuple[DailyBias, dict]:
    """Compute the full daily-bias card for `symbol` on date `d`."""
    tz = pytz.timezone(settings.astro_timezone)
    noon = tz.localize(datetime.combine(d, datetime.min.time().replace(hour=12)))

    # planet positions (also used for events)
    events, pos = _events_on(d, prev_pos)
    moon_nak = pos["Moon"].nakshatra

    # tara from symbol nakshatra (1 = janma, 9 & 18 sympathetic; 3/5/7 challenging)
    tara = ((moon_nak["index"] - 1 - symbol_nak_idx) % 27) + 1

    # day-lord = first hora of that day
    weekday = d.weekday()                      # Python: Mon=0..Sun=6
    day_lord = hora_eng.WEEKDAY_FIRST_HORA[weekday]
    day_lord_bias = hora_eng.HORA_NATURE[day_lord]["bias"]

    # numerology compatibility
    date_num = _date_number(d)
    num_compat = numerology.compatibility(symbol_root, date_num)

    # market sentiment for that date
    sentiment = astrology.market_sentiment(noon)

    # ---- scoring ----
    score = 50.0
    reasons: list[str] = []

    # 1) Moon nakshatra intrinsic nature
    nak_name, nak_ruler, nak_nature = NAKSHATRAS[moon_nak["index"] - 1]
    if nak_nature == "bullish":
        score += 6
        reasons.append(f"Moon in {nak_name} (wealth-favorable)")
    elif nak_nature == "bearish":
        score -= 6
        reasons.append(f"Moon in {nak_name} (volatile)")

    # 2) Tara — distance Moon → symbol's nakshatra
    if tara == 1:
        score += 12
        reasons.append(f"Janma tara (Moon on {symbol}'s nakshatra) — high activation")
    elif tara in (9, 17):
        score += 6
        reasons.append(f"Sympathetic tara {tara} — supportive")
    elif tara in (3, 5, 7):
        score -= 8
        reasons.append(f"Challenging tara {tara} — caution")

    # 3) Day-lord climate
    if day_lord_bias == "bullish":
        score += 5
        reasons.append(f"{d.strftime('%A')} = {day_lord} day (bullish climate)")
    elif day_lord_bias == "bearish":
        score -= 5
        reasons.append(f"{d.strftime('%A')} = {day_lord} day (bearish/restrictive)")

    # 4) Numerology compatibility
    if num_compat >= 75:
        score += 4
        reasons.append(f"Date {d.day}/{d.month} root {date_num} highly compatible ({num_compat:.0f})")
    elif num_compat <= 30:
        score -= 4
        reasons.append(f"Date root {date_num} incompatible with {symbol} ({num_compat:.0f})")

    # 5) Overall astro market sentiment tilt
    if sentiment.bias == "BULLISH":
        score += 3
    elif sentiment.bias == "BEARISH":
        score -= 3

    # 6) Gann time-cycle hit
    if d.isoformat() in gann_cycle_dates:
        score -= 4   # reversal risk — reduce conviction either way
        reasons.append("Major Gann cycle date — potential reversal")
        events.append("Gann cycle reversal window")

    # 7) Mercury Rx penalty
    if pos["Mercury"].retrograde:
        score -= 3
        reasons.append("Mercury retrograde — execution risk")

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    windows = _intraday_hora_windows(d)

    return DailyBias(
        date=d.isoformat(),
        weekday=d.strftime("%A"),
        day_lord=day_lord,
        moon_nakshatra=nak_name,
        moon_pada=moon_nak["pada"],
        tara_from_symbol=tara,
        symbol_nakshatra=NAKSHATRAS[symbol_nak_idx][0],
        score=round(score, 2),
        bias=bias,
        grade=_grade(score),
        intraday_windows=windows,
        events=events,
        reasons=reasons,
    ), pos


# ---------------------------------------------------------------------------
# Public: per-symbol weekly outlook
# ---------------------------------------------------------------------------

def symbol_weekly_outlook(symbol: str, days: int = 7, start: date | None = None) -> SymbolOutlook:
    start = start or date.today()
    symbol = symbol.upper()
    sym_nak_idx = _symbol_nakshatra_index(symbol)
    sym_nak_name, sym_nak_ruler, _ = NAKSHATRAS[sym_nak_idx]
    sym_root = numerology._full_reduce(numerology._compound(symbol, numerology.PYTHAGOREAN))

    # Pre-compute Gann cycle dates the user should be aware of
    gann_dates = {c["projected_date"] for c in gann.time_cycles(start - timedelta(days=30))}

    daily: list[DailyBias] = []
    prev_pos: dict | None = None
    for i in range(days):
        d = start + timedelta(days=i)
        db, pos = _daily_bias_for(symbol, sym_nak_idx, sym_root, d, prev_pos, gann_dates)
        daily.append(db)
        prev_pos = pos

    daily_dicts = [d.__dict__ for d in daily]
    # Best buy day = highest score; best sell = lowest score (only if decisive enough)
    best_buy = max(daily, key=lambda x: x.score)
    best_sell = min(daily, key=lambda x: x.score)

    summary = (
        f"{symbol} symbol-nakshatra: {sym_nak_name} (ruled by {sym_nak_ruler}). "
        f"Root number {sym_root}. "
        f"Highest-edge BUY day: {best_buy.date} ({best_buy.grade}). "
        f"Highest-edge SELL day: {best_sell.date} ({best_sell.grade})."
    )

    return SymbolOutlook(
        symbol=symbol,
        symbol_nakshatra=sym_nak_name,
        symbol_nakshatra_ruler=sym_nak_ruler,
        symbol_root_number=sym_root,
        asof=datetime.now().isoformat(),
        days=daily_dicts,
        best_buy_day=best_buy.date if best_buy.score >= 55 else None,
        best_sell_day=best_sell.date if best_sell.score <= 45 else None,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Market-wide weekly calendar
# ---------------------------------------------------------------------------

@dataclass
class MarketCalendarEntry:
    date: str
    weekday: str
    day_lord: str
    day_lord_bias: str
    moon_nakshatra: str
    moon_paksha: str
    tithi: int
    events: list[str]
    score: float                # market-wide bias 0..100
    bias: str

    def to_dict(self) -> dict:
        return self.__dict__


def _scan_eclipses_in_window(start: date, days: int) -> list[dict]:
    """Scan for solar/lunar eclipses within [start, start+days]."""
    out = []
    tz = pytz.timezone(settings.astro_timezone)
    jd_start = _to_jd_ut(tz.localize(datetime.combine(start, datetime.min.time())))
    try:
        # Solar
        _r, tret = swe.sol_eclipse_when_glob(jd_start - 1, swe.FLG_MOSEPH, 0)
        if tret and tret[0] - jd_start <= days:
            y, m, d, _h = swe.revjul(tret[0], swe.GREG_CAL)
            out.append({"type": "Solar Eclipse", "date": f"{int(y):04d}-{int(m):02d}-{int(d):02d}",
                         "jd_offset_days": round(tret[0] - jd_start, 2)})
    except Exception:
        pass
    try:
        # Lunar
        _r, tret = swe.lun_eclipse_when(jd_start - 1, swe.FLG_MOSEPH, 0)
        if tret and tret[0] - jd_start <= days:
            y, m, d, _h = swe.revjul(tret[0], swe.GREG_CAL)
            out.append({"type": "Lunar Eclipse", "date": f"{int(y):04d}-{int(m):02d}-{int(d):02d}",
                         "jd_offset_days": round(tret[0] - jd_start, 2)})
    except Exception:
        pass
    return out


def market_weekly_calendar(days: int = 7, start: date | None = None) -> dict:
    start = start or date.today()
    tz = pytz.timezone(settings.astro_timezone)
    entries: list[MarketCalendarEntry] = []
    prev_pos: dict | None = None
    for i in range(days):
        d = start + timedelta(days=i)
        noon = tz.localize(datetime.combine(d, datetime.min.time().replace(hour=12)))
        events, pos = _events_on(d, prev_pos)
        prev_pos = pos

        moon_nak = pos["Moon"].nakshatra
        phase = astrology.moon_phase(noon)
        sentiment = astrology.market_sentiment(noon)
        weekday = d.weekday()
        day_lord = hora_eng.WEEKDAY_FIRST_HORA[weekday]
        day_lord_bias = hora_eng.HORA_NATURE[day_lord]["bias"]

        # NSE holiday flag
        is_weekend = weekday >= 5
        if is_weekend:
            events.append("⚠ NSE closed (weekend)")

        entries.append(MarketCalendarEntry(
            date=d.isoformat(),
            weekday=d.strftime("%A"),
            day_lord=day_lord,
            day_lord_bias=day_lord_bias,
            moon_nakshatra=moon_nak["name"],
            moon_paksha=phase["paksha"],
            tithi=phase["tithi"],
            events=events,
            score=round(sentiment.score, 2),
            bias=sentiment.bias,
        ))

    # Surface upcoming Gann cycle dates in the window
    upcoming_gann = [c for c in gann.time_cycles(start - timedelta(days=30))
                     if start.isoformat() <= c["projected_date"] <= (start + timedelta(days=days)).isoformat()]

    summary_evts = [
        e.weekday + " " + e.date + ": " + (" | ".join(e.events) if e.events else "no major events")
        for e in entries if e.events
    ][:6]

    eclipses = _scan_eclipses_in_window(start, days)

    return {
        "from": start.isoformat(),
        "days": [e.to_dict() for e in entries],
        "upcoming_gann_dates": upcoming_gann[:8],
        "upcoming_eclipses": eclipses,
        "summary_events": summary_evts,
        "disclaimer": "Educational use only — astro predictions are confluence layers, not guaranteed forecasts.",
    }
