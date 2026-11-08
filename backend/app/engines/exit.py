"""Exit / Sell-side signal engine.

Given a held position (long or short), decides whether to:
  - HOLD               — keep the position, stop unchanged
  - TRAIL_STOP         — move stoploss to lock in profit
  - PARTIAL_EXIT       — book a portion (e.g. 50%), trail rest
  - FULL_EXIT          — close the entire position immediately

Logic combines:
  • Profit/loss vs entry, in ATR multiples
  • Live technical bias (engine.technical)
  • SMC reversal signals (CHoCH, BoS opposite direction)
  • Astrology volatility window
  • Time decay (days held without movement)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Literal
import pandas as pd

from app.engines import technical, smc, astrology


Action = Literal["HOLD", "TRAIL_STOP", "PARTIAL_EXIT", "FULL_EXIT"]


@dataclass
class ExitDecision:
    symbol: str
    side: str                       # LONG / SHORT
    entry_price: float
    current_price: float
    qty: int
    days_held: int

    pnl_abs: float
    pnl_pct: float
    pnl_in_atr: float

    action: Action
    suggested_qty_to_exit: int
    new_stop: float | None
    new_target: float | None
    urgency: str                    # LOW / MEDIUM / HIGH / CRITICAL
    confidence: float               # 0..100 — confidence that exit (or hold) is correct
    reasons: list[str] = field(default_factory=list)
    sub_signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------
# Core decision
# ----------------------------------------------------------------------------

def evaluate(
    symbol: str,
    df: pd.DataFrame,
    entry_price: float,
    qty: int,
    entry_date: date | datetime,
    side: str = "LONG",
    current_stop: float | None = None,
    trail_atr_mult: float = 1.5,
    profit_target_atr_mult: float = 4.0,
    max_days: int = 30,
) -> ExitDecision:
    """Evaluate exit logic for a held position."""
    side = side.upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError("side must be LONG or SHORT")
    if isinstance(entry_date, datetime):
        entry_date = entry_date.date()

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    current_price = float(df["close"].iloc[-1])
    days_held = max(0, (date.today() - entry_date).days)

    # P&L
    if side == "LONG":
        pnl_abs = (current_price - entry_price) * qty
        pnl_pct = (current_price / entry_price - 1) * 100
    else:
        pnl_abs = (entry_price - current_price) * qty
        pnl_pct = (entry_price / current_price - 1) * 100

    # Sub-engines
    tech = technical.analyze(df)
    smc_res = smc.analyze(df)
    astro = astrology.market_sentiment(datetime.now())
    atr_val = tech.indicators["atr14"]
    pnl_in_atr = (current_price - entry_price) / atr_val if side == "LONG" else (entry_price - current_price) / atr_val

    reasons: list[str] = []
    score_exit = 0.0          # higher = more reason to exit
    score_hold = 0.0          # higher = more reason to hold
    urgency = "LOW"

    # 1) Hard stop check
    if current_stop is not None:
        if side == "LONG" and current_price <= current_stop:
            return _final(symbol, side, entry_price, current_price, qty, days_held,
                          pnl_abs, pnl_pct, pnl_in_atr,
                          "FULL_EXIT", qty, None, None, "CRITICAL", 100.0,
                          reasons=[f"Stoploss {current_stop:.2f} hit — full exit"],
                          sub={"tech": tech.bias, "smc": smc_res.market_structure})
        if side == "SHORT" and current_price >= current_stop:
            return _final(symbol, side, entry_price, current_price, qty, days_held,
                          pnl_abs, pnl_pct, pnl_in_atr,
                          "FULL_EXIT", qty, None, None, "CRITICAL", 100.0,
                          reasons=[f"Stoploss {current_stop:.2f} hit — full exit"],
                          sub={"tech": tech.bias, "smc": smc_res.market_structure})

    # 2) Technical bias flip against position
    bias_long_ok = tech.bias == "BULLISH"
    bias_short_ok = tech.bias == "BEARISH"
    if side == "LONG" and tech.bias == "BEARISH":
        score_exit += 30
        urgency = "HIGH"
        reasons.append(f"Technical bias flipped BEARISH (score {tech.score:.0f}/100)")
    elif side == "SHORT" and tech.bias == "BULLISH":
        score_exit += 30
        urgency = "HIGH"
        reasons.append(f"Technical bias flipped BULLISH (score {tech.score:.0f}/100)")
    elif (side == "LONG" and bias_long_ok) or (side == "SHORT" and bias_short_ok):
        score_hold += 20
        reasons.append(f"Technical bias still {tech.bias} — supports holding")

    # 3) SMC reversal: CHoCH against position
    if smc_res.last_choch:
        choch = smc_res.last_choch["type"]
        if side == "LONG" and "BEARISH" in choch:
            score_exit += 25
            urgency = "HIGH"
            reasons.append(f"SMC bearish CHoCH at {smc_res.last_choch['level']:.2f} — trend reversal")
        elif side == "SHORT" and "BULLISH" in choch:
            score_exit += 25
            urgency = "HIGH"
            reasons.append(f"SMC bullish CHoCH at {smc_res.last_choch['level']:.2f} — trend reversal")

    # 4) Profit-take in ATR multiples
    action: Action = "HOLD"
    suggested_qty_to_exit = 0
    new_stop = current_stop
    new_target = None

    if pnl_in_atr >= profit_target_atr_mult:
        action = "PARTIAL_EXIT"
        suggested_qty_to_exit = max(1, qty // 2)
        score_hold = 0
        urgency = max_urgency(urgency, "MEDIUM")
        reasons.append(f"Hit {pnl_in_atr:.1f}× ATR profit — book 50%, trail rest")
        # Aggressive trailing stop after partial book
        if side == "LONG":
            new_stop = round(current_price - trail_atr_mult * atr_val, 2)
            new_target = round(current_price + 2 * atr_val, 2)
        else:
            new_stop = round(current_price + trail_atr_mult * atr_val, 2)
            new_target = round(current_price - 2 * atr_val, 2)
    elif pnl_in_atr >= 2.0:
        # Profit decent — propose trailing stop
        if side == "LONG":
            proposed = round(current_price - trail_atr_mult * atr_val, 2)
            if current_stop is None or proposed > current_stop:
                action = "TRAIL_STOP"
                new_stop = proposed
                reasons.append(f"Trail SL up to {new_stop:.2f} (2× ATR profit secured)")
        else:
            proposed = round(current_price + trail_atr_mult * atr_val, 2)
            if current_stop is None or proposed < current_stop:
                action = "TRAIL_STOP"
                new_stop = proposed
                reasons.append(f"Trail SL down to {new_stop:.2f} (2× ATR profit secured)")

    # 5) Time decay — position stale + flat
    if days_held >= max_days and abs(pnl_pct) < 1.0:
        action = "FULL_EXIT"
        suggested_qty_to_exit = qty
        urgency = max_urgency(urgency, "MEDIUM")
        reasons.append(f"Held {days_held}d with <1% movement — capital better deployed elsewhere")

    # 6) Astro volatility heads-up (non-blocking, info-only)
    if astro.volatility_pct >= 60:
        reasons.append(f"⚠ Elevated astro volatility ({astro.volatility_pct:.0f}%) — tighten stops")
        urgency = max_urgency(urgency, "MEDIUM")

    # 7) Final decision when exit pressure dominates
    if score_exit >= 50 and action == "HOLD":
        action = "FULL_EXIT"
        suggested_qty_to_exit = qty
        urgency = "HIGH"
        reasons.append("Multiple exit signals confluence — full exit")
    elif score_exit >= 25 and action == "HOLD":
        action = "PARTIAL_EXIT"
        suggested_qty_to_exit = max(1, qty // 2)
        urgency = max_urgency(urgency, "MEDIUM")
        reasons.append("Moderate exit signals — book half")

    # Confidence: based on margin between exit and hold scores
    margin = abs(score_exit - score_hold)
    confidence = min(100.0, 50 + margin)

    return _final(
        symbol, side, entry_price, current_price, qty, days_held,
        pnl_abs, pnl_pct, pnl_in_atr,
        action, suggested_qty_to_exit, new_stop, new_target, urgency, confidence,
        reasons=reasons,
        sub={
            "technical": {"bias": tech.bias, "score": tech.score},
            "smc": {"structure": smc_res.market_structure, "choch": smc_res.last_choch},
            "astro": {"bias": astro.bias, "volatility_pct": astro.volatility_pct},
            "atr": atr_val,
        },
    )


def _final(symbol, side, entry, current, qty, days, pnl, pnl_pct, pnl_atr,
           action, exit_qty, new_stop, new_target, urgency, confidence,
           reasons, sub) -> ExitDecision:
    return ExitDecision(
        symbol=symbol, side=side,
        entry_price=round(entry, 2), current_price=round(current, 2), qty=qty,
        days_held=days,
        pnl_abs=round(pnl, 2), pnl_pct=round(pnl_pct, 2), pnl_in_atr=round(pnl_atr, 2),
        action=action, suggested_qty_to_exit=exit_qty,
        new_stop=new_stop, new_target=new_target,
        urgency=urgency, confidence=round(confidence, 2),
        reasons=reasons, sub_signals=sub,
    )


_URGENCY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

def max_urgency(a: str, b: str) -> str:
    return a if _URGENCY_ORDER[a] >= _URGENCY_ORDER[b] else b
