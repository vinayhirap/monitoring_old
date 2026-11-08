"""Strategy selector.

Given a finalized symbol's full analysis bundle (technical, SMC, options, ATR,
volatility climate), pick the *best playbook*:

  • EQUITY_BUY              — straightforward long delivery / swing
  • EQUITY_SHORT            — intraday short (cash) or futures short
  • FUT_LONG / FUT_SHORT    — directional futures with leverage
  • OPT_CE_BUY              — bullish, low IV → buy calls
  • OPT_PE_BUY              — bearish, low IV → buy puts
  • OPT_BULL_CALL_SPREAD    — bullish, mid IV
  • OPT_BEAR_PUT_SPREAD     — bearish, mid IV
  • OPT_IRON_CONDOR         — range-bound, high IV → sell premium
  • OPT_LONG_STRADDLE       — expecting big move, low IV
  • OPT_SHORT_STRANGLE      — range-bound, very high IV
  • WAIT                    — no edge

Outputs a structured StrategyPlan with entry/SL/targets, capital allocation,
and expected payoff sketch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


StrategyType = Literal[
    "EQUITY_BUY", "EQUITY_SHORT",
    "FUT_LONG", "FUT_SHORT",
    "OPT_CE_BUY", "OPT_PE_BUY",
    "OPT_BULL_CALL_SPREAD", "OPT_BEAR_PUT_SPREAD",
    "OPT_IRON_CONDOR", "OPT_LONG_STRADDLE", "OPT_SHORT_STRANGLE",
    "WAIT",
]

Horizon = Literal["INTRADAY", "SWING", "POSITIONAL"]


@dataclass
class StrategyPlan:
    symbol: str
    strategy: StrategyType
    horizon: Horizon
    rationale: str
    entry: float
    stoploss: float
    targets: list[float]
    risk_reward: float
    suggested_qty: int
    capital_allocation_pct: float
    capital_required_inr: float
    expected_max_profit_inr: float
    expected_max_loss_inr: float
    # ---- Entry geometry (added so recommendations aren't just "buy at LTP") ----
    # `entry` above is the *trigger price* the user should set their order at;
    # the fields below describe HOW that price was derived so the UI can show
    # "buy on pullback to ₹X (Gann support)" instead of just echoing spot back.
    entry_zone: dict = field(default_factory=dict)
    # entry_zone = {
    #   "low":  float — bottom of the acceptable entry band,
    #   "high": float — top of the acceptable entry band,
    #   "anchor": "GANN_SUPPORT" | "GANN_RESISTANCE" | "PULLBACK_ATR" | "BREAKOUT_ATR" | "MARKET",
    # }
    trigger_type: str = "MARKET"           # PULLBACK / BREAKOUT / MARKET
    trigger_note: str = ""                 # one-line human explanation
    candle_confirmation: dict = field(default_factory=dict)
    # candle_confirmation = {
    #   "consecutive_in_direction": int  — last N candles aligned with direction,
    #   "required": int                  — how many we need for a confirmed signal,
    #   "confirmed": bool                — consecutive >= required,
    #   "note": str,
    # }
    instrument_legs: list[dict] = field(default_factory=list)   # for spreads/condors
    notes: list[str] = field(default_factory=list)
    # ---- Timing fields (filled in when Hora info is supplied) ----
    timing: dict = field(default_factory=dict)
    # timing = {
    #   "entry_time":   ISO timestamp — single best-clock entry,
    #   "window_start": ISO — earliest acceptable entry,
    #   "window_end":   ISO — latest acceptable entry,
    #   "ruler":        planet ruling the entry hora,
    #   "rationale":    why this clock time,
    #   "exit_by":      ISO — recommended hard-exit time,
    # }
    why_this_strategy: list[str] = field(default_factory=list)
    suitability: dict = field(default_factory=dict)   # "EQUITY_BUY": "suitable when …", ...

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------
# Smart entry — Gann support/resistance + ATR pullback + candle confirmation
# ----------------------------------------------------------------------------

def _consecutive_in_direction(recent_candles: list[dict] | None, direction: str) -> int:
    """Count CONSECUTIVE candles ending at the most recent bar whose body
    aligns with `direction`. Bullish bar = close > open; bearish = close < open.
    A doji (close == open) breaks the streak."""
    if not recent_candles:
        return 0
    want_bull = direction == "BULLISH"
    count = 0
    # `recent_candles` should be ordered oldest → newest; walk from newest backward.
    for bar in reversed(recent_candles):
        o = float(bar.get("open", 0))
        c = float(bar.get("close", 0))
        if o == c:                                # doji breaks streak
            break
        bullish_bar = c > o
        if (want_bull and bullish_bar) or (not want_bull and not bullish_bar):
            count += 1
        else:
            break
    return count


def _smart_entry(*,
                  spot: float,
                  direction: str,
                  atr: float,
                  gann_support: float | None,
                  gann_resistance: float | None,
                  recent_candles: list[dict] | None) -> dict:
    """Compute a *trade-able* entry price + zone + trigger type.

    NEVER returns `entry = spot` blindly. Instead picks ONE of:
      • PULLBACK   — wait for price to retrace toward Gann support/resistance
      • BREAKOUT   — wait for price to clear Gann resistance/support with momentum
      • MARKET     — only when spot is already in a high-quality entry zone

    For a BULLISH setup:
      - If spot is well above support (>1× ATR away), use PULLBACK toward support
      - If price just broke through resistance with 2+ green candles, use BREAKOUT
      - Otherwise use MARKET (with a wider zone reflecting uncertainty)
    Mirror logic for BEARISH.

    Returns: {entry, entry_zone, trigger_type, trigger_note}
    """
    if atr <= 0:
        atr = max(spot * 0.01, 1.0)              # floor to 1% of spot

    cons_bull = _consecutive_in_direction(recent_candles, "BULLISH")
    cons_bear = _consecutive_in_direction(recent_candles, "BEARISH")
    last_close = float(recent_candles[-1]["close"]) if recent_candles else spot

    if direction == "BULLISH":
        sup = float(gann_support) if gann_support and gann_support > 0 else None
        res = float(gann_resistance) if gann_resistance and gann_resistance > 0 else None

        # BREAKOUT path — recent close just cleared resistance with momentum
        if res and last_close > res and cons_bull >= 2:
            entry = round(res * 1.002, 2)        # small buffer above the level
            return {
                "entry": entry,
                "entry_zone": {"low": round(res, 2),
                                "high": round(res + 0.5 * atr, 2),
                                "anchor": "GANN_RESISTANCE"},
                "trigger_type": "BREAKOUT",
                "trigger_note": (f"Buy on confirmed breakout above Gann resistance ₹{res:.2f} "
                                  f"({cons_bull} consecutive bullish candles)."),
            }

        # PULLBACK path — spot is meaningfully above support, wait for retest
        if sup and spot > sup * 1.005 and (spot - sup) > 0.5 * atr:
            # Entry at the higher of: just above support, or spot - 0.5*ATR
            pullback_target = max(sup * 1.003, spot - 0.5 * atr)
            entry = round(pullback_target, 2)
            return {
                "entry": entry,
                "entry_zone": {"low": round(sup, 2),
                                "high": round(min(spot, sup + 0.7 * atr), 2),
                                "anchor": "GANN_SUPPORT"},
                "trigger_type": "PULLBACK",
                "trigger_note": (f"Buy on pullback to Gann support zone ₹{sup:.2f}–"
                                  f"₹{spot - 0.5*atr:.2f}."),
            }

        # MARKET — spot is near support OR no clean Gann level
        entry = round(spot, 2)
        return {
            "entry": entry,
            "entry_zone": {"low": round(spot - 0.3 * atr, 2),
                            "high": round(spot + 0.2 * atr, 2),
                            "anchor": "MARKET"},
            "trigger_type": "MARKET",
            "trigger_note": ("Buy near current price — no clear pullback zone, candle "
                              f"momentum {cons_bull}/2 (weak confirmation)."
                              if cons_bull < 2 else
                              f"Buy near current price — {cons_bull} consecutive bullish candles confirm momentum."),
        }

    if direction == "BEARISH":
        sup = float(gann_support) if gann_support and gann_support > 0 else None
        res = float(gann_resistance) if gann_resistance and gann_resistance > 0 else None

        # BREAKDOWN — close below support with bearish momentum
        if sup and last_close < sup and cons_bear >= 2:
            entry = round(sup * 0.998, 2)
            return {
                "entry": entry,
                "entry_zone": {"low": round(sup - 0.5 * atr, 2),
                                "high": round(sup, 2),
                                "anchor": "GANN_SUPPORT"},
                "trigger_type": "BREAKOUT",
                "trigger_note": (f"Sell on confirmed breakdown below Gann support ₹{sup:.2f} "
                                  f"({cons_bear} consecutive bearish candles)."),
            }

        # PULLBACK rally — spot below resistance, wait for retest
        if res and spot < res * 0.995 and (res - spot) > 0.5 * atr:
            pullback_target = min(res * 0.997, spot + 0.5 * atr)
            entry = round(pullback_target, 2)
            return {
                "entry": entry,
                "entry_zone": {"low": round(max(spot, res - 0.7 * atr), 2),
                                "high": round(res, 2),
                                "anchor": "GANN_RESISTANCE"},
                "trigger_type": "PULLBACK",
                "trigger_note": (f"Sell on rally to Gann resistance zone ₹"
                                  f"{spot + 0.5*atr:.2f}–₹{res:.2f}."),
            }

        entry = round(spot, 2)
        return {
            "entry": entry,
            "entry_zone": {"low": round(spot - 0.2 * atr, 2),
                            "high": round(spot + 0.3 * atr, 2),
                            "anchor": "MARKET"},
            "trigger_type": "MARKET",
            "trigger_note": ("Sell near current price — no clear rally zone, candle "
                              f"momentum {cons_bear}/2 (weak confirmation)."
                              if cons_bear < 2 else
                              f"Sell near current price — {cons_bear} consecutive bearish candles confirm momentum."),
        }

    # SIDEWAYS — no directional entry; the strategy is range/premium-based
    return {
        "entry": round(spot, 2),
        "entry_zone": {"low": round(spot - 0.2 * atr, 2),
                        "high": round(spot + 0.2 * atr, 2),
                        "anchor": "MARKET"},
        "trigger_type": "MARKET",
        "trigger_note": "Non-directional setup — entry at market, range-based.",
    }


# ----------------------------------------------------------------------------
# Decision logic
# ----------------------------------------------------------------------------

def select(
    symbol: str,
    spot: float,
    direction: str,                          # BULLISH / BEARISH / SIDEWAYS
    confidence: float,                       # 0..100
    atr: float,
    iv_pct: float | None = None,             # nearest ATM IV %
    options_bias: str = "NEUTRAL",
    horizon: Horizon = "SWING",
    capital: float = 100_000,
    max_position_pct: float = 5.0,
    is_fno: bool = True,
    lot_size: int = 1,
    attach_timing: bool = True,              # compute Hora-based entry window
    vibration_score: float | None = None,    # 0..100 — Gann vibration confluence
    # ---- New: smart-entry inputs (optional — old callers still work) ----
    gann_support: float | None = None,       # nearest Gann support BELOW spot
    gann_resistance: float | None = None,    # nearest Gann resistance ABOVE spot
    recent_candles: list[dict] | None = None,  # last 5+ OHLC rows for confirmation
) -> StrategyPlan:

    notes: list[str] = []
    iv = iv_pct if iv_pct is not None else 20.0

    # ----------------------------------------------------------
    # Map direction + confidence + IV regime → strategy
    # ----------------------------------------------------------
    strategy: StrategyType = "WAIT"

    if direction == "BULLISH":
        if confidence < 55:
            strategy = "WAIT"
            notes.append("Bullish lean but confidence below 55 — wait for confirmation")
        elif iv < 18:
            strategy = "OPT_CE_BUY" if is_fno else "EQUITY_BUY"
            notes.append("Low IV — calls are cheap, buy outright")
        elif iv < 28:
            strategy = "OPT_BULL_CALL_SPREAD" if is_fno else "EQUITY_BUY"
            notes.append("Mid IV — bull-call spread caps cost while keeping upside")
        elif iv >= 28 and confidence >= 70:
            strategy = "FUT_LONG" if is_fno else "EQUITY_BUY"
            notes.append("High IV makes option premia expensive — use futures for directional bet")
        else:
            strategy = "EQUITY_BUY"

    elif direction == "BEARISH":
        if confidence < 55:
            strategy = "WAIT"
            notes.append("Bearish lean but confidence below 55 — wait for confirmation")
        elif iv < 18:
            strategy = "OPT_PE_BUY" if is_fno else "EQUITY_SHORT"
            notes.append("Low IV — puts are cheap, buy outright")
        elif iv < 28:
            strategy = "OPT_BEAR_PUT_SPREAD" if is_fno else "EQUITY_SHORT"
            notes.append("Mid IV — bear-put spread caps cost while keeping downside")
        elif iv >= 28 and confidence >= 70:
            strategy = "FUT_SHORT" if is_fno else "EQUITY_SHORT"
            notes.append("High IV expensive — use futures for directional bet")
        else:
            strategy = "EQUITY_SHORT"

    else:  # SIDEWAYS
        if iv >= 30 and is_fno:
            strategy = "OPT_IRON_CONDOR"
            notes.append("Range-bound + elevated IV — sell premium with defined risk (iron condor)")
        elif iv >= 35 and is_fno:
            strategy = "OPT_SHORT_STRANGLE"
            notes.append("Very high IV — short strangle premium decay play (margin intensive)")
        elif iv < 15 and is_fno:
            strategy = "OPT_LONG_STRADDLE"
            notes.append("Compressed IV — expect expansion, buy straddle")
        else:
            strategy = "WAIT"
            notes.append("Sideways with mid IV — no edge")

    # ----------------------------------------------------------
    # Compute entry / SL / target by strategy type
    #
    # `entry` is no longer just `spot` — _smart_entry picks the right trigger
    # price based on Gann support/resistance + ATR + consecutive-candle
    # confirmation. For directional strategies the SL is anchored BELOW the
    # entry trigger (not the LTP) so a pullback entry doesn't blow stops on
    # the same retracement that gave the entry.
    # ----------------------------------------------------------
    smart = _smart_entry(
        spot=spot, direction=direction, atr=atr,
        gann_support=gann_support, gann_resistance=gann_resistance,
        recent_candles=recent_candles,
    )
    entry = smart["entry"]

    if strategy in ("EQUITY_BUY", "FUT_LONG", "OPT_CE_BUY"):
        # SL below the structural support if we know one, else 1.5×ATR below entry
        sl_struct = (gann_support * 0.995) if (gann_support and gann_support > 0
                                                and gann_support < entry) else None
        stoploss = round(min(entry - 1.5 * atr, sl_struct) if sl_struct
                          else entry - 1.5 * atr, 2)
        targets = [round(entry + k * atr, 2) for k in (1.5, 2.5, 4.0)]
    elif strategy in ("EQUITY_SHORT", "FUT_SHORT", "OPT_PE_BUY"):
        sl_struct = (gann_resistance * 1.005) if (gann_resistance and gann_resistance > 0
                                                    and gann_resistance > entry) else None
        stoploss = round(max(entry + 1.5 * atr, sl_struct) if sl_struct
                          else entry + 1.5 * atr, 2)
        targets = [round(entry - k * atr, 2) for k in (1.5, 2.5, 4.0)]
    elif strategy == "OPT_BULL_CALL_SPREAD":
        stoploss = round(entry - 2 * atr, 2)
        targets = [round(entry + 1.5 * atr, 2), round(entry + 3 * atr, 2)]
    elif strategy == "OPT_BEAR_PUT_SPREAD":
        stoploss = round(entry + 2 * atr, 2)
        targets = [round(entry - 1.5 * atr, 2), round(entry - 3 * atr, 2)]
    elif strategy == "OPT_IRON_CONDOR":
        stoploss = round(spot + 3 * atr, 2)   # outer-wing breach (range strategy → anchored to spot)
        targets = [round(spot, 2)]            # max profit if expiry near spot
    elif strategy == "OPT_LONG_STRADDLE":
        stoploss = round(spot, 2)
        targets = [round(spot + 3 * atr, 2), round(spot - 3 * atr, 2)]
    elif strategy == "OPT_SHORT_STRANGLE":
        stoploss = round(spot + 3 * atr, 2)
        targets = [round(spot, 2)]
    else:
        stoploss = round(spot - 1 * atr, 2)
        targets = []

    risk = abs(entry - stoploss) if stoploss else 0
    reward = abs(targets[0] - entry) if targets else 0
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    # ----------------------------------------------------------
    # Position sizing
    # ----------------------------------------------------------
    if strategy == "WAIT":
        qty = 0
        cap_alloc_pct = 0.0
        cap_required = 0.0
    else:
        cap_alloc_pct = round(min(max_position_pct, (confidence - 50) / 50 * max_position_pct), 2)
        cap_alloc_pct = max(0.0, cap_alloc_pct)
        cap_required = capital * cap_alloc_pct / 100
        per_unit_cost = entry if strategy in ("EQUITY_BUY", "EQUITY_SHORT") else max(atr * 5, 50)
        qty = max(0, int(cap_required // per_unit_cost))
        # round to lot size for derivatives
        if strategy not in ("EQUITY_BUY", "EQUITY_SHORT") and lot_size > 1:
            qty = max(lot_size, (qty // lot_size) * lot_size)

    expected_max_profit = abs((targets[0] - entry) * qty) if targets else 0
    expected_max_loss = risk * qty if risk else 0

    # ----------------------------------------------------------
    # Instrument legs (for options spreads — informational)
    # ----------------------------------------------------------
    legs: list[dict] = []
    atm = round(spot / 50) * 50
    if strategy == "OPT_CE_BUY":
        legs = [{"action": "BUY", "type": "CE", "strike": atm}]
    elif strategy == "OPT_PE_BUY":
        legs = [{"action": "BUY", "type": "PE", "strike": atm}]
    elif strategy == "OPT_BULL_CALL_SPREAD":
        legs = [
            {"action": "BUY", "type": "CE", "strike": atm},
            {"action": "SELL", "type": "CE", "strike": atm + 100},
        ]
    elif strategy == "OPT_BEAR_PUT_SPREAD":
        legs = [
            {"action": "BUY", "type": "PE", "strike": atm},
            {"action": "SELL", "type": "PE", "strike": atm - 100},
        ]
    elif strategy == "OPT_IRON_CONDOR":
        legs = [
            {"action": "SELL", "type": "CE", "strike": atm + 100},
            {"action": "BUY",  "type": "CE", "strike": atm + 200},
            {"action": "SELL", "type": "PE", "strike": atm - 100},
            {"action": "BUY",  "type": "PE", "strike": atm - 200},
        ]
    elif strategy == "OPT_LONG_STRADDLE":
        legs = [
            {"action": "BUY", "type": "CE", "strike": atm},
            {"action": "BUY", "type": "PE", "strike": atm},
        ]
    elif strategy == "OPT_SHORT_STRANGLE":
        legs = [
            {"action": "SELL", "type": "CE", "strike": atm + 150},
            {"action": "SELL", "type": "PE", "strike": atm - 150},
        ]

    rationale = _rationale(strategy, direction, confidence, iv)

    # ---------- Per-signal "why this strategy" explainer ----------
    why = _why_this_strategy(strategy, direction, confidence, iv, atr,
                              rr, vibration_score, horizon)
    suitability_matrix = _suitability_matrix()

    # ---------- Timing: exact entry-time + window via planetary hora ----------
    timing: dict = {}
    if attach_timing and strategy != "WAIT":
        try:
            from app.engines import hora as hora_eng
            from datetime import datetime as _dt
            buy_or_sell = "BUY" if strategy in (
                "EQUITY_BUY", "FUT_LONG", "OPT_CE_BUY",
                "OPT_BULL_CALL_SPREAD", "OPT_LONG_STRADDLE",
            ) else "SELL" if strategy in (
                "EQUITY_SHORT", "FUT_SHORT", "OPT_PE_BUY", "OPT_BEAR_PUT_SPREAD",
            ) else "NEUTRAL"
            win = hora_eng.next_window(buy_or_sell)
            # Horizon-aware exit ceiling
            from datetime import timedelta as _td
            exit_by_dt = _dt.fromisoformat(win.entry_time)
            if horizon == "INTRADAY":
                # Exit before next planetary-hour change (or end of session)
                exit_by_dt = _dt.fromisoformat(win.window_end)
            elif horizon == "SWING":
                exit_by_dt = exit_by_dt + _td(days=5)
            else:                                          # POSITIONAL
                exit_by_dt = exit_by_dt + _td(days=20)
            timing = {
                "direction": buy_or_sell,
                "entry_time":   win.entry_time,
                "window_start": win.window_start,
                "window_end":   win.window_end,
                "minutes_to_entry": win.minutes_to_entry,
                "ruler": win.ruler,
                "hora_bias": win.bias,
                "rationale": win.rationale,
                "exit_by": exit_by_dt.isoformat(),
                "is_within_session": win.is_within_session,
                "caveat": (
                    "Timing is a confluence heuristic from Vedic muhurta (planetary hora). "
                    "It is NOT a guaranteed turning point. Confirm with live price action "
                    "before entry."
                ),
            }
        except Exception as e:                                # pragma: no cover
            timing = {"error": f"timing computation failed: {e}"}

    # ---------- Candle confirmation block ----------
    cons_dir = direction if direction in ("BULLISH", "BEARISH") else "BULLISH"
    cons_count = _consecutive_in_direction(recent_candles, cons_dir)
    # Default: require 2 consecutive aligned bars for swing/positional,
    # 3 for intraday (intraday signals need higher confirmation bar).
    required_cons = 3 if horizon == "INTRADAY" else 2
    candle_confirmation = {
        "consecutive_in_direction": cons_count,
        "required": required_cons,
        "confirmed": cons_count >= required_cons,
        "note": (f"{cons_count} consecutive {cons_dir.lower()} candles "
                  f"({'confirmed' if cons_count >= required_cons else 'below required ' + str(required_cons)})"
                  if direction in ("BULLISH", "BEARISH") else
                  "Non-directional setup — candle confirmation not applicable"),
    }
    if direction in ("BULLISH", "BEARISH") and cons_count < required_cons \
            and strategy != "WAIT":
        notes.append(
            f"Only {cons_count} consecutive {cons_dir.lower()} candles "
            f"(need ≥{required_cons}) — wait for momentum confirmation before entry"
        )

    return StrategyPlan(
        symbol=symbol,
        strategy=strategy,
        horizon=horizon,
        rationale=rationale,
        entry=entry,
        stoploss=stoploss,
        targets=targets,
        risk_reward=rr,
        suggested_qty=qty,
        capital_allocation_pct=cap_alloc_pct,
        capital_required_inr=round(cap_required, 2),
        expected_max_profit_inr=round(expected_max_profit, 2),
        expected_max_loss_inr=round(expected_max_loss, 2),
        entry_zone=smart.get("entry_zone", {}),
        trigger_type=smart.get("trigger_type", "MARKET"),
        trigger_note=smart.get("trigger_note", ""),
        candle_confirmation=candle_confirmation,
        instrument_legs=legs,
        notes=notes,
        timing=timing,
        why_this_strategy=why,
        suitability=suitability_matrix,
    )


def _rationale(strategy: StrategyType, direction: str, conf: float, iv: float) -> str:
    base = f"{direction} bias @ {conf:.0f}% confidence, ATM IV {iv:.1f}%."
    explain = {
        "EQUITY_BUY":             "Cash delivery long — simplest expression.",
        "EQUITY_SHORT":           "Intraday cash short (or futures short if held overnight).",
        "FUT_LONG":               "Futures long preferred — IV too high for premium plays, leverage available.",
        "FUT_SHORT":              "Futures short preferred — IV too high for premium plays.",
        "OPT_CE_BUY":             "Buy ATM call — cheap premium + directional conviction.",
        "OPT_PE_BUY":             "Buy ATM put — cheap premium + directional conviction.",
        "OPT_BULL_CALL_SPREAD":   "Buy ATM call, sell OTM call — caps cost, defined R:R.",
        "OPT_BEAR_PUT_SPREAD":    "Buy ATM put, sell OTM put — caps cost, defined R:R.",
        "OPT_IRON_CONDOR":        "Sell OTM call & put spreads — defined-risk premium harvest.",
        "OPT_LONG_STRADDLE":      "Buy ATM call + put — pay for volatility expansion.",
        "OPT_SHORT_STRANGLE":     "Sell OTM call + put — collect rich premia; margin heavy.",
        "WAIT":                   "Edge insufficient — preserve capital, wait for confluence.",
    }
    return base + " " + explain.get(strategy, "")


# ---------------------------------------------------------------------------
# "Why this strategy" explainer — surfaces the *decision factors* that drove
# the selection. Lets the user audit confluence vs the suitability matrix.
# ---------------------------------------------------------------------------

def _why_this_strategy(strategy: StrategyType, direction: str, conf: float,
                       iv: float, atr: float, rr: float,
                       vibration_score: float | None, horizon: Horizon) -> list[str]:
    why: list[str] = []

    # Direction-confidence axis
    if direction == "BULLISH":
        why.append(f"BULLISH lean @ {conf:.0f}% confidence ⇒ favour long-delta strategies")
    elif direction == "BEARISH":
        why.append(f"BEARISH lean @ {conf:.0f}% confidence ⇒ favour short-delta strategies")
    else:
        why.append(f"SIDEWAYS @ {conf:.0f}% ⇒ favour non-directional / theta-harvest strategies")

    # IV regime
    if iv < 18:
        why.append(f"IV {iv:.1f}% LOW ⇒ option premia are cheap; buying options favoured over selling")
    elif iv < 28:
        why.append(f"IV {iv:.1f}% MID ⇒ spreads (defined-risk) optimal: capped cost + capped reward")
    elif iv < 35:
        why.append(f"IV {iv:.1f}% HIGH ⇒ premium selling viable; long options expensive")
    else:
        why.append(f"IV {iv:.1f}% VERY HIGH ⇒ either short premium or move to futures for directional")

    # Strategy-specific justification
    strat_why = {
        "EQUITY_BUY":            "Cash equity chosen — non-F&O symbol OR confidence too low for leverage",
        "EQUITY_SHORT":          "Cash short — non-F&O OR margin-conservative bearish view",
        "FUT_LONG":              "Futures long preferred — IV makes option premia uneconomical for a directional bet",
        "FUT_SHORT":             "Futures short preferred — IV makes put premia too expensive vs leverage",
        "OPT_CE_BUY":            "Naked CE buy — cheap premium + strong directional conviction; max risk = premium paid",
        "OPT_PE_BUY":            "Naked PE buy — cheap premium + strong directional conviction; max risk = premium paid",
        "OPT_BULL_CALL_SPREAD":  "Bull-call spread — buys ATM CE, sells OTM CE: cuts premium ~50%, caps upside but max loss bounded",
        "OPT_BEAR_PUT_SPREAD":   "Bear-put spread — buys ATM PE, sells OTM PE: cuts premium ~50%, caps downside but max loss bounded",
        "OPT_IRON_CONDOR":       "Iron condor — sell strangle + buy wider strangle: collects net credit, profits if price stays in range, max loss = wing width − credit",
        "OPT_LONG_STRADDLE":     "Long straddle — buy ATM CE + PE: profits on a *big move either way*, loses if price sits still and IV decays",
        "OPT_SHORT_STRANGLE":    "Short strangle — sell OTM CE + PE for credit: profits on theta + IV crush, UNDEFINED RISK if price breaks out",
        "WAIT":                  "No-trade — confluence below 55% threshold; preserving capital",
    }
    if strategy in strat_why:
        why.append(strat_why[strategy])

    # Risk-reward
    if rr > 0:
        if rr >= 2.0:
            why.append(f"Risk-reward {rr}:1 is favourable (≥2:1) — supports position taking")
        elif rr >= 1.0:
            why.append(f"Risk-reward {rr}:1 is acceptable but marginal")
        else:
            why.append(f"Risk-reward {rr}:1 is below 1:1 — strategy will need high hit-rate to be net-positive")

    # Volatility (ATR)
    vol_pct = (atr / 100) if atr else 0
    if atr > 0:
        why.append(f"ATR {atr:.2f} drives SL/target geometry (1.5× / 2.5× / 4× ATR)")

    # Horizon adaptation
    if horizon == "INTRADAY":
        why.append("INTRADAY horizon — exit forced before next planetary-hora change or NSE close")
    elif horizon == "SWING":
        why.append("SWING horizon — hold up to 5 days; trail SL on each 1× ATR move")
    else:
        why.append("POSITIONAL — hold up to 20 days; watch Gann time-cycle reversal dates")

    # Vibration confluence
    if vibration_score is not None:
        if vibration_score >= 65:
            why.append(f"Gann vibration resonance {vibration_score:.0f}/100 BULLISH — natal harmonic active")
        elif vibration_score <= 35:
            why.append(f"Gann vibration resonance {vibration_score:.0f}/100 BEARISH — discordant harmonic")
        else:
            why.append(f"Gann vibration resonance {vibration_score:.0f}/100 neutral — no harmonic boost")

    return why


# ---------------------------------------------------------------------------
# Suitability matrix — for every strategy, when it is suitable.
# Returned in every signal so the UI / user can cross-check.
# ---------------------------------------------------------------------------

def _suitability_matrix() -> dict:
    return {
        "EQUITY_BUY":             "Trending up, any IV, capital-light, no F&O margin required.",
        "EQUITY_SHORT":           "Trending down, intraday only (no SLB), strong technical breakdown.",
        "FUT_LONG":               "Strong bullish + high IV (option premia too expensive). Margin available.",
        "FUT_SHORT":              "Strong bearish + high IV. Watch for short-squeeze gap-ups overnight.",
        "OPT_CE_BUY":             "Strong directional UP move expected within expiry window AND low IV (<18%).",
        "OPT_PE_BUY":             "Strong directional DOWN move expected within expiry window AND low IV (<18%).",
        "OPT_BULL_CALL_SPREAD":   "Moderate bullish + mid-IV (18-28%). Cap cost. Defined risk:reward.",
        "OPT_BEAR_PUT_SPREAD":    "Moderate bearish + mid-IV (18-28%). Cap cost. Defined risk:reward.",
        "OPT_IRON_CONDOR":        "Range-bound expectation + high IV (>30%). Theta-harvest, defined wings.",
        "OPT_LONG_STRADDLE":      "Big move expected EITHER way (earnings, event) + currently low IV. Vol expansion play.",
        "OPT_SHORT_STRANGLE":     "Range-bound + very high IV (>35%). UNLIMITED RISK — only with stop-loss alerts.",
        "WAIT":                   "Confluence below 55% — preserve capital; re-scan next bar.",
    }
