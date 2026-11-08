"""Pivot Points engine — Standard, Camarilla, Fibonacci, Woodie.

Pivot levels are the institutional intraday/swing reference grid. The previous
period's H/L/C produces a central pivot plus 3 support and 3 resistance levels
that act as magnets and reaction zones for the next session.
"""
from __future__ import annotations

from dataclasses import dataclass
import pandas as pd


@dataclass
class PivotSet:
    method: str           # standard / camarilla / fibonacci / woodie
    period: str           # daily / weekly / monthly
    pivot: float
    r1: float; r2: float; r3: float
    s1: float; s2: float; s3: float
    note: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


def standard(prev_h: float, prev_l: float, prev_c: float) -> dict:
    p = (prev_h + prev_l + prev_c) / 3
    r1 = 2 * p - prev_l;  s1 = 2 * p - prev_h
    r2 = p + (prev_h - prev_l); s2 = p - (prev_h - prev_l)
    r3 = prev_h + 2 * (p - prev_l); s3 = prev_l - 2 * (prev_h - p)
    return {"pivot": round(p, 2),
            "r1": round(r1, 2), "r2": round(r2, 2), "r3": round(r3, 2),
            "s1": round(s1, 2), "s2": round(s2, 2), "s3": round(s3, 2)}


def camarilla(prev_h: float, prev_l: float, prev_c: float) -> dict:
    rng = prev_h - prev_l
    r3 = prev_c + rng * 1.1 / 4
    r2 = prev_c + rng * 1.1 / 6
    r1 = prev_c + rng * 1.1 / 12
    s1 = prev_c - rng * 1.1 / 12
    s2 = prev_c - rng * 1.1 / 6
    s3 = prev_c - rng * 1.1 / 4
    return {"pivot": round(prev_c, 2),
            "r1": round(r1, 2), "r2": round(r2, 2), "r3": round(r3, 2),
            "s1": round(s1, 2), "s2": round(s2, 2), "s3": round(s3, 2)}


def fibonacci(prev_h: float, prev_l: float, prev_c: float) -> dict:
    p = (prev_h + prev_l + prev_c) / 3
    rng = prev_h - prev_l
    return {"pivot": round(p, 2),
            "r1": round(p + 0.382 * rng, 2), "r2": round(p + 0.618 * rng, 2),
            "r3": round(p + 1.000 * rng, 2),
            "s1": round(p - 0.382 * rng, 2), "s2": round(p - 0.618 * rng, 2),
            "s3": round(p - 1.000 * rng, 2)}


def _prev_period(df: pd.DataFrame, period: str) -> tuple[float, float, float] | None:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if period == "daily":
        if len(df) < 2:
            return None
        prev = df.iloc[-2]
        return float(prev["high"]), float(prev["low"]), float(prev["close"])
    rule = {"weekly": "W", "monthly": "ME"}[period]
    g = df.resample(rule).agg({"high": "max", "low": "min", "close": "last"}).dropna()
    if len(g) < 2:
        return None
    prev = g.iloc[-2]
    return float(prev["high"]), float(prev["low"]), float(prev["close"])


def analyze(df: pd.DataFrame, period: str = "daily") -> dict:
    """Compute all 3 pivot methods for the given period."""
    p = _prev_period(df, period)
    if p is None:
        return {"period": period, "error": f"insufficient data for {period} pivots"}
    h, l, c = p
    last = float(df["close"].iloc[-1]) if "close" in df.columns else float(df["Close"].iloc[-1])

    std = standard(h, l, c)
    cam = camarilla(h, l, c)
    fib = fibonacci(h, l, c)

    # Identify nearest level + signal
    levels = []
    for src, name in ((std, "standard"), (cam, "camarilla"), (fib, "fibonacci")):
        for k in ("r3", "r2", "r1", "pivot", "s1", "s2", "s3"):
            levels.append({"method": name, "level": k, "price": src[k]})
    nearest = min(levels, key=lambda x: abs(x["price"] - last))
    dist_pct = (nearest["price"] - last) / last * 100

    bias = "NEUTRAL"
    if last > std["pivot"]:
        bias = "BULLISH"
    elif last < std["pivot"]:
        bias = "BEARISH"

    return {
        "period": period,
        "prev_high": h, "prev_low": l, "prev_close": c,
        "last_price": last,
        "bias": bias,
        "standard": std, "camarilla": cam, "fibonacci": fib,
        "nearest_level": nearest,
        "distance_to_nearest_pct": round(dist_pct, 3),
        "note": (
            "Camarilla H3/L3 act as the most-watched breakout/breakdown lines. "
            "Standard R1/S1 are the most-traded magnets intraday."
        ),
    }
