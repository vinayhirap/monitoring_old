"""Ichimoku Kinko Hyo ("one-look equilibrium chart") — full 5-line system.

Tenkan-sen (9):     conversion line
Kijun-sen (26):     base line
Senkou Span A:      (Tenkan + Kijun) / 2  plotted 26 periods ahead → cloud edge 1
Senkou Span B (52): (52H + 52L) / 2       plotted 26 periods ahead → cloud edge 2
Chikou Span:        close plotted 26 periods BACK → momentum confirmation

Bias logic (institutional standard):
  • Price above cloud + green cloud + Tenkan>Kijun + Chikou above price  → STRONG BULL
  • Price below cloud + red cloud + Tenkan<Kijun + Chikou below price    → STRONG BEAR
  • Inside cloud OR mixed signals                                         → NEUTRAL
"""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass
class IchimokuRead:
    tenkan: float
    kijun: float
    senkou_a: float
    senkou_b: float
    chikou: float
    cloud_top: float
    cloud_bottom: float
    cloud_color: str           # green / red
    price: float
    bias: str                  # STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
    score: float               # 0..100 (>50 bullish)
    reasons: list[str]
    note: str

    def to_dict(self) -> dict:
        return self.__dict__


def _midpoint(high: pd.Series, low: pd.Series, period: int) -> pd.Series:
    return (high.rolling(period).max() + low.rolling(period).min()) / 2


def analyze(df: pd.DataFrame) -> IchimokuRead:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    high, low, close = df["high"], df["low"], df["close"]

    tenkan = _midpoint(high, low, 9)
    kijun = _midpoint(high, low, 26)
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = _midpoint(high, low, 52).shift(26)
    chikou = close.shift(-26)

    last_idx = -1
    t = float(tenkan.iloc[last_idx]); k = float(kijun.iloc[last_idx])
    a = float(span_a.iloc[last_idx]) if not pd.isna(span_a.iloc[last_idx]) else t
    b = float(span_b.iloc[last_idx]) if not pd.isna(span_b.iloc[last_idx]) else t
    cloud_top = max(a, b); cloud_bot = min(a, b)
    color = "green" if a >= b else "red"
    price = float(close.iloc[last_idx])

    # Chikou compared to price 26 bars ago
    if len(close) > 26:
        chikou_val = price
        price_26_ago = float(close.iloc[last_idx - 26])
        chikou_above = chikou_val > price_26_ago
    else:
        chikou_val = price
        chikou_above = True

    reasons = []
    score = 50.0
    if price > cloud_top:
        score += 18; reasons.append("Price above the cloud (bullish trend)")
    elif price < cloud_bot:
        score -= 18; reasons.append("Price below the cloud (bearish trend)")
    else:
        reasons.append("Price inside the cloud (no-trade zone)")

    if color == "green":
        score += 5; reasons.append("Future cloud is green (continuation bullish)")
    else:
        score -= 5; reasons.append("Future cloud is red (continuation bearish)")

    if t > k:
        score += 8; reasons.append("Tenkan > Kijun (short-term bullish cross)")
    elif t < k:
        score -= 8; reasons.append("Tenkan < Kijun (short-term bearish cross)")

    if chikou_above:
        score += 6; reasons.append("Chikou above price-26-ago (momentum confirms)")
    else:
        score -= 6; reasons.append("Chikou below price-26-ago (momentum negates)")

    score = max(0.0, min(100.0, score))
    if score >= 75:
        bias = "STRONG_BULL"
    elif score >= 60:
        bias = "BULL"
    elif score <= 25:
        bias = "STRONG_BEAR"
    elif score <= 40:
        bias = "BEAR"
    else:
        bias = "NEUTRAL"

    return IchimokuRead(
        tenkan=round(t, 2), kijun=round(k, 2),
        senkou_a=round(a, 2), senkou_b=round(b, 2),
        chikou=round(chikou_val, 2),
        cloud_top=round(cloud_top, 2), cloud_bottom=round(cloud_bot, 2),
        cloud_color=color, price=round(price, 2),
        bias=bias, score=round(score, 2), reasons=reasons,
        note=("Trade only outside the cloud and in the direction of cloud color "
              "with Chikou confirmation — the canonical 'TKx' setup."),
    )
