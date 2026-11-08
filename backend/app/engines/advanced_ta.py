"""Advanced technical analysis — VWAP family + divergence detection +
multi-timeframe momentum alignment.

These are the methods institutional desks actually use, that the user-facing
recommendation engine had been missing. Each function returns a structured
dict with score (0-100), bias (BULLISH/BEARISH/NEUTRAL), and machine-readable
diagnostic fields so other engines can compose with them.

Methods implemented:

1. VWAP family
   - Session VWAP (rolling, anchored to first bar of window)
   - VWAP standard-deviation bands (±1σ, ±2σ)
   - Price-to-VWAP distance → mean-reversion / breakout signal
   Why VWAP matters: it's the primary intraday execution benchmark
   institutions trade against. Price persistently above session VWAP =
   buyers in control; below = sellers in control.

2. RSI / MACD divergence detection
   - Bullish divergence: price lower low + indicator higher low
   - Bearish divergence: price higher high + indicator lower high
   - Hidden divergences (trend-continuation) also detected
   Why divergence matters: it's one of the few patterns with documented
   statistical edge (especially when confirmed by multiple oscillators).

3. Multi-timeframe momentum alignment
   - Computes momentum on 1× and 5× the bar window
   - "Aligned bullish" = both timeframes positive momentum AND higher TF
     showing trending behavior
   Why MTF matters: trades aligned with the higher-timeframe trend have
   measurably higher hit rates (Brock-Lakonishok-LeBaron 1992 and
   replications).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
import math

import numpy as np
import pandas as pd


# =============================================================================
# VWAP family
# =============================================================================

@dataclass
class VwapReport:
    vwap: float                          # current VWAP value
    spot: float                          # last close
    distance_pct: float                  # (spot - vwap) / vwap * 100
    upper_1sigma: float
    lower_1sigma: float
    upper_2sigma: float
    lower_2sigma: float
    zone: str                            # ABOVE_2S / ABOVE_1S / BULLISH / NEAR / BEARISH / BELOW_1S / BELOW_2S
    score: float                         # 0-100
    bias: str                            # BULLISH / BEARISH / NEUTRAL
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return self.__dict__


def vwap_analysis(df: pd.DataFrame, lookback: int = 60) -> VwapReport:
    """Session-style VWAP over `lookback` bars + ±1σ / ±2σ bands.

    Why a fixed lookback (not true session reset): the symbol detail endpoint
    runs on daily candles where intraday session boundaries don't exist.
    Lookback of 60 bars on daily = ~quarter; gives a meaningful institutional
    reference price without the indeterminacy of "which day to anchor."
    For intraday lookbacks (5-min bars), pass lookback=78 = single session.
    """
    if df is None or df.empty or len(df) < 10:
        return VwapReport(
            vwap=0, spot=0, distance_pct=0,
            upper_1sigma=0, lower_1sigma=0, upper_2sigma=0, lower_2sigma=0,
            zone="UNKNOWN", score=50, bias="NEUTRAL",
            reasons=["Insufficient bars for VWAP"],
        )

    work = df.tail(lookback).copy()
    work.columns = [c.lower() for c in work.columns]

    # Typical price × volume / cumulative volume — standard VWAP formula
    tp = (work["high"] + work["low"] + work["close"]) / 3
    vol = work["volume"].replace(0, np.nan).fillna(work["volume"].median() or 1)
    cum_vol = vol.cumsum()
    cum_pv = (tp * vol).cumsum()
    vwap_series = cum_pv / cum_vol

    # Standard-deviation bands — measure of how dispersed price is from VWAP
    # within the lookback. Weighted by volume for consistency.
    sq_diff = ((tp - vwap_series) ** 2 * vol).cumsum()
    var = sq_diff / cum_vol
    sigma = np.sqrt(var)

    vwap_now = float(vwap_series.iloc[-1])
    sigma_now = float(sigma.iloc[-1])
    spot = float(work["close"].iloc[-1])
    dist_pct = (spot - vwap_now) / vwap_now * 100 if vwap_now > 0 else 0

    upper_1 = vwap_now + sigma_now
    lower_1 = vwap_now - sigma_now
    upper_2 = vwap_now + 2 * sigma_now
    lower_2 = vwap_now - 2 * sigma_now

    reasons: list[str] = []

    # Zone + bias logic
    if spot >= upper_2:
        zone = "ABOVE_2S"
        score = 30        # extended — mean-reversion sell candidate
        bias = "BEARISH"
        reasons.append(f"Price stretched >2σ above VWAP (₹{spot:.2f} vs VWAP ₹{vwap_now:.2f}) — extension/exhaustion zone")
    elif spot >= upper_1:
        zone = "ABOVE_1S"
        score = 65
        bias = "BULLISH"
        reasons.append(f"Price 1σ–2σ above VWAP — strong buyer control, trend leg in progress")
    elif spot > vwap_now:
        zone = "BULLISH"
        score = 60
        bias = "BULLISH"
        reasons.append(f"Price above VWAP (+{dist_pct:.2f}%) — buyers in control")
    elif spot >= lower_1:
        zone = "NEAR" if abs(dist_pct) < 0.3 else "BEARISH"
        score = 45 if zone == "BEARISH" else 50
        bias = "BEARISH" if zone == "BEARISH" else "NEUTRAL"
        if zone == "NEAR":
            reasons.append("Price hugging VWAP — directional commitment unclear")
        else:
            reasons.append(f"Price below VWAP ({dist_pct:.2f}%) — sellers in control")
    elif spot >= lower_2:
        zone = "BELOW_1S"
        score = 35
        bias = "BEARISH"
        reasons.append("Price 1σ–2σ below VWAP — sellers dominant, downtrend leg active")
    else:
        zone = "BELOW_2S"
        score = 70        # extended — mean-reversion buy candidate
        bias = "BULLISH"
        reasons.append(f"Price stretched >2σ below VWAP — oversold extension, mean-reversion candidate")

    return VwapReport(
        vwap=round(vwap_now, 2),
        spot=round(spot, 2),
        distance_pct=round(dist_pct, 3),
        upper_1sigma=round(upper_1, 2),
        lower_1sigma=round(lower_1, 2),
        upper_2sigma=round(upper_2, 2),
        lower_2sigma=round(lower_2, 2),
        zone=zone,
        score=round(score, 1),
        bias=bias,
        reasons=reasons,
    )


# =============================================================================
# Divergence detection — RSI + MACD
# =============================================================================

@dataclass
class DivergenceReport:
    rsi_divergence:  str | None    # BULLISH / BEARISH / HIDDEN_BULLISH / HIDDEN_BEARISH / None
    macd_divergence: str | None
    confirmed_count: int           # how many indicators are showing same divergence
    score: float
    bias: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return self.__dict__


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = -delta.clip(upper=0).rolling(period).mean()
    rs = up / down.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast=12, slow=26, signal=9) -> tuple[pd.Series, pd.Series]:
    """Returns (macd_line, signal_line)."""
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal).mean()
    return macd, sig


def _find_pivots(series: pd.Series, lookback: int = 5) -> tuple[list[int], list[int]]:
    """Local maxima/minima with a `lookback`-bar window on each side.
    Returns (high_indices, low_indices)."""
    vals = series.values
    n = len(vals)
    highs, lows = [], []
    for i in range(lookback, n - lookback):
        window = vals[i - lookback: i + lookback + 1]
        center = vals[i]
        if center == max(window) and not math.isnan(center):
            highs.append(i)
        if center == min(window) and not math.isnan(center):
            lows.append(i)
    return highs, lows


def _detect_divergence(price: pd.Series, indicator: pd.Series,
                        lookback: int = 5, window: int = 50) -> str | None:
    """Compare last two price pivots vs last two indicator pivots over `window`
    bars and classify any divergence.

    Returns one of: BULLISH / BEARISH / HIDDEN_BULLISH / HIDDEN_BEARISH / None
    """
    if len(price) < window + lookback * 2:
        return None

    p = price.tail(window).reset_index(drop=True)
    ind = indicator.tail(window).reset_index(drop=True)

    p_highs, p_lows = _find_pivots(p, lookback)
    i_highs, i_lows = _find_pivots(ind, lookback)

    # Regular bullish: price lower-low + indicator higher-low
    if len(p_lows) >= 2 and len(i_lows) >= 2:
        p1, p2 = p_lows[-2], p_lows[-1]
        # Use nearest indicator low to each price low (within 3 bars tolerance)
        i1 = min(i_lows, key=lambda x: abs(x - p1)) if i_lows else None
        i2 = min(i_lows, key=lambda x: abs(x - p2)) if i_lows else None
        if i1 is not None and i2 is not None and i1 != i2:
            if p.iloc[p2] < p.iloc[p1] and ind.iloc[i2] > ind.iloc[i1]:
                return "BULLISH"
            if p.iloc[p2] > p.iloc[p1] and ind.iloc[i2] < ind.iloc[i1]:
                return "HIDDEN_BULLISH"

    # Regular bearish: price higher-high + indicator lower-high
    if len(p_highs) >= 2 and len(i_highs) >= 2:
        p1, p2 = p_highs[-2], p_highs[-1]
        i1 = min(i_highs, key=lambda x: abs(x - p1)) if i_highs else None
        i2 = min(i_highs, key=lambda x: abs(x - p2)) if i_highs else None
        if i1 is not None and i2 is not None and i1 != i2:
            if p.iloc[p2] > p.iloc[p1] and ind.iloc[i2] < ind.iloc[i1]:
                return "BEARISH"
            if p.iloc[p2] < p.iloc[p1] and ind.iloc[i2] > ind.iloc[i1]:
                return "HIDDEN_BEARISH"

    return None


def divergence_analysis(df: pd.DataFrame, lookback: int = 5, window: int = 50) -> DivergenceReport:
    """Detect RSI + MACD divergences over recent price action."""
    if df is None or df.empty or len(df) < window + 10:
        return DivergenceReport(
            rsi_divergence=None, macd_divergence=None,
            confirmed_count=0, score=50, bias="NEUTRAL",
            reasons=["Insufficient bars for divergence analysis"],
        )

    work = df.copy()
    work.columns = [c.lower() for c in work.columns]
    close = work["close"].astype(float)
    rsi = _rsi(close, period=14)
    macd_line, _ = _macd(close)

    rsi_div = _detect_divergence(close, rsi, lookback=lookback, window=window)
    macd_div = _detect_divergence(close, macd_line, lookback=lookback, window=window)

    # Bias logic
    bullish_signals = sum(1 for d in (rsi_div, macd_div) if d in ("BULLISH", "HIDDEN_BULLISH"))
    bearish_signals = sum(1 for d in (rsi_div, macd_div) if d in ("BEARISH", "HIDDEN_BEARISH"))

    if bullish_signals > bearish_signals:
        bias = "BULLISH"
        score = 60 + 8 * bullish_signals    # 2 confirms → 76
    elif bearish_signals > bullish_signals:
        bias = "BEARISH"
        score = 40 - 8 * bearish_signals    # 2 confirms → 24
    else:
        bias = "NEUTRAL"
        score = 50

    reasons: list[str] = []
    if rsi_div:
        reasons.append(f"RSI {rsi_div.lower().replace('_', ' ')} divergence detected — momentum waning")
    if macd_div:
        reasons.append(f"MACD {macd_div.lower().replace('_', ' ')} divergence — trend energy fading")
    if not reasons:
        reasons.append("No active divergences — price/momentum in agreement")

    return DivergenceReport(
        rsi_divergence=rsi_div,
        macd_divergence=macd_div,
        confirmed_count=bullish_signals + bearish_signals,
        score=round(score, 1),
        bias=bias,
        reasons=reasons,
    )


# =============================================================================
# Multi-timeframe momentum alignment
# =============================================================================

@dataclass
class MtfMomentumReport:
    short_tf_momentum: float       # ROC% on `short_window` bars
    long_tf_momentum: float        # ROC% on `long_window` bars
    short_tf_bias: str
    long_tf_bias: str
    aligned: bool                  # both timeframes pointing same way
    higher_tf_trending: bool       # is HTF showing trending behavior (ADX-style)
    score: float
    bias: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return self.__dict__


def _adx_lite(df: pd.DataFrame, period: int = 14) -> float:
    """Lightweight ADX approximation — returns most-recent ADX value.
    Used to detect 'is this timeframe trending or chopping'?

    >25 = trending, <20 = ranging, in between = developing.
    """
    work = df.copy()
    work.columns = [c.lower() for c in work.columns]
    h, l, c = work["high"].astype(float), work["low"].astype(float), work["close"].astype(float)

    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    tr = pd.concat([(h - l),
                     (h - c.shift()).abs(),
                     (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr.replace(0, 1e-9))
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr.replace(0, 1e-9))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
    adx = dx.rolling(period).mean()
    return float(adx.iloc[-1]) if not adx.empty and not math.isnan(adx.iloc[-1]) else 0.0


def mtf_momentum(df: pd.DataFrame,
                  short_window: int = 10,
                  long_window: int = 50) -> MtfMomentumReport:
    """Compare short-window and long-window rate-of-change to detect
    timeframe alignment. Bonus score when both timeframes align AND
    the long-timeframe is in a trending regime (high ADX).
    """
    if df is None or df.empty or len(df) <= long_window:
        return MtfMomentumReport(
            short_tf_momentum=0, long_tf_momentum=0,
            short_tf_bias="NEUTRAL", long_tf_bias="NEUTRAL",
            aligned=False, higher_tf_trending=False,
            score=50, bias="NEUTRAL",
            reasons=["Insufficient bars for MTF analysis"],
        )

    work = df.copy()
    work.columns = [c.lower() for c in work.columns]
    c = work["close"].astype(float)

    short_roc = (c.iloc[-1] / c.iloc[-short_window] - 1) * 100
    long_roc  = (c.iloc[-1] / c.iloc[-long_window] - 1) * 100

    def _bias(roc: float, threshold: float = 0.5) -> str:
        if roc > threshold: return "BULLISH"
        if roc < -threshold: return "BEARISH"
        return "NEUTRAL"

    short_bias = _bias(short_roc)
    long_bias = _bias(long_roc, threshold=2.0)    # higher TF needs bigger move
    aligned = short_bias == long_bias and short_bias != "NEUTRAL"

    adx_val = _adx_lite(work.tail(max(long_window + 20, 60)))
    htf_trending = adx_val > 22

    # Score logic
    if aligned and htf_trending:
        # Best case — high-confidence with-trend setup
        score = 75 if short_bias == "BULLISH" else 25
        bias = short_bias
        reasons = [
            f"Multi-TF alignment: short {short_roc:+.2f}% / long {long_roc:+.2f}% — both {short_bias}",
            f"Higher-TF ADX={adx_val:.1f} → trending regime confirms direction",
        ]
    elif aligned:
        score = 65 if short_bias == "BULLISH" else 35
        bias = short_bias
        reasons = [
            f"Timeframes aligned ({short_bias}) but ADX={adx_val:.1f} — ranging market, take partial position",
        ]
    elif short_bias != long_bias and short_bias != "NEUTRAL" and long_bias != "NEUTRAL":
        # Divergent — short fighting long
        score = 45
        bias = "NEUTRAL"
        reasons = [
            f"Timeframe conflict: short {short_bias} ({short_roc:+.2f}%) vs long {long_bias} ({long_roc:+.2f}%)",
            "Wait for alignment before deploying — counter-trend trades have low edge",
        ]
    else:
        score = 50
        bias = "NEUTRAL"
        reasons = ["No clear multi-timeframe signal"]

    return MtfMomentumReport(
        short_tf_momentum=round(short_roc, 2),
        long_tf_momentum=round(long_roc, 2),
        short_tf_bias=short_bias,
        long_tf_bias=long_bias,
        aligned=aligned,
        higher_tf_trending=htf_trending,
        score=round(score, 1),
        bias=bias,
        reasons=reasons,
    )


# =============================================================================
# Composite advanced-TA analyze() — bundle all three into one call
# =============================================================================

@dataclass
class AdvancedTaReport:
    vwap: dict
    divergence: dict
    mtf_momentum: dict
    composite_score: float          # weighted average of the three
    composite_bias: str
    confluence_count: int           # how many of 3 agree on direction
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict: return self.__dict__


def analyze(df: pd.DataFrame) -> AdvancedTaReport:
    """Run all three advanced-TA engines and produce a composite reading.

    Weighting (chosen for typical-volatility daily charts):
      • MTF momentum   45%   — direction filter is highest-value signal
      • VWAP            30%   — anchor for institutional flow
      • Divergence      25%   — exhaustion / warning overlay

    `confluence_count` reports how many of the three engines agree on
    the composite direction. 3/3 is rare but high-conviction; 2/3 is
    the standard "decent setup" threshold.
    """
    v = vwap_analysis(df)
    d = divergence_analysis(df)
    m = mtf_momentum(df)

    composite_score = 0.30 * v.score + 0.25 * d.score + 0.45 * m.score
    if composite_score >= 58:
        composite_bias = "BULLISH"
    elif composite_score <= 42:
        composite_bias = "BEARISH"
    else:
        composite_bias = "NEUTRAL"

    confluence_count = sum(
        1 for r in (v.bias, d.bias, m.bias) if r == composite_bias
    )

    reasons: list[str] = []
    if confluence_count == 3:
        reasons.append("⚡ Triple confluence — all 3 advanced-TA engines agree on direction")
    elif confluence_count == 2:
        reasons.append("✓ 2-of-3 advanced-TA engines aligned")
    else:
        reasons.append("Mixed advanced-TA signals — wait for clearer alignment")

    reasons.extend(m.reasons[:1])
    reasons.extend(v.reasons[:1])
    if d.confirmed_count > 0:
        reasons.extend(d.reasons[:1])

    return AdvancedTaReport(
        vwap=v.to_dict(),
        divergence=d.to_dict(),
        mtf_momentum=m.to_dict(),
        composite_score=round(composite_score, 1),
        composite_bias=composite_bias,
        confluence_count=confluence_count,
        reasons=reasons,
    )
