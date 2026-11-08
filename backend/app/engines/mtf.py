"""Multi-timeframe agreement.

Runs the technical engine on Daily / Weekly / Monthly resampled candles for the
same symbol and reports whether their biases agree. Strong setups generally
require alignment across at least 2 of 3 timeframes — single-timeframe signals
are far more prone to whipsaw.
"""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

from app.engines import technical


@dataclass
class TFRead:
    timeframe: str         # 1d / 1w / 1mo
    bias: str
    score: float
    rsi: float
    ema_alignment: str     # bullish stack / bearish stack / mixed
    note: str

    def to_dict(self) -> dict:
        return self.__dict__


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()


def _one(df: pd.DataFrame, label: str) -> TFRead:
    if len(df) < 30:
        return TFRead(timeframe=label, bias="NEUTRAL", score=50,
                      rsi=50, ema_alignment="insufficient data",
                      note=f"need >=30 bars at {label}")
    t = technical.analyze(df)
    e9, e20, e50 = t.indicators["ema9"], t.indicators["ema20"], t.indicators["ema50"]
    if e9 > e20 > e50:
        align = "bullish stack"
    elif e9 < e20 < e50:
        align = "bearish stack"
    else:
        align = "mixed"
    note = "; ".join(t.reasons[:3])
    return TFRead(timeframe=label, bias=t.bias, score=round(t.score, 2),
                  rsi=t.indicators["rsi14"], ema_alignment=align, note=note)


def analyze(df_daily: pd.DataFrame) -> dict:
    """`df_daily` must be a daily OHLCV dataframe with a DatetimeIndex."""
    df = df_daily.copy()
    df.columns = [c.lower() for c in df.columns]
    daily = _one(df, "1d")
    weekly = _one(_resample(df, "W"), "1w")
    monthly = _one(_resample(df, "ME"), "1mo")

    biases = [daily.bias, weekly.bias, monthly.bias]
    bull_count = biases.count("BULLISH")
    bear_count = biases.count("BEARISH")
    aligned = max(bull_count, bear_count)
    direction = "BULLISH" if bull_count > bear_count else "BEARISH" if bear_count > bull_count else "MIXED"

    grade = "ALL_3" if aligned == 3 else "2_OF_3" if aligned == 2 else "DIVERGENT"
    confidence = 50 + (aligned - 1) * 15 if direction != "MIXED" else 50

    return {
        "direction": direction,
        "agreement_grade": grade,
        "agreement_count": aligned,
        "confidence": round(confidence, 2),
        "timeframes": {
            "daily":   daily.to_dict(),
            "weekly":  weekly.to_dict(),
            "monthly": monthly.to_dict(),
        },
        "summary": (
            f"{aligned}/3 timeframes agree on {direction}. "
            + ("All three aligned — institutional-grade setup."
                if aligned == 3 else
                "Daily + one higher timeframe aligned — actionable."
                if aligned == 2 else
                "Timeframes diverge — wait for resolution.")
        ),
    }
