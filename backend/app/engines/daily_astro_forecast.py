"""14-day pure-astrology forecast.

For each calendar day in a forward window, computes:
  • Moon nakshatra + pada + the day's tithi/paksha
  • Day-lord (sun = Sunday, moon = Monday, etc.)
  • Tara distance from the symbol's natal nakshatra → favourable/tense
  • Hora-weighted intraday bias for that day
  • Composite bias score: BULLISH / BEARISH / NEUTRAL
  • Expected intraday range %: derived from symbol's ATR × astrology-volatility factor
  • Best entry window (HH:MM IST) and best exit window for that day

Returns a structured per-day forecast that the frontend renders as a clean
14-day table — no engine-name jargon, just "this day looks bullish/bearish,
range ±X%, enter between 10:30-12:30."

ALL ASTROLOGY — no price-action input. So users get a pure cyclical view
they can cross-reference against their own technical analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Literal
import math

import pytz

from app.config import settings
from app.engines import astrology, numerology
from app.engines.nakshatra_screener import (
    _symbol_nakshatra_idx, _classify_tara, _tara_bonus,
)


# Day-of-week → planetary lord
WEEKDAY_LORD = {
    0: "Moon", 1: "Mars", 2: "Mercury", 3: "Jupiter",
    4: "Venus", 5: "Saturn", 6: "Sun",
}

# Each day-lord's intrinsic market polarity (heuristic)
LORD_POLARITY = {
    "Sun":     +0.4,
    "Moon":    +0.1,        # volatile but slightly positive on average
    "Mercury": +0.3,
    "Venus":   +0.8,
    "Mars":    -0.4,
    "Jupiter": +1.0,        # the most bullish day-lord (Thursday)
    "Saturn":  -0.6,        # the most bearish (Saturday — but markets closed)
}

# Per-day-lord typical "best window" — pulled from classical muhurta-hora
# tradition. Times are in IST. These are the windows when the day-lord's
# hora typically falls during NSE hours (09:15-15:30).
DEFAULT_BEST_WINDOWS = {
    "Sun":     [("09:30", "10:35")],
    "Moon":    [("11:30", "12:35"), ("14:00", "15:05")],
    "Mars":    [("11:30", "12:35")],
    "Mercury": [("09:30", "10:35"), ("11:30", "12:35")],
    "Jupiter": [("11:30", "12:35"), ("14:00", "15:05")],
    "Venus":   [("09:30", "10:35"), ("14:00", "15:05")],
    "Saturn":  [],          # markets closed Saturdays anyway
}


@dataclass
class DailyAstroBar:
    date: str                       # ISO YYYY-MM-DD
    weekday: str
    is_market_open: bool            # False on Sat/Sun
    day_lord: str
    moon_nakshatra: str
    moon_nakshatra_ruler: str
    tithi: int                      # 1..30
    paksha: str                     # Shukla / Krishna
    moon_phase: str
    tara_distance: int              # vs symbol's natal nakshatra
    tara_class: str                 # JANMA / SAMPADA / SYMPATHETIC / TENSE / NEUTRAL
    astro_score: float              # 0..100
    bias: str                       # BULLISH / BEARISH / NEUTRAL
    expected_range_pct: float        # ±range from astrology volatility factor
    best_entry_windows: list[tuple[str, str]]   # [(HH:MM, HH:MM)]
    best_exit_windows: list[tuple[str, str]]
    events: list[str] = field(default_factory=list)     # eclipse, full moon, retrograde flag

    def to_dict(self) -> dict:
        """ADMIN/OWNER/ANALYST view — full astrology internals exposed."""
        return {**self.__dict__,
                "best_entry_windows": [{"from": w[0], "to": w[1]} for w in self.best_entry_windows],
                "best_exit_windows":  [{"from": w[0], "to": w[1]} for w in self.best_exit_windows]}

    def to_user_dict(self) -> dict:
        """USER view — astrology internals stripped, events sanitized.

        What's REMOVED for users:
          • day_lord, moon_nakshatra, moon_nakshatra_ruler
          • tithi, paksha, moon_phase
          • tara_distance, tara_class
          • Raw astro_score field name → renamed to `confidence`

        What's KEPT:
          • Date, weekday, is_market_open (calendar facts)
          • Bias (BULLISH/BEARISH/NEUTRAL)
          • Confidence (0-100 — renamed from astro_score so the UI doesn't say "astro")
          • Expected range %
          • Best entry/exit windows
          • Events — sanitized to neutral language; unsalvageable jargon dropped.
        """
        # Sanitize events here so the caller never has to filter Nones
        clean_events = [s for s in (sanitize_event(e) for e in self.events) if s]
        return {
            "date": self.date,
            "weekday": self.weekday,
            "is_market_open": self.is_market_open,
            "bias": self.bias,
            "confidence": self.astro_score,
            "expected_range_pct": self.expected_range_pct,
            "best_entry_windows": [{"from": w[0], "to": w[1]} for w in self.best_entry_windows],
            "best_exit_windows":  [{"from": w[0], "to": w[1]} for w in self.best_exit_windows],
            "events": clean_events,
        }


def sanitize_event(event: str) -> str | None:
    """Rewrite astrology-jargon event strings to neutral, user-facing language.

    Returns None if the event is too astrology-specific to be salvaged
    (caller filters None out).
    """
    e = event.lower()
    # Volatility-expansion events
    if "full moon" in e:
        return "Volatility expansion expected — consider wider stops"
    if "new moon" in e:
        return "Accumulation window — fresh setups forming"
    # Uncertainty events
    if "retrograde" in e:
        return "High-uncertainty window — choppy moves likely"
    if "eclipse" in e:
        return "Major event window — expect outsized moves"
    # Cycle / transition events
    if "moon enters" in e or "ingress" in e or "gann cycle" in e or "cycle reversal" in e:
        return "Cycle transition — heightened attention"
    if "janma tara" in e or "heightened volatility" in e:
        return "Symbol-specific volatility window"
    # Anything that mentions raw nakshatra / planet names — drop
    JARGON_TOKENS = (
        "nakshatra", "tara", "tithi", "paksha", "hora", "rahu", "ketu",
        "ashlesha", "magha", "purva", "uttara", "hasta", "chitra", "swati",
        "vishakha", "anuradha", "jyeshtha", "mula", "purvashadha",
        "uttarashadha", "shravana", "dhanishta", "shatabhisha", "revati",
    )
    if any(t in e for t in JARGON_TOKENS):
        return None    # drop
    return event       # already neutral


def forecast(symbol: str, days: int = 14,
              base_volatility_pct: float = 1.5,
              view: str = "admin") -> dict:
    """Generate a 14-day per-day astrology forecast for one symbol.

    `base_volatility_pct` is the symbol's typical daily-range % (~1-2% for
    large caps, 2-4% for mid/small). We use this as the multiplier baseline;
    astrology adjusts ± up to 50% from this.

    `view`:
      • 'admin' — full payload with nakshatra/day-lord/tara/tithi/paksha
      • 'user'  — astrology fields stripped, events sanitized to neutral
                  language, raw scores renamed to `confidence`
    """
    tz = pytz.timezone(settings.astro_timezone)
    today = datetime.now(tz).date()
    sym_nak_idx = _symbol_nakshatra_idx(symbol)
    sym_nak_name = astrology.NAKSHATRAS[sym_nak_idx][0]
    sym_nak_ruler = astrology.NAKSHATRAS[sym_nak_idx][1]

    bars: list[DailyAstroBar] = []
    for d in range(days):
        bar_date = today + timedelta(days=d)
        # Use 11 AM IST as the "representative" moment for the day's astrology
        bar_dt = tz.localize(datetime(bar_date.year, bar_date.month, bar_date.day, 11, 0))

        positions = astrology.planet_positions(bar_dt)
        moon = positions["Moon"]
        phase = astrology.moon_phase(bar_dt)
        sentiment = astrology.market_sentiment(bar_dt)

        # Tara distance
        moon_idx = moon.nakshatra["index"] - 1
        d_tara = (moon_idx - sym_nak_idx + 27) % 27
        tara_class = _classify_tara(d_tara)
        tara_bonus = _tara_bonus(tara_class)

        # Day-lord polarity
        weekday = bar_date.weekday()
        day_lord = WEEKDAY_LORD[weekday]
        lord_pol = LORD_POLARITY.get(day_lord, 0)

        # Compose astro score
        # baseline 50 + sentiment.score - 50 + tara_bonus + 5×lord_polarity
        score = 50.0 + (sentiment.score - 50) * 0.4 + tara_bonus + 5 * lord_pol

        # Saturn/Mercury retrograde drag
        if positions.get("Saturn") and positions["Saturn"].retrograde:
            score -= 2
        if positions.get("Mercury") and positions["Mercury"].retrograde:
            score -= 3

        score = max(0.0, min(100.0, score))
        bias = "BULLISH" if score >= 58 else "BEARISH" if score <= 42 else "NEUTRAL"

        # Expected intraday range — astrology volatility factor
        vol_mult = 1.0
        if phase["phase"] in ("New Moon", "Full Moon"):
            vol_mult *= 1.4
        if positions.get("Mars") and not positions["Mars"].retrograde:
            mars_sun_sep = abs(positions["Mars"].longitude - positions["Sun"].longitude) % 360
            if mars_sun_sep > 180: mars_sun_sep = 360 - mars_sun_sep
            if mars_sun_sep < 10 or abs(mars_sun_sep - 180) < 10:
                vol_mult *= 1.25
        if tara_class == "JANMA":
            vol_mult *= 1.2
        expected_range = base_volatility_pct * vol_mult

        # Best windows for the day-lord
        if bias == "BULLISH":
            entry_windows = DEFAULT_BEST_WINDOWS.get(day_lord, [])
            exit_windows = [("14:30", "15:20")]
        elif bias == "BEARISH":
            entry_windows = [("09:15", "09:45")]
            exit_windows = DEFAULT_BEST_WINDOWS.get(day_lord, [])
        else:
            entry_windows = [("10:30", "11:30")]
            exit_windows = [("14:00", "15:00")]

        # Events
        events = []
        if phase["phase"] == "New Moon":
            events.append("New Moon — accumulation phase begins")
        if phase["phase"] == "Full Moon":
            events.append("Full Moon — distribution / volatility peak")
        if positions.get("Mercury") and positions["Mercury"].retrograde:
            events.append("Mercury retrograde — comms/execution risk")
        if d_tara == 0:
            events.append(f"Moon in {sym_nak_name} (janma tara — heightened volatility for {symbol})")

        is_market_open = bar_date.weekday() < 5

        bars.append(DailyAstroBar(
            date=bar_date.isoformat(),
            weekday=bar_date.strftime("%A"),
            is_market_open=is_market_open,
            day_lord=day_lord,
            moon_nakshatra=moon.nakshatra["name"],
            moon_nakshatra_ruler=moon.nakshatra["ruler"],
            tithi=phase["tithi"],
            paksha=phase["paksha"],
            moon_phase=phase["phase"],
            tara_distance=d_tara,
            tara_class=tara_class,
            astro_score=round(score, 1),
            bias=bias if is_market_open else "MARKET_CLOSED",
            expected_range_pct=round(expected_range, 2),
            best_entry_windows=entry_windows if is_market_open else [],
            best_exit_windows=exit_windows if is_market_open else [],
            events=events,
        ))

    # Aggregate stats
    open_bars = [b for b in bars if b.is_market_open]
    best_buy_day  = max(open_bars, key=lambda b: b.astro_score, default=None)
    best_sell_day = min(open_bars, key=lambda b: b.astro_score, default=None)

    bullish_count = sum(1 for b in open_bars if b.bias == "BULLISH")
    bearish_count = sum(1 for b in open_bars if b.bias == "BEARISH")
    neutral_count = sum(1 for b in open_bars if b.bias == "NEUTRAL")

    return {
        "symbol": symbol.upper(),
        "asof": datetime.now(tz).isoformat(),
        "symbol_nakshatra": sym_nak_name,
        "symbol_nakshatra_ruler": sym_nak_ruler,
        "horizon_days": days,
        "trading_days": len(open_bars),
        "summary": {
            "bullish_days":  bullish_count,
            "bearish_days":  bearish_count,
            "neutral_days":  neutral_count,
            "best_buy_day":  best_buy_day.date if best_buy_day else None,
            "best_buy_score": best_buy_day.astro_score if best_buy_day else None,
            "best_sell_day": best_sell_day.date if best_sell_day else None,
            "best_sell_score": best_sell_day.astro_score if best_sell_day else None,
        },
        # View-aware days payload. `to_user_dict()` already strips astrology
        # internals AND sanitizes events to neutral phrasing in-place.
        "days": [b.to_user_dict() for b in bars] if view == "user"
                else [b.to_dict() for b in bars],
    }
