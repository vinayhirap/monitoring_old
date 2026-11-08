"""Hora (planetary hour) engine — Vedic muhurta timing.

Each day (sunrise → next sunrise) is divided into 24 horas, each ruled by a
classical planet. The first hora of a given day is ruled by that day's lord:
   Sun (Sun), Mon (Moon), Tue (Mars), Wed (Mercury),
   Thu (Jupiter), Fri (Venus), Sat (Saturn)

Subsequent horas cycle through the Chaldean order:
   Saturn → Jupiter → Mars → Sun → Venus → Mercury → Moon → Saturn …

We use a simplified daytime model (sunrise 06:00 IST → sunset 18:00 IST) which
is good enough for NSE market hours (09:15–15:30). For full precision, Swiss
Ephemeris-computed sunrise/sunset can be plugged in via `sunrise`/`sunset`
arguments.

Why this matters: muhurta says option-buying (CE/PE) entries timed in a
benefic hora hit far more often than the same entry in a malefic hora.
The pipeline uses Hora as a directional *consistency gate* — a CE BUY in
a Saturn/Mars hora gets flagged or downgraded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import pytz
import swisseph as swe

from app.config import settings


# Python weekday: Monday=0 … Sunday=6
WEEKDAY_FIRST_HORA = {
    6: "Sun",      # Sunday
    0: "Moon",     # Monday
    1: "Mars",     # Tuesday
    2: "Mercury",  # Wednesday
    3: "Jupiter",  # Thursday
    4: "Venus",    # Friday
    5: "Saturn",   # Saturday
}

# Chaldean sequence used for hora cycling
CHALDEAN_ORDER = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]

# Trading interpretation per ruler.
#   bias    – directional polarity for *trade entry* (bullish / bearish / neutral)
#   weight  – how strongly this hora's bias should be enforced (0..1)
#   notes   – human-readable rationale shown in UI
HORA_NATURE: dict[str, dict] = {
    "Sun":     {"bias": "bullish", "weight": 0.6,
                "notes": "Bold, leadership; large caps, gold, energy. OK for CE/long, weak for shorts."},
    "Moon":    {"bias": "neutral", "weight": 0.3,
                "notes": "Volatile, mood-driven; intraday scalps; FMCG, dairy, hospitality."},
    "Mars":    {"bias": "bearish", "weight": 0.7,
                "notes": "Aggressive/risky; breakdowns favored. Strong for PE/short, weak for CE/long."},
    "Mercury": {"bias": "bullish", "weight": 0.5,
                "notes": "Quick scalps, commerce; IT, broking, media. Mildly bullish."},
    "Jupiter": {"bias": "bullish", "weight": 1.0,
                "notes": "Most auspicious for buying — banking/finance/insurance. Strong CE/long bias."},
    "Venus":   {"bias": "bullish", "weight": 0.8,
                "notes": "Smooth uptrends; luxury, autos, FMCG. Strong for CE/long."},
    "Saturn":  {"bias": "bearish", "weight": 0.9,
                "notes": "Restrictive, heavy; PSU/infra/metals. Strong for PE/short, AVOID CE/long."},
}


@dataclass
class HoraInfo:
    asof: str
    timezone: str
    weekday: str
    is_day: bool
    hora_index: int             # 1..24
    duration_minutes: float
    ruler: str                  # current ruler
    bias: Literal["bullish", "bearish", "neutral"]
    weight: float
    notes: str
    next_change_in_minutes: float
    next_ruler: str
    sequence_remaining: list[dict]      # next ~5 horas with rulers
    market_open: bool           # NSE 09:15-15:30 IST

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _compute_sunrise_sunset(date_local: datetime) -> tuple[datetime, datetime]:
    """Compute actual local sunrise & sunset for the configured lat/lon via
    Swiss Ephemeris `rise_trans`. Returns timezone-aware datetimes in the
    configured astro_timezone. Falls back to 06:00–18:00 IST on any failure.
    """
    tz = pytz.timezone(settings.astro_timezone)
    try:
        # Use noon UTC of the same calendar day as the search anchor.
        start_local = date_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(pytz.utc)
        jd_start = swe.julday(start_utc.year, start_utc.month, start_utc.day,
                              start_utc.hour + start_utc.minute / 60, swe.GREG_CAL)

        geopos = (settings.astro_longitude, settings.astro_latitude, 0.0)
        flags = swe.FLG_MOSEPH
        # CALC_RISE = 1, CALC_SET = 2
        _, tret_rise = swe.rise_trans(jd_start, swe.SUN, swe.CALC_RISE, geopos, 0.0, 0.0, flags)
        _, tret_set  = swe.rise_trans(jd_start, swe.SUN, swe.CALC_SET,  geopos, 0.0, 0.0, flags)
        jd_rise = tret_rise[0]
        jd_set = tret_set[0]

        def _jd_to_dt(jd: float) -> datetime:
            y, m, d, h = swe.revjul(jd, swe.GREG_CAL)
            hours = int(h)
            minutes = int((h - hours) * 60)
            seconds = int(((h - hours) * 60 - minutes) * 60)
            utc_dt = datetime(int(y), int(m), int(d), hours, minutes, max(0, min(59, seconds)),
                              tzinfo=pytz.utc)
            return utc_dt.astimezone(tz)

        return _jd_to_dt(jd_rise), _jd_to_dt(jd_set)
    except Exception:
        # Fallback to fixed 06:00 / 18:00 in local TZ
        fixed_sr = date_local.replace(hour=6, minute=0, second=0, microsecond=0)
        fixed_ss = date_local.replace(hour=18, minute=0, second=0, microsecond=0)
        return fixed_sr, fixed_ss


def current_hora(
    dt: datetime | None = None,
    sunrise_hour: int | None = None,
    sunset_hour: int | None = None,
) -> HoraInfo:
    tz = pytz.timezone(settings.astro_timezone)
    if dt is None:
        dt = datetime.now(tz)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)

    # Real sunrise/sunset for the configured lat/lon — fixes seasonal drift
    if sunrise_hour is not None and sunset_hour is not None:
        sunrise = dt.replace(hour=sunrise_hour, minute=0, second=0, microsecond=0)
        sunset = dt.replace(hour=sunset_hour, minute=0, second=0, microsecond=0)
    else:
        sunrise, sunset = _compute_sunrise_sunset(dt)

    if sunrise <= dt < sunset:
        # Daytime — horas 1..12 from sunrise
        is_day = True
        period_start = sunrise
        period_end = sunset
        offset = 0
    elif dt >= sunset:
        # Night, after sunset → horas 13..24
        is_day = False
        period_start = sunset
        period_end = sunrise + timedelta(days=1)
        offset = 12
    else:
        # Before sunrise → still in previous day's nighttime horas
        is_day = False
        period_start = sunset - timedelta(days=1)
        period_end = sunrise
        offset = 12
        dt_for_lord = dt - timedelta(days=1)  # use previous day's lord for sequence
    # End-of-period guard
    if dt >= period_end:
        dt = period_end - timedelta(seconds=1)

    period_length = (period_end - period_start).total_seconds()
    hora_length = period_length / 12.0
    elapsed = (dt - period_start).total_seconds()
    sub_idx = int(elapsed / hora_length)                # 0..11
    hora_index = offset + sub_idx + 1                   # 1..24

    # Vedic day = sunrise → next sunrise.
    #  • daytime:        use today's weekday
    #  • night-after-sunset (still same calendar day): use today's weekday
    #  • before sunrise (early morning):                use yesterday's weekday
    if is_day or dt >= sunset:
        lord_anchor = dt
    else:
        lord_anchor = dt - timedelta(days=1)
    first_lord = WEEKDAY_FIRST_HORA[lord_anchor.weekday()]
    start_pos = CHALDEAN_ORDER.index(first_lord)
    ruler = CHALDEAN_ORDER[(start_pos + (hora_index - 1)) % 7]

    nature = HORA_NATURE[ruler]
    next_change_secs = hora_length - (elapsed - sub_idx * hora_length)
    next_ruler = CHALDEAN_ORDER[(start_pos + hora_index) % 7]

    # Look-ahead — next 5 horas
    sequence = []
    for k in range(1, 6):
        idx = hora_index + k
        if idx > 24:
            break
        r = CHALDEAN_ORDER[(start_pos + (idx - 1)) % 7]
        sequence.append({
            "hora_index": idx,
            "ruler": r,
            "bias": HORA_NATURE[r]["bias"],
            "minutes_from_now": round(next_change_secs / 60 + (k - 1) * hora_length / 60, 1),
        })

    market_open = _nse_open(dt)

    return HoraInfo(
        asof=dt.isoformat(),
        timezone=settings.astro_timezone,
        weekday=dt.strftime("%A"),
        is_day=is_day,
        hora_index=hora_index,
        duration_minutes=round(hora_length / 60, 2),
        ruler=ruler,
        bias=nature["bias"],
        weight=nature["weight"],
        notes=nature["notes"],
        next_change_in_minutes=round(next_change_secs / 60, 1),
        next_ruler=next_ruler,
        sequence_remaining=sequence,
        market_open=market_open,
    )


def _nse_open(dt: datetime) -> bool:
    # NSE equity 09:15 → 15:30 IST, Mon–Fri
    if dt.weekday() >= 5:                # Sat/Sun
        return False
    h, m = dt.hour, dt.minute
    after_open = (h, m) >= (9, 15)
    before_close = (h, m) < (15, 30)
    return after_open and before_close


# ---------------------------------------------------------------------------
# Day timeline — EVERY hora during the NSE session, not just the "best" ones
# ---------------------------------------------------------------------------
#
# User complaint surfaced this: the forecast card only showed Mercury (09:30-
# 10:35) and Mars (14:00-15:05) windows but said nothing about what happened
# between 10:35 and 14:00. NIFTY dropped sharply in that gap — and looking at
# the planetary sequence, Saturn hora hit around 11:40 (bearish weight 0.9).
# Surfacing the FULL day's hora timeline lets users see WHY the market behaved
# the way it did at any given minute, not just during the "best" windows.

def day_timeline(date_local: datetime | None = None) -> list[dict]:
    """Return every planetary hora that overlaps the NSE session (09:15–15:30 IST)
    on the given date, with start_iso, end_iso, ruler, bias, weight, and notes.

    Each block in the returned list represents one hora window the user can
    glance at. The list is ordered by time (earliest first). Used by the
    `/api/hora/day-timeline` endpoint and the frontend HoraDayTimeline widget.
    """
    tz = pytz.timezone(settings.astro_timezone)
    if date_local is None:
        date_local = datetime.now(tz)
    if date_local.tzinfo is None:
        date_local = tz.localize(date_local)
    else:
        date_local = date_local.astimezone(tz)

    sunrise, sunset = _compute_sunrise_sunset(date_local)
    period_length_secs = (sunset - sunrise).total_seconds()
    hora_length_secs = period_length_secs / 12.0

    # First-hora lord for the day (Sun=Sunday, Moon=Monday, etc.)
    first_lord = WEEKDAY_FIRST_HORA[date_local.weekday()]
    start_pos = CHALDEAN_ORDER.index(first_lord)

    # NSE session window for this date — clip to actual session
    session_open = date_local.replace(hour=NSE_OPEN_HM[0], minute=NSE_OPEN_HM[1],
                                        second=0, microsecond=0)
    session_close = date_local.replace(hour=NSE_CLOSE_HM[0], minute=NSE_CLOSE_HM[1],
                                         second=0, microsecond=0)

    timeline: list[dict] = []
    now = datetime.now(tz)
    for sub_idx in range(12):                            # 12 daytime horas
        hora_start = sunrise + timedelta(seconds=sub_idx * hora_length_secs)
        hora_end   = hora_start + timedelta(seconds=hora_length_secs)
        # Only include horas that overlap the NSE session at all
        if hora_end <= session_open or hora_start >= session_close:
            continue
        # Clip to session boundaries so the UI doesn't render bars that fall
        # outside the trading window (a Mars hora at 06:00 doesn't help a trader).
        clipped_start = max(hora_start, session_open)
        clipped_end   = min(hora_end,   session_close)

        ruler = CHALDEAN_ORDER[(start_pos + sub_idx) % 7]
        nature = HORA_NATURE[ruler]
        is_current = clipped_start <= now < clipped_end
        is_past = now >= clipped_end

        timeline.append({
            "hora_index":       sub_idx + 1,
            "ruler":            ruler,
            "bias":             nature["bias"],
            "weight":           nature["weight"],
            "notes":            nature["notes"],
            "start_iso":        clipped_start.isoformat(),
            "end_iso":          clipped_end.isoformat(),
            "duration_minutes": round((clipped_end - clipped_start).total_seconds() / 60, 1),
            "is_current":       is_current,
            "is_past":          is_past,
            "is_future":        not is_current and not is_past,
        })

    return timeline


# ---------------------------------------------------------------------------
# Forward-search helpers — find the next benefic hora for a given direction
# ---------------------------------------------------------------------------

NSE_OPEN_HM  = (9, 15)
NSE_CLOSE_HM = (15, 30)


def _clamp_to_market_session(start: datetime) -> datetime:
    """If `start` is before market open, push it to 09:15. If after close,
    push to 09:15 next trading day. If on weekend, jump to Monday 09:15."""
    tz = pytz.timezone(settings.astro_timezone)
    cur = start.astimezone(tz)
    # Skip weekends
    while cur.weekday() >= 5:
        cur = (cur + timedelta(days=1)).replace(
            hour=NSE_OPEN_HM[0], minute=NSE_OPEN_HM[1], second=0, microsecond=0,
        )
    hm = (cur.hour, cur.minute)
    if hm < NSE_OPEN_HM:
        cur = cur.replace(hour=NSE_OPEN_HM[0], minute=NSE_OPEN_HM[1], second=0, microsecond=0)
    elif hm >= NSE_CLOSE_HM:
        # next day
        cur = (cur + timedelta(days=1)).replace(
            hour=NSE_OPEN_HM[0], minute=NSE_OPEN_HM[1], second=0, microsecond=0,
        )
        while cur.weekday() >= 5:
            cur = cur + timedelta(days=1)
    return cur


def _market_close_for(dt: datetime) -> datetime:
    return dt.replace(hour=NSE_CLOSE_HM[0], minute=NSE_CLOSE_HM[1], second=0, microsecond=0)


@dataclass
class HoraWindow:
    direction: str                        # BUY or SELL
    entry_time: str                       # ISO timestamp — midpoint of the benefic hora
    window_start: str                     # ISO — earliest acceptable entry
    window_end: str                       # ISO — latest acceptable entry
    ruler: str
    bias: str
    weight: float
    minutes_to_entry: float
    is_within_session: bool
    rationale: str

    def to_dict(self) -> dict:
        return self.__dict__


def next_window(direction: str, asof: datetime | None = None,
                lookahead_horas: int = 16) -> HoraWindow:
    """Find the next planetary hora that's directionally aligned with
    `direction` (BUY/SELL) AND falls within an NSE trading session.

    Returns the *midpoint* of the benefic hora as the suggested clock time,
    plus the surrounding window (start..end of that hora). The midpoint
    avoids the edges where the ruler is changing.

    BUY  → prefer Jupiter (1.0) > Venus (0.8) > Sun (0.6) > Mercury (0.5)
    SELL → prefer Saturn (0.9) > Mars (0.7)
    """
    tz = pytz.timezone(settings.astro_timezone)
    asof = asof.astimezone(tz) if asof else datetime.now(tz)
    direction = direction.upper()

    if direction == "BUY":
        preferred = ["Jupiter", "Venus", "Sun", "Mercury"]
        bias_word = "bullish"
    elif direction == "SELL":
        preferred = ["Saturn", "Mars"]
        bias_word = "bearish"
    else:
        # Neutral — use neutral horas
        preferred = ["Moon", "Mercury"]
        bias_word = "neutral"

    search_start = _clamp_to_market_session(asof)
    best: HoraWindow | None = None
    cursor = search_start

    for _ in range(lookahead_horas):
        info = current_hora(cursor)
        # Compute this hora's start/end
        hora_minutes = info.duration_minutes
        # Approximate: cursor's hora started `info.next_change_in_minutes` minutes
        # before its end. So:
        end = cursor + timedelta(minutes=info.next_change_in_minutes)
        start = end - timedelta(minutes=hora_minutes)
        mid = start + (end - start) / 2

        market_close = _market_close_for(cursor)
        # Reject if midpoint outside trading session
        within = (
            cursor.weekday() < 5
            and start.replace(hour=NSE_OPEN_HM[0], minute=NSE_OPEN_HM[1]) <= mid <= market_close
            and mid.weekday() < 5
        )

        if info.ruler in preferred and (info.bias == bias_word or direction == "NEUTRAL") and within:
            rank = preferred.index(info.ruler)
            # First match in preference order wins
            best = HoraWindow(
                direction=direction,
                entry_time=mid.isoformat(),
                window_start=max(start, search_start).isoformat(),
                window_end=min(end, market_close).isoformat(),
                ruler=info.ruler,
                bias=info.bias,
                weight=info.weight,
                minutes_to_entry=round((mid - asof).total_seconds() / 60, 1),
                is_within_session=True,
                rationale=(
                    f"{info.ruler} hora ({info.bias}, weight {info.weight}) "
                    f"matches {direction} direction — preferred rank {rank+1}/{len(preferred)}. "
                    f"{info.notes}"
                ),
            )
            break

        # Jump to next hora
        cursor = end + timedelta(seconds=1)
        cursor = _clamp_to_market_session(cursor)

    if best is None:
        # Nothing matched within lookahead — fall back to current hora info
        info = current_hora(asof)
        cursor_end = asof + timedelta(minutes=max(1, info.next_change_in_minutes))
        best = HoraWindow(
            direction=direction,
            entry_time=asof.isoformat(),
            window_start=asof.isoformat(),
            window_end=cursor_end.isoformat(),
            ruler=info.ruler,
            bias=info.bias,
            weight=info.weight,
            minutes_to_entry=0.0,
            is_within_session=info.market_open,
            rationale=(
                f"No benefic hora found within {lookahead_horas} look-ahead horas — "
                f"falling back to current {info.ruler} hora. "
                "Consider waiting for next session."
            ),
        )
    return best
