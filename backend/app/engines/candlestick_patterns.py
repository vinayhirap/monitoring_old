"""Candlestick pattern recognition — pure Python, no TA-Lib dependency.

Why pure Python (instead of TA-Lib)?
  • TA-Lib is a C library; installation often fails on Windows and minimal
    Linux containers. Adding it for 10 patterns is too much friction.
  • These rules are mechanical — a 50-line implementation per pattern is fine
    and easier to debug than the TA-Lib black box.

Patterns implemented (highest-edge candlestick signals per documented studies):

Single-bar:
  1. **Doji**           — open ≈ close, signals indecision at turning points
  2. **Hammer**         — small body, long lower wick; bullish reversal at lows
  3. **Shooting Star**  — small body, long upper wick; bearish reversal at highs
  4. **Marubozu**       — large body, minimal wicks; strong continuation

Two-bar:
  5. **Bullish Engulfing** — prior down, current up body engulfs prior body
  6. **Bearish Engulfing** — mirror of above
  7. **Piercing Line**     — down candle then up candle closing >50% into the prior
  8. **Dark Cloud Cover**  — up candle then down candle closing >50% into the prior

Three-bar:
  9. **Morning Star**   — down, small body (any color), up that closes deep into bar 1
 10. **Evening Star**   — up, small body, down that closes deep into bar 1

Each pattern returns:
  • detected (bool)
  • bias (BULLISH/BEARISH/NEUTRAL)
  • strength (1..5) — context-aware (1 if pattern is alone, 5 if at a swing low/high)

Output is a composite report — bias + strength + which patterns fired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class PatternHit:
    name: str
    bias: str                          # BULLISH / BEARISH / NEUTRAL
    strength: int                      # 1..5
    bar_index: int                     # which bar (negative = most recent)
    rationale: str                     # one-line explanation


@dataclass
class CandlestickReport:
    patterns: list[dict]               # list of PatternHit dicts
    headline_pattern: Optional[str]    # the highest-strength pattern detected
    composite_bias: str
    composite_score: float             # 0..100
    confluence_count: int              # how many patterns agree on direction
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------
# Pattern detection helpers
# ----------------------------------------------------------------------------

def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range_(h: float, l: float) -> float:
    return max(1e-9, h - l)


def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_wick(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def _is_bullish(o: float, c: float) -> bool:
    return c > o


def _is_bearish(o: float, c: float) -> bool:
    return c < o


def _near_swing_low(df: pd.DataFrame, lookback: int = 10) -> bool:
    """Is the most recent low within 1% of the lookback-window low?"""
    if len(df) < lookback:
        return False
    recent_low = float(df["low"].iloc[-1])
    window_low = float(df["low"].tail(lookback).min())
    return abs(recent_low - window_low) / max(window_low, 1e-9) < 0.01


def _near_swing_high(df: pd.DataFrame, lookback: int = 10) -> bool:
    if len(df) < lookback:
        return False
    recent_high = float(df["high"].iloc[-1])
    window_high = float(df["high"].tail(lookback).max())
    return abs(recent_high - window_high) / max(window_high, 1e-9) < 0.01


# ----------------------------------------------------------------------------
# Single-bar patterns
# ----------------------------------------------------------------------------

def _detect_doji(o: float, h: float, l: float, c: float) -> Optional[PatternHit]:
    """Body < 10% of range — indecision."""
    rng = _range_(h, l)
    body = _body(o, c)
    if body / rng < 0.10:
        return PatternHit(name="Doji", bias="NEUTRAL", strength=1, bar_index=-1,
                            rationale="Open ≈ close — indecision at this level")
    return None


def _detect_hammer(o: float, h: float, l: float, c: float,
                    at_swing_low: bool) -> Optional[PatternHit]:
    """Body in upper third, lower wick ≥ 2× body, upper wick small."""
    body = _body(o, c)
    upper = _upper_wick(o, h, c)
    lower = _lower_wick(o, l, c)
    if body == 0:
        return None
    if lower >= 2 * body and upper <= 0.5 * body:
        # At a swing low: strength 4; otherwise 2
        strength = 5 if at_swing_low and _is_bullish(o, c) else 4 if at_swing_low else 2
        return PatternHit(
            name="Hammer", bias="BULLISH", strength=strength, bar_index=-1,
            rationale=("Hammer at recent low — rejection of lower prices"
                         if at_swing_low else "Hammer pattern — body in upper third, long lower wick"),
        )
    return None


def _detect_shooting_star(o: float, h: float, l: float, c: float,
                           at_swing_high: bool) -> Optional[PatternHit]:
    """Mirror of hammer — body in lower third, long upper wick."""
    body = _body(o, c)
    upper = _upper_wick(o, h, c)
    lower = _lower_wick(o, l, c)
    if body == 0:
        return None
    if upper >= 2 * body and lower <= 0.5 * body:
        strength = 5 if at_swing_high and _is_bearish(o, c) else 4 if at_swing_high else 2
        return PatternHit(
            name="Shooting Star", bias="BEARISH", strength=strength, bar_index=-1,
            rationale=("Shooting star at recent high — rejection of higher prices"
                         if at_swing_high else "Shooting star — body in lower third, long upper wick"),
        )
    return None


def _detect_marubozu(o: float, h: float, l: float, c: float) -> Optional[PatternHit]:
    """Body covers >85% of range — strong directional bar."""
    rng = _range_(h, l)
    body = _body(o, c)
    if body / rng > 0.85:
        bias = "BULLISH" if _is_bullish(o, c) else "BEARISH"
        return PatternHit(
            name=f"{bias.title()} Marubozu", bias=bias, strength=3, bar_index=-1,
            rationale=f"{bias.title()} Marubozu — body covers {body / rng * 100:.0f}% of range, strong conviction",
        )
    return None


# ----------------------------------------------------------------------------
# Two-bar patterns
# ----------------------------------------------------------------------------

def _detect_engulfing(prev_o, prev_h, prev_l, prev_c,
                       o, h, l, c) -> Optional[PatternHit]:
    """Current body engulfs prior body (in opposite direction)."""
    prev_body_max = max(prev_o, prev_c)
    prev_body_min = min(prev_o, prev_c)
    cur_body_max = max(o, c)
    cur_body_min = min(o, c)
    if _is_bearish(prev_o, prev_c) and _is_bullish(o, c):
        if cur_body_min <= prev_body_min and cur_body_max >= prev_body_max:
            return PatternHit(name="Bullish Engulfing", bias="BULLISH",
                                strength=4, bar_index=-1,
                                rationale="Bullish engulfing — current up bar engulfs prior down bar")
    if _is_bullish(prev_o, prev_c) and _is_bearish(o, c):
        if cur_body_min <= prev_body_min and cur_body_max >= prev_body_max:
            return PatternHit(name="Bearish Engulfing", bias="BEARISH",
                                strength=4, bar_index=-1,
                                rationale="Bearish engulfing — current down bar engulfs prior up bar")
    return None


def _detect_piercing_or_dark_cloud(prev_o, prev_h, prev_l, prev_c,
                                      o, h, l, c) -> Optional[PatternHit]:
    """Piercing line (bull) / Dark cloud cover (bear) — close past 50% of prior body."""
    prev_mid = (prev_o + prev_c) / 2
    if _is_bearish(prev_o, prev_c) and _is_bullish(o, c) and o < prev_c and c > prev_mid:
        return PatternHit(name="Piercing Line", bias="BULLISH", strength=3, bar_index=-1,
                            rationale="Piercing line — gap-down open then strong recovery past prior midpoint")
    if _is_bullish(prev_o, prev_c) and _is_bearish(o, c) and o > prev_c and c < prev_mid:
        return PatternHit(name="Dark Cloud Cover", bias="BEARISH", strength=3, bar_index=-1,
                            rationale="Dark cloud cover — gap-up open then close past prior midpoint")
    return None


# ----------------------------------------------------------------------------
# Three-bar patterns
# ----------------------------------------------------------------------------

def _detect_star(b1, b2, b3, bullish: bool) -> Optional[PatternHit]:
    """Morning Star (bullish) / Evening Star (bearish).
    Bar 1: strong directional. Bar 2: small body (gap, indecision). Bar 3:
    strong opposite-direction, closes deep into bar 1."""
    o1, _, _, c1 = b1
    o2, _, _, c2 = b2
    o3, _, _, c3 = b3
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    body3 = abs(c3 - o3)
    mid1 = (o1 + c1) / 2
    if bullish:
        if not (_is_bearish(o1, c1) and body1 > body2 * 2 and
                  _is_bullish(o3, c3) and body3 > body2 * 2 and c3 > mid1):
            return None
        return PatternHit(name="Morning Star", bias="BULLISH", strength=4, bar_index=-1,
                            rationale="Morning Star — bear, doji, strong bull closing inside bar 1")
    else:
        if not (_is_bullish(o1, c1) and body1 > body2 * 2 and
                  _is_bearish(o3, c3) and body3 > body2 * 2 and c3 < mid1):
            return None
        return PatternHit(name="Evening Star", bias="BEARISH", strength=4, bar_index=-1,
                            rationale="Evening Star — bull, doji, strong bear closing inside bar 1")


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

def detect(df: pd.DataFrame) -> CandlestickReport:
    """Run all pattern detectors on the most recent bars of `df`.

    Returns a composite report — bias driven by which patterns fired and
    their strengths. NEUTRAL when nothing fired or signals are conflicted.
    """
    if df is None or df.empty or len(df) < 3:
        return CandlestickReport(
            patterns=[], headline_pattern=None,
            composite_bias="NEUTRAL", composite_score=50, confluence_count=0,
            reasons=["Not enough bars to detect candle patterns"],
        )

    work = df.copy()
    work.columns = [c.lower() for c in work.columns]

    o   = float(work["open"].iloc[-1])
    h   = float(work["high"].iloc[-1])
    l   = float(work["low"].iloc[-1])
    c   = float(work["close"].iloc[-1])
    po  = float(work["open"].iloc[-2])
    ph  = float(work["high"].iloc[-2])
    pl  = float(work["low"].iloc[-2])
    pc  = float(work["close"].iloc[-2])
    if len(work) >= 3:
        b1 = (float(work["open"].iloc[-3]),
               float(work["high"].iloc[-3]),
               float(work["low"].iloc[-3]),
               float(work["close"].iloc[-3]))
        b2 = (po, ph, pl, pc)
        b3 = (o, h, l, c)
    else:
        b1 = b2 = b3 = None

    at_low  = _near_swing_low(work)
    at_high = _near_swing_high(work)

    hits: list[PatternHit] = []

    # Single-bar
    for fn, args in [
        (_detect_doji, (o, h, l, c)),
        (_detect_hammer, (o, h, l, c, at_low)),
        (_detect_shooting_star, (o, h, l, c, at_high)),
        (_detect_marubozu, (o, h, l, c)),
    ]:
        result = fn(*args)
        if result:
            hits.append(result)

    # Two-bar
    for fn in (_detect_engulfing, _detect_piercing_or_dark_cloud):
        result = fn(po, ph, pl, pc, o, h, l, c)
        if result:
            hits.append(result)

    # Three-bar (morning / evening star)
    if b1 is not None:
        ms = _detect_star(b1, b2, b3, bullish=True)
        if ms: hits.append(ms)
        es = _detect_star(b1, b2, b3, bullish=False)
        if es: hits.append(es)

    if not hits:
        return CandlestickReport(
            patterns=[], headline_pattern=None,
            composite_bias="NEUTRAL", composite_score=50, confluence_count=0,
            reasons=["No notable candlestick patterns on the most recent bars"],
        )

    # Weighted composite — sum of bias × strength
    bull_weight = sum(p.strength for p in hits if p.bias == "BULLISH")
    bear_weight = sum(p.strength for p in hits if p.bias == "BEARISH")
    net = bull_weight - bear_weight

    # Map net to 0-100 score (50 neutral, ±20 strong)
    score = 50 + min(40, max(-40, net * 5))
    if score > 58:
        composite_bias = "BULLISH"
    elif score < 42:
        composite_bias = "BEARISH"
    else:
        composite_bias = "NEUTRAL"

    confluence = sum(1 for p in hits if p.bias == composite_bias)
    # The headline pattern is the strongest one matching the composite direction
    matching = [p for p in hits if p.bias == composite_bias]
    headline = max(matching, key=lambda p: p.strength) if matching else max(hits, key=lambda p: p.strength)

    reasons = [headline.rationale]
    other_strong = sorted([p for p in hits if p is not headline], key=lambda p: -p.strength)[:2]
    for p in other_strong:
        reasons.append(f"Also detected: {p.name} ({p.bias.lower()})")

    return CandlestickReport(
        patterns=[p.__dict__ for p in hits],
        headline_pattern=headline.name,
        composite_bias=composite_bias,
        composite_score=round(score, 1),
        confluence_count=confluence,
        reasons=reasons,
    )
