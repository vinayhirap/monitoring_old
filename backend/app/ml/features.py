"""Feature engineering for the ML pipeline.

Produces a numerical feature vector from a symbol's recent OHLCV bars *plus*
the outputs of every engine (technical, smc, options, astrology, gann,
numerology). Engine outputs become features — the ML layer learns which
engines actually contribute predictive signal.

Output: a flat dict[str, float] with ~60 features. Anything non-numeric is
dropped or one-hot encoded.
"""
from __future__ import annotations

import math
from datetime import datetime
import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Price-derived features
# ---------------------------------------------------------------------------

def _price_features(df: pd.DataFrame) -> dict:
    out: dict = {}
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low  = df["low"].astype(float)
    vol  = df["volume"].astype(float) if "volume" in df.columns else None

    # Returns at multiple horizons
    for n in (1, 5, 10, 20, 60):
        if len(close) > n:
            out[f"ret_{n}d_pct"] = float((close.iloc[-1] / close.iloc[-n - 1] - 1) * 100)
        else:
            out[f"ret_{n}d_pct"] = 0.0

    # Volatility
    for n in (5, 20, 60):
        if len(close) > n:
            returns = close.pct_change().dropna().iloc[-n:]
            out[f"vol_{n}d_pct"] = float(returns.std() * math.sqrt(252) * 100) if len(returns) else 0
        else:
            out[f"vol_{n}d_pct"] = 0.0

    # Drawdown from rolling peak
    for n in (20, 60):
        if len(close) > n:
            window = close.iloc[-n:]
            peak = window.max()
            out[f"dd_from_{n}d_high_pct"] = float((window.iloc[-1] - peak) / peak * 100) if peak > 0 else 0
        else:
            out[f"dd_from_{n}d_high_pct"] = 0.0

    # Position in N-day range
    for n in (20, 60):
        if len(close) > n:
            w = close.iloc[-n:]
            rng = w.max() - w.min()
            out[f"pos_in_{n}d_range_pct"] = float((w.iloc[-1] - w.min()) / rng * 100) if rng > 0 else 50
        else:
            out[f"pos_in_{n}d_range_pct"] = 50.0

    # Volume features
    if vol is not None and len(vol) > 20:
        out["vol_ratio_5_20"] = float(vol.iloc[-5:].mean() / max(vol.iloc[-20:].mean(), 1))
    else:
        out["vol_ratio_5_20"] = 1.0

    # Body / range ratio (last bar)
    if len(close) > 0:
        body = abs(close.iloc[-1] - df["open"].astype(float).iloc[-1])
        rng = high.iloc[-1] - low.iloc[-1]
        out["last_bar_body_ratio"] = float(body / rng) if rng > 0 else 0
    else:
        out["last_bar_body_ratio"] = 0

    return out


# ---------------------------------------------------------------------------
# Calendar / temporal features
# ---------------------------------------------------------------------------

def _calendar_features(dt: datetime | None = None) -> dict:
    dt = dt or datetime.utcnow()
    return {
        "cal_day_of_week":  float(dt.weekday()),
        "cal_day_of_month": float(dt.day),
        "cal_month":        float(dt.month),
        "cal_quarter":      float((dt.month - 1) // 3 + 1),
        "cal_week_of_year": float(dt.isocalendar()[1]),
    }


# ---------------------------------------------------------------------------
# Engine output features — pulls scores + biases from a decision.aggregate()
# dict. One-hot encodes the bias.
# ---------------------------------------------------------------------------

ENGINES = ("technical", "smc", "options", "astrology", "gann", "numerology")
BIASES = ("BULLISH", "BEARISH", "NEUTRAL", "SIDEWAYS")


def _engine_features(decision_output: dict | None) -> dict:
    out: dict = {}
    if not decision_output:
        for e in ENGINES:
            out[f"{e}_score"] = 50.0
            for b in BIASES:
                out[f"{e}_bias_{b}"] = 0.0
        return out

    engines = decision_output.get("engines", {})
    for e in ENGINES:
        d = engines.get(e, {})
        out[f"{e}_score"] = float(d.get("score", 50))
        bias = (d.get("bias") or "").upper()
        for b in BIASES:
            out[f"{e}_bias_{b}"] = 1.0 if bias == b else 0.0

    out["headline_confidence"] = float(decision_output.get("confidence", 50))
    out["risk_reward"] = float(decision_output.get("risk_reward", 0))
    return out


# ---------------------------------------------------------------------------
# Public — build the full feature dict
# ---------------------------------------------------------------------------

def build(df: pd.DataFrame, decision_output: dict | None = None,
           dt: datetime | None = None) -> dict:
    """Combine all feature groups into a single dict."""
    feats: dict = {}
    feats.update(_price_features(df))
    feats.update(_calendar_features(dt))
    feats.update(_engine_features(decision_output))
    # Replace inf/nan with 0 (defensive)
    return {k: (0.0 if (v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))))
                else float(v)) for k, v in feats.items()}


FEATURE_NAMES = sorted(build(pd.DataFrame({
    "open":  [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
              1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
              1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    "high":  [1] * 61, "low": [1] * 61, "close": [1] * 61, "volume": [1] * 61,
})).keys())
