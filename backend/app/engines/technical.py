"""Technical analysis engine.

Pure-numpy/pandas implementations of classic indicators plus a scoring layer.
No TA-Lib dependency (avoids Windows build pain).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable
import numpy as np
import pandas as pd


# ============================================================================
# Indicator primitives
# ============================================================================

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(period).std()
    return pd.DataFrame({"upper": mid + mult * std, "mid": mid, "lower": mid - mult * std})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_val = atr(high, low, close, period)
    plus_di = 100 * pd.Series(plus_dm, index=close.index).ewm(alpha=1 / period, adjust=False).mean() / tr_val
    minus_di = 100 * pd.Series(minus_dm, index=close.index).ewm(alpha=1 / period, adjust=False).mean() / tr_val
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical = (high + low + close) / 3
    cum_vp = (typical * volume).cumsum()
    cum_v = volume.cumsum().replace(0, np.nan)
    return cum_vp / cum_v


def fibonacci_levels(high: float, low: float) -> dict[str, float]:
    diff = high - low
    return {
        "0.0": low,
        "0.236": low + 0.236 * diff,
        "0.382": low + 0.382 * diff,
        "0.5": low + 0.5 * diff,
        "0.618": low + 0.618 * diff,
        "0.786": low + 0.786 * diff,
        "1.0": high,
        "1.272": high + 0.272 * diff,
        "1.618": high + 0.618 * diff,
    }


# ============================================================================
# Scoring
# ============================================================================

@dataclass
class TechnicalScore:
    score: float                # 0..100 (higher = stronger bullish)
    bias: str                   # BULLISH / BEARISH / NEUTRAL
    trend_strength: float       # 0..100 (ADX-based)
    momentum: float             # 0..100 (RSI/MACD)
    volatility: float           # 0..100 (ATR % of price)
    reasons: list[str] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 2),
            "bias": self.bias,
            "trend_strength": round(self.trend_strength, 2),
            "momentum": round(self.momentum, 2),
            "volatility": round(self.volatility, 2),
            "reasons": self.reasons,
            "indicators": self.indicators,
        }


def analyze(df: pd.DataFrame) -> TechnicalScore:
    """Run full technical analysis on OHLCV dataframe.

    df must contain columns: open, high, low, close, volume (lowercase).
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"missing required column: {col}")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    vol = df["volume"]

    # Indicators
    ema9 = ema(close, 9).iloc[-1]
    ema20 = ema(close, 20).iloc[-1]
    ema50 = ema(close, 50).iloc[-1]
    ema200 = ema(close, 200).iloc[-1] if len(close) >= 200 else ema50
    rsi14 = rsi(close).iloc[-1]
    m = macd(close).iloc[-1]
    bb = bollinger(close).iloc[-1]
    atr14 = atr(high, low, close).iloc[-1]
    adx14 = adx(high, low, close).iloc[-1]
    vw = vwap(high, low, close, vol).iloc[-1]

    last = float(close.iloc[-1])

    reasons: list[str] = []
    bull = 0.0
    bear = 0.0

    # EMA stack
    if ema9 > ema20 > ema50:
        bull += 20
        reasons.append("EMA stack 9>20>50 (bullish)")
    elif ema9 < ema20 < ema50:
        bear += 20
        reasons.append("EMA stack 9<20<50 (bearish)")
    if last > ema200:
        bull += 5
        reasons.append("Price above 200-EMA (long-term bullish)")
    else:
        bear += 5
        reasons.append("Price below 200-EMA (long-term bearish)")

    # RSI
    if rsi14 > 70:
        bear += 10
        reasons.append(f"RSI {rsi14:.1f} overbought")
    elif rsi14 > 55:
        bull += 12
        reasons.append(f"RSI {rsi14:.1f} bullish momentum")
    elif rsi14 < 30:
        bull += 8
        reasons.append(f"RSI {rsi14:.1f} oversold (mean-reversion)")
    elif rsi14 < 45:
        bear += 12
        reasons.append(f"RSI {rsi14:.1f} bearish momentum")

    # MACD
    if m["macd"] > m["signal"] and m["hist"] > 0:
        bull += 15
        reasons.append("MACD bullish cross")
    elif m["macd"] < m["signal"] and m["hist"] < 0:
        bear += 15
        reasons.append("MACD bearish cross")

    # Bollinger
    if last > bb["upper"]:
        bear += 5
        reasons.append("Price above upper Bollinger (stretched)")
    elif last < bb["lower"]:
        bull += 5
        reasons.append("Price below lower Bollinger (stretched)")

    # VWAP
    if last > vw:
        bull += 8
        reasons.append("Above VWAP (intraday bullish)")
    else:
        bear += 8
        reasons.append("Below VWAP (intraday bearish)")

    # Aggregate
    raw = 50 + (bull - bear) / 2
    raw = max(0.0, min(100.0, raw))
    if raw >= 60:
        bias = "BULLISH"
    elif raw <= 40:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    trend_strength = float(min(100.0, adx14 * 2.5))   # ADX 40 -> 100
    momentum = float(abs(rsi14 - 50) * 2)             # 0..100
    volatility = float(min(100.0, (atr14 / last) * 100 * 20))  # ~5% ATR -> 100

    return TechnicalScore(
        score=raw,
        bias=bias,
        trend_strength=trend_strength,
        momentum=momentum,
        volatility=volatility,
        reasons=reasons,
        indicators={
            "ema9": round(float(ema9), 2),
            "ema20": round(float(ema20), 2),
            "ema50": round(float(ema50), 2),
            "ema200": round(float(ema200), 2),
            "rsi14": round(float(rsi14), 2),
            "macd": round(float(m["macd"]), 4),
            "macd_signal": round(float(m["signal"]), 4),
            "bb_upper": round(float(bb["upper"]), 2),
            "bb_mid": round(float(bb["mid"]), 2),
            "bb_lower": round(float(bb["lower"]), 2),
            "atr14": round(float(atr14), 4),
            "adx14": round(float(adx14), 2),
            "vwap": round(float(vw), 2),
            "last": round(last, 2),
        },
    )


# ============================================================================
# Synthetic OHLC for paper-mode demos
# ============================================================================

def synthetic_ohlcv(symbol: str, periods: int = 250, seed: int | None = None) -> pd.DataFrame:
    """Generate plausible OHLCV data deterministically per symbol.

    Used in paper-trading mode when no live broker is connected.
    """
    if seed is None:
        seed = sum(ord(c) for c in symbol)
    rng = np.random.default_rng(seed)

    base = 100 + (seed % 4000)            # base price 100..4100
    drift = rng.normal(0.0005, 0.018, periods)
    close = base * np.cumprod(1 + drift)
    high = close * (1 + rng.uniform(0.001, 0.012, periods))
    low = close * (1 - rng.uniform(0.001, 0.012, periods))
    open_ = close * (1 + rng.normal(0, 0.004, periods))
    volume = rng.integers(50_000, 5_000_000, periods)

    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=periods, freq="B")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
