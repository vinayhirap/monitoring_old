"""Smart Money Concepts (SMC) + ICT detection engine.

Detects:
  - Market structure pivots (HH/HL/LH/LL)
  - Break of Structure (BoS) and Change of Character (CHoCH)
  - Order Blocks (last opposing candle before strong displacement)
  - Fair Value Gaps (3-candle imbalance)
  - Liquidity Zones (equal highs/lows = sweep targets)
  - Premium/Discount zones (50% of last leg)
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class SMCAnalysis:
    market_structure: str          # BULLISH / BEARISH / RANGING
    last_bos: dict | None
    last_choch: dict | None
    order_blocks: list[dict]
    fair_value_gaps: list[dict]
    liquidity_zones: list[dict]
    premium_discount: dict
    score: float                   # 0..100 (bullish bias)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------
# Pivots
# ----------------------------------------------------------------------------

def find_pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[pd.Series, pd.Series]:
    """Return (pivot_high_mask, pivot_low_mask) booleans."""
    high, low = df["high"], df["low"]
    ph = pd.Series(False, index=df.index)
    pl = pd.Series(False, index=df.index)
    for i in range(left, len(df) - right):
        win_h = high.iloc[i - left:i + right + 1]
        win_l = low.iloc[i - left:i + right + 1]
        if high.iloc[i] == win_h.max() and (win_h == high.iloc[i]).sum() == 1:
            ph.iloc[i] = True
        if low.iloc[i] == win_l.min() and (win_l == low.iloc[i]).sum() == 1:
            pl.iloc[i] = True
    return ph, pl


# ----------------------------------------------------------------------------
# Fair Value Gaps (3-candle imbalance)
# ----------------------------------------------------------------------------

def detect_fvg(df: pd.DataFrame, max_results: int = 10) -> list[dict]:
    """A bullish FVG: candle3.low > candle1.high. Bearish: candle3.high < candle1.low."""
    out = []
    for i in range(2, len(df)):
        c1, c3 = df.iloc[i - 2], df.iloc[i]
        if c3["low"] > c1["high"]:
            out.append({
                "type": "BULLISH_FVG",
                "top": float(c3["low"]),
                "bottom": float(c1["high"]),
                "index": str(df.index[i]),
            })
        elif c3["high"] < c1["low"]:
            out.append({
                "type": "BEARISH_FVG",
                "top": float(c1["low"]),
                "bottom": float(c3["high"]),
                "index": str(df.index[i]),
            })
    return out[-max_results:]


# ----------------------------------------------------------------------------
# Order Blocks (last bearish candle before bullish displacement; vice versa)
# ----------------------------------------------------------------------------

def detect_order_blocks(df: pd.DataFrame, displacement_atr: float = 1.5, max_results: int = 6) -> list[dict]:
    from app.engines.technical import atr
    a = atr(df["high"], df["low"], df["close"], 14)
    out = []
    for i in range(15, len(df) - 1):
        body = df["close"].iloc[i] - df["open"].iloc[i]
        if abs(body) < displacement_atr * a.iloc[i]:
            continue
        # find last opposing candle
        for j in range(i - 1, max(i - 10, 0), -1):
            opp = df["close"].iloc[j] - df["open"].iloc[j]
            if body > 0 and opp < 0:                    # bullish OB candidate
                out.append({
                    "type": "BULLISH_OB",
                    "top": float(df["high"].iloc[j]),
                    "bottom": float(df["low"].iloc[j]),
                    "index": str(df.index[j]),
                })
                break
            if body < 0 and opp > 0:                    # bearish OB candidate
                out.append({
                    "type": "BEARISH_OB",
                    "top": float(df["high"].iloc[j]),
                    "bottom": float(df["low"].iloc[j]),
                    "index": str(df.index[j]),
                })
                break
    return out[-max_results:]


# ----------------------------------------------------------------------------
# Liquidity zones (equal highs / equal lows)
# ----------------------------------------------------------------------------

def detect_liquidity(df: pd.DataFrame, tolerance_pct: float = 0.001, max_results: int = 6) -> list[dict]:
    out = []
    last = df["close"].iloc[-1]
    tol = last * tolerance_pct
    highs = df["high"].tail(80).round(0)
    lows = df["low"].tail(80).round(0)
    for level, count in highs.value_counts().items():
        if count >= 2 and abs(level - last) > tol:
            out.append({"type": "BSL", "price": float(level), "touches": int(count)})  # buy-side liq
    for level, count in lows.value_counts().items():
        if count >= 2 and abs(level - last) > tol:
            out.append({"type": "SSL", "price": float(level), "touches": int(count)})  # sell-side liq
    return sorted(out, key=lambda x: -x["touches"])[:max_results]


# ----------------------------------------------------------------------------
# Market structure / BoS / CHoCH
# ----------------------------------------------------------------------------

def detect_structure(df: pd.DataFrame) -> tuple[str, dict | None, dict | None]:
    ph_mask, pl_mask = find_pivots(df, 3, 3)
    pivots = []
    for ts, is_h, is_l in zip(df.index, ph_mask, pl_mask):
        if is_h:
            pivots.append({"ts": ts, "type": "H", "price": float(df.loc[ts, "high"])})
        if is_l:
            pivots.append({"ts": ts, "type": "L", "price": float(df.loc[ts, "low"])})
    pivots = sorted(pivots, key=lambda x: x["ts"])
    if len(pivots) < 4:
        return "RANGING", None, None

    last_h = [p for p in pivots if p["type"] == "H"][-2:]
    last_l = [p for p in pivots if p["type"] == "L"][-2:]

    structure = "RANGING"
    if len(last_h) == 2 and len(last_l) == 2:
        if last_h[1]["price"] > last_h[0]["price"] and last_l[1]["price"] > last_l[0]["price"]:
            structure = "BULLISH"
        elif last_h[1]["price"] < last_h[0]["price"] and last_l[1]["price"] < last_l[0]["price"]:
            structure = "BEARISH"

    last = df["close"].iloc[-1]
    bos = None
    choch = None
    if last_h and last > last_h[-1]["price"]:
        bos = {"type": "BULLISH_BOS", "level": last_h[-1]["price"]}
    elif last_l and last < last_l[-1]["price"]:
        bos = {"type": "BEARISH_BOS", "level": last_l[-1]["price"]}

    # CHoCH = first BoS in opposite direction of prior structure
    if structure == "BULLISH" and bos and bos["type"] == "BEARISH_BOS":
        choch = {"type": "BEARISH_CHOCH", "level": bos["level"]}
    elif structure == "BEARISH" and bos and bos["type"] == "BULLISH_BOS":
        choch = {"type": "BULLISH_CHOCH", "level": bos["level"]}

    return structure, bos, choch


# ----------------------------------------------------------------------------
# Premium / discount of last leg
# ----------------------------------------------------------------------------

def premium_discount(df: pd.DataFrame, lookback: int = 50) -> dict:
    seg = df.tail(lookback)
    hi, lo = float(seg["high"].max()), float(seg["low"].min())
    last = float(df["close"].iloc[-1])
    mid = (hi + lo) / 2
    zone = "PREMIUM" if last > mid else "DISCOUNT"
    return {"zone": zone, "high": hi, "low": lo, "mid": mid, "last": last}


# ----------------------------------------------------------------------------
# Aggregate
# ----------------------------------------------------------------------------

def analyze(df: pd.DataFrame) -> SMCAnalysis:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    structure, bos, choch = detect_structure(df)
    obs = detect_order_blocks(df)
    fvgs = detect_fvg(df)
    liq = detect_liquidity(df)
    pd_zone = premium_discount(df)

    reasons: list[str] = []
    score = 50.0
    if structure == "BULLISH":
        score += 15
        reasons.append("Market structure bullish (HH/HL)")
    elif structure == "BEARISH":
        score -= 15
        reasons.append("Market structure bearish (LH/LL)")

    if bos:
        if bos["type"] == "BULLISH_BOS":
            score += 10
            reasons.append(f"Bullish BoS at {bos['level']:.2f}")
        else:
            score -= 10
            reasons.append(f"Bearish BoS at {bos['level']:.2f}")
    if choch:
        if choch["type"] == "BULLISH_CHOCH":
            score += 8
            reasons.append("Bullish CHoCH (trend reversal up)")
        else:
            score -= 8
            reasons.append("Bearish CHoCH (trend reversal down)")

    if pd_zone["zone"] == "DISCOUNT":
        score += 5
        reasons.append("Price in discount zone (better long entry)")
    else:
        score -= 5
        reasons.append("Price in premium zone (better short entry)")

    score = max(0.0, min(100.0, score))

    return SMCAnalysis(
        market_structure=structure,
        last_bos=bos,
        last_choch=choch,
        order_blocks=obs,
        fair_value_gaps=fvgs,
        liquidity_zones=liq,
        premium_discount=pd_zone,
        score=score,
        reasons=reasons,
    )
