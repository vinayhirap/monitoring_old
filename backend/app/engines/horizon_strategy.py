"""Per-horizon strategy planner.

Given a symbol's full analysis (direction, confidence, ATR, IV, quant regime,
hora), produces a *different* trade plan for each horizon:

  • INTRADAY    — minutes to hours, square off by EOD
  • SWING       — 2-10 trading days
  • POSITIONAL  — 2-12 weeks

Each plan answers:
    1. WHICH strategy fits this horizon × regime × direction
    2. WHICH instrument (equity, futures, options expiry)
    3. WHAT entry / SL / target multiples (different per horizon)
    4. HOW LONG to expect to be in the trade (bars + calendar days)
    5. WHEN to enter (time-of-day rules)
    6. WHEN to exit (rules, not just price targets)
    7. POSITION sizing per horizon
    8. REGIME FIT score (does the current regime support this horizon?)

The holding-time estimate uses ATR-implied velocity:
    expected_bars_to_target ≈ target_distance / (ATR × 0.6)
where 0.6 is the empirical "directional content" of average bar range
(bars rarely move full ATR in one direction; ~60% net is the rough estimate
from price-action research on liquid Indian equities).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
import math

import pandas as pd


Horizon = Literal["INTRADAY", "SWING", "POSITIONAL"]


# ===========================================================================
# Per-horizon configuration matrix
# ===========================================================================

HORIZON_CONFIG: dict[str, dict] = {
    "INTRADAY": {
        "atr_sl_mult":        0.75,
        "atr_t1_mult":        0.75,
        "atr_t2_mult":        1.50,
        "atr_t3_mult":        2.50,
        "max_holding_bars":   30,        # ~7-8 hours of 15-min bars
        "expected_bar_minutes": 15,
        "directional_content":  0.55,    # intraday bars more random
        "preferred_instruments": ["INDEX_OPTIONS", "STOCK_FUTURES", "STOCK_OPTIONS_ATM"],
        "avoid_instruments":    ["EQUITY_DELIVERY"],
        "best_entry_windows":   [(10, 30), (13, 30)],   # (hour, minute) — start of window
        "worst_entry_windows":  [(9, 15), (15, 0)],     # avoid first 15 min, last 30
        "hard_exit_by_minute":  (15, 20),
        "hora_alignment_required": True,
        "min_iv_for_ce_buy":   0,         # any IV ok for short-dated
        "max_iv_for_ce_buy":   45,
        "good_regimes":         ["TRENDING", "MEAN_REVERTING"],
        "bad_regimes":          ["CHOPPY"],
        "position_sizing_cap_pct": 5.0,   # 5% of capital max
        "min_confidence":       62,
    },
    "SWING": {
        "atr_sl_mult":        1.5,
        "atr_t1_mult":        1.5,
        "atr_t2_mult":        2.5,
        "atr_t3_mult":        4.0,
        "max_holding_bars":   15,         # ~3 weeks on daily bars
        "expected_bar_minutes": 60 * 6,   # 1 trading day = 6 hours
        "directional_content":  0.65,
        "preferred_instruments": ["STOCK_FUTURES", "STOCK_OPTIONS_MONTHLY", "EQUITY_DELIVERY", "BULL_CALL_SPREAD"],
        "avoid_instruments":    ["INDEX_WEEKLY_OPTIONS"],   # too much theta over multiple days
        "best_entry_windows":   [(9, 15), (10, 0)],         # at open or first hour confirm
        "worst_entry_windows":  [],
        "hard_exit_by_minute":  None,
        "hora_alignment_required": False,
        "min_iv_for_ce_buy":   12,
        "max_iv_for_ce_buy":   30,
        "good_regimes":         ["TRENDING", "MEAN_REVERTING"],
        "bad_regimes":          ["CHOPPY"],
        "position_sizing_cap_pct": 8.0,
        "min_confidence":       60,
    },
    "POSITIONAL": {
        "atr_sl_mult":        3.0,
        "atr_t1_mult":        3.0,
        "atr_t2_mult":        5.0,
        "atr_t3_mult":        8.0,
        "max_holding_bars":   90,         # ~4.5 months on daily bars
        "expected_bar_minutes": 60 * 6,
        "directional_content":  0.70,     # longer-horizon trends are more persistent
        "preferred_instruments": ["EQUITY_DELIVERY", "FAR_MONTH_FUTURES", "BULL_CALL_SPREAD_FAR"],
        "avoid_instruments":    ["WEEKLY_OPTIONS", "ATM_OPTIONS_NAKED"],
        "best_entry_windows":   [(10, 0), (14, 0)],
        "worst_entry_windows":  [],
        "hard_exit_by_minute":  None,
        "hora_alignment_required": False,
        "min_iv_for_ce_buy":   10,
        "max_iv_for_ce_buy":   25,
        "good_regimes":         ["TRENDING"],
        "bad_regimes":          ["MEAN_REVERTING", "CHOPPY"],
        "position_sizing_cap_pct": 15.0,
        "min_confidence":       58,
    },
}


# ===========================================================================
# Output
# ===========================================================================

@dataclass
class HorizonPlan:
    horizon: str
    fit_score: float                     # 0..100, how well horizon × regime × direction align
    fit_rating: str                      # EXCELLENT / GOOD / MARGINAL / POOR
    recommended: bool                    # true if this horizon should be acted on

    # Strategy choice
    strategy: str                        # CE_BUY / BULL_CALL_SPREAD / FUT_LONG / EQUITY_BUY / WAIT etc.
    strategy_rationale: str
    preferred_instrument: str

    # Price levels
    entry: float
    stoploss: float
    target_1: float
    target_2: float
    target_3: float
    risk_reward_t1: float
    risk_reward_t3: float

    # Time estimates
    expected_bars_to_t1: float
    expected_bars_to_t2: float
    expected_bars_to_t3: float
    expected_calendar_days_to_t1: float
    expected_calendar_days_to_t2: float
    expected_calendar_days_to_t3: float
    max_holding_calendar_days: float

    # Timing
    best_entry_time: str                 # "10:30" or "next session 09:15"
    worst_entry_time: str | None         # "avoid 09:15-09:30"
    hard_exit_time: str | None           # "15:20 today" for intraday, None for swing+
    hora_requirement: str                # required / preferred / not-needed

    # Position sizing
    suggested_capital_pct: float         # of total capital
    suggested_capital_inr: float
    suggested_qty: int
    max_loss_inr: float

    # Exit rules
    exit_rules: list[str]
    review_cadence: str                  # "every 15 min" / "daily close" / "weekly"

    # Caveats
    caveats: list[str]
    regime_at_analysis: str

    def to_dict(self) -> dict:
        return self.__dict__


# ===========================================================================
# Fit-score computation — how well does this horizon match the situation?
# ===========================================================================

def _compute_fit_score(horizon: str, direction: str, confidence: float,
                       regime: str, hurst: float, lr_r2: float,
                       ou_half_life: float | None) -> tuple[float, str, list[str]]:
    """Score 0-100 + rating + reasons explaining the fit."""
    cfg = HORIZON_CONFIG[horizon]
    score = 50.0
    reasons: list[str] = []

    # 1. Confidence threshold
    if confidence < cfg["min_confidence"]:
        score -= 20
        reasons.append(f"Confidence {confidence:.0f}% below {horizon} threshold ({cfg['min_confidence']}%)")
    elif confidence >= 75:
        score += 12
        reasons.append(f"High confidence {confidence:.0f}% — strong fit for {horizon}")
    elif confidence >= 65:
        score += 6
        reasons.append(f"Decent confidence {confidence:.0f}%")

    # 2. Regime fit
    if regime in cfg["good_regimes"]:
        score += 15
        reasons.append(f"Regime {regime} fits {horizon} well")
    elif regime in cfg["bad_regimes"]:
        score -= 18
        reasons.append(f"Regime {regime} POORLY fits {horizon} — strategies likely fail")

    # 3. Hurst alignment per horizon
    if horizon == "POSITIONAL":
        # Positional needs strong trend
        if hurst > 0.6:
            score += 10; reasons.append(f"Hurst {hurst:.2f} confirms persistent trend — ideal for positional")
        elif hurst < 0.45:
            score -= 15; reasons.append(f"Hurst {hurst:.2f} mean-reverting — bad for positional holds")
    elif horizon == "INTRADAY":
        # Intraday loves both extremes (trend or mean-rev), hates random walk
        if abs(hurst - 0.5) > 0.10:
            score += 7; reasons.append(f"Hurst {hurst:.2f} — exploitable for intraday")
        else:
            score -= 5; reasons.append(f"Hurst {hurst:.2f} near random — intraday edge weak")
    else:  # SWING
        if 0.45 < hurst < 0.65:
            score += 5; reasons.append(f"Hurst {hurst:.2f} acceptable for swing")

    # 4. Linear-regression trend quality (R²)
    if horizon in ("SWING", "POSITIONAL") and lr_r2 > 0.7:
        score += 8; reasons.append(f"LR R²={lr_r2:.2f} — strong directional trend supports {horizon}")
    elif horizon in ("SWING", "POSITIONAL") and lr_r2 < 0.25:
        score -= 8; reasons.append(f"LR R²={lr_r2:.2f} — no clear trend, weak fit for {horizon}")

    # 5. OU half-life vs horizon length
    if ou_half_life is not None:
        bars = ou_half_life
        if horizon == "INTRADAY" and bars < 30:
            score += 5; reasons.append(f"Mean-reversion half-life {bars:.0f} bars — fits intraday")
        elif horizon == "POSITIONAL" and bars > 40:
            score += 4; reasons.append(f"Long half-life {bars:.0f} bars — supports positional holding")
        elif horizon == "POSITIONAL" and bars < 10:
            score -= 10; reasons.append(f"Half-life only {bars:.0f} bars — too mean-reverting for positional")

    # 6. Direction sanity — NEUTRAL with any horizon is weak
    if direction == "NEUTRAL":
        score -= 12
        reasons.append("Direction NEUTRAL — no directional edge for any horizon")

    score = max(0, min(100, score))
    rating = ("EXCELLENT" if score >= 80 else
              "GOOD"      if score >= 65 else
              "MARGINAL"  if score >= 50 else
              "POOR")
    return score, rating, reasons


# ===========================================================================
# Strategy selection per horizon × direction × IV regime
# ===========================================================================

def _select_strategy(horizon: str, direction: str, confidence: float,
                     iv_pct: float, cfg: dict) -> tuple[str, str, str]:
    """Returns (strategy_code, instrument, rationale)."""
    if confidence < cfg["min_confidence"]:
        return "WAIT", "NONE", (
            f"Confidence {confidence:.0f}% below {horizon} minimum {cfg['min_confidence']}% — preserve capital"
        )

    if direction == "BULLISH":
        if horizon == "INTRADAY":
            if iv_pct < 25:
                return ("OPT_CE_BUY_ATM",
                        "INDEX/STOCK ATM call (weekly expiry)",
                        f"Intraday + bullish + IV {iv_pct:.0f}% cheap → buy ATM CE for max gamma exposure")
            return ("FUT_LONG",
                    "Stock or index futures",
                    f"Intraday + bullish + IV {iv_pct:.0f}% rich → futures avoid theta+IV burn")
        elif horizon == "SWING":
            if iv_pct < 18 and confidence >= 70:
                return ("OPT_CE_BUY_MONTHLY",
                        "Monthly ATM call",
                        f"Swing + strong bullish + low IV — monthly CE captures multi-day move")
            if iv_pct < 28:
                return ("BULL_CALL_SPREAD",
                        "Monthly ATM CE buy + OTM CE sell",
                        f"Swing + bullish + mid IV {iv_pct:.0f}% → spread caps premium cost")
            return ("FUT_LONG",
                    "Stock futures (current month)",
                    f"Swing + bullish + high IV {iv_pct:.0f}% — futures preferred")
        else:  # POSITIONAL
            return ("EQUITY_BUY_DELIVERY" if iv_pct >= 22 else "BULL_CALL_SPREAD_FAR",
                    "Equity delivery OR far-month bull call spread",
                    f"Positional + bullish — own equity for compound, hedge with far-month spread if IV {iv_pct:.0f}% manageable")

    elif direction == "BEARISH":
        if horizon == "INTRADAY":
            if iv_pct < 25:
                return ("OPT_PE_BUY_ATM",
                        "Index/stock ATM put (weekly)",
                        f"Intraday + bearish + IV {iv_pct:.0f}% cheap → ATM PE for gamma")
            return ("FUT_SHORT",
                    "Stock or index futures short",
                    f"Intraday + bearish + IV {iv_pct:.0f}% rich → short futures")
        elif horizon == "SWING":
            if iv_pct < 28:
                return ("BEAR_PUT_SPREAD",
                        "Monthly ATM PE buy + OTM PE sell",
                        f"Swing + bearish + IV {iv_pct:.0f}% → bear put spread")
            return ("FUT_SHORT",
                    "Stock futures short",
                    f"Swing + bearish + IV {iv_pct:.0f}% rich → futures short")
        else:  # POSITIONAL bearish
            return ("FUT_SHORT_FAR" if iv_pct < 25 else "BEAR_PUT_SPREAD_FAR",
                    "Far-month futures short OR bear put spread",
                    "Positional bearish — equity cash short not viable >intraday in India; use F&O")

    else:  # NEUTRAL / SIDEWAYS
        if horizon == "INTRADAY":
            return ("WAIT", "NONE",
                    "Intraday + neutral = no edge. Skip the session, preserve capital.")
        elif horizon == "SWING":
            if iv_pct >= 30:
                return ("IRON_CONDOR",
                        "Monthly iron condor — sell ±1 strike, buy ±2 strike wings",
                        f"Swing + range-bound + high IV {iv_pct:.0f}% → harvest theta with defined wings")
            return ("WAIT", "NONE",
                    "Swing + neutral + IV not high enough — no premium edge")
        else:  # POSITIONAL neutral
            return ("WAIT", "NONE",
                    "Positional + neutral = no thesis. Wait for trend to develop.")


# ===========================================================================
# Public entry — one horizon plan
# ===========================================================================

def plan(symbol: str, spot: float, direction: str, confidence: float,
          atr: float, iv_pct: float | None,
          horizon: Horizon,
          regime: str = "CHOPPY",
          hurst: float = 0.5, lr_r2: float = 0.0,
          ou_half_life: float | None = None,
          capital: float = 100_000,
          hora_ruler: str | None = None, hora_bias: str | None = None,
          asof: datetime | None = None) -> HorizonPlan:
    """Produce a complete per-horizon trade plan."""
    cfg = HORIZON_CONFIG[horizon]
    iv = iv_pct if iv_pct is not None else 20.0
    asof = asof or datetime.now()

    # 1. Fit-score
    fit_score, fit_rating, fit_reasons = _compute_fit_score(
        horizon, direction, confidence, regime, hurst, lr_r2, ou_half_life
    )

    # 2. Strategy
    strategy, instrument, strat_rationale = _select_strategy(
        horizon, direction, confidence, iv, cfg
    )

    # 3. Entry / SL / Targets — direction-adjusted, horizon-scaled
    entry = round(spot, 2)
    if direction == "BULLISH":
        sl  = round(spot - cfg["atr_sl_mult"]  * atr, 2)
        t1  = round(spot + cfg["atr_t1_mult"]  * atr, 2)
        t2  = round(spot + cfg["atr_t2_mult"]  * atr, 2)
        t3  = round(spot + cfg["atr_t3_mult"]  * atr, 2)
    elif direction == "BEARISH":
        sl  = round(spot + cfg["atr_sl_mult"]  * atr, 2)
        t1  = round(spot - cfg["atr_t1_mult"]  * atr, 2)
        t2  = round(spot - cfg["atr_t2_mult"]  * atr, 2)
        t3  = round(spot - cfg["atr_t3_mult"]  * atr, 2)
    else:
        sl = round(spot - cfg["atr_sl_mult"] * atr, 2)
        t1 = t2 = t3 = round(spot, 2)

    risk = abs(entry - sl) if sl else 0
    rr1 = round(abs(t1 - entry) / risk, 2) if risk > 0 else 0
    rr3 = round(abs(t3 - entry) / risk, 2) if risk > 0 else 0

    # 4. Expected bars-to-target — ATR-velocity model
    directional_atr_per_bar = atr * cfg["directional_content"]
    if directional_atr_per_bar > 0:
        bars_t1 = abs(t1 - entry) / directional_atr_per_bar
        bars_t2 = abs(t2 - entry) / directional_atr_per_bar
        bars_t3 = abs(t3 - entry) / directional_atr_per_bar
    else:
        bars_t1 = bars_t2 = bars_t3 = float("nan")

    # Cap by max_holding_bars
    bars_t3 = min(bars_t3, cfg["max_holding_bars"])

    bar_min = cfg["expected_bar_minutes"]
    days_per_bar = bar_min / (60 * 6) if bar_min >= 60 else bar_min / 60 / 6
    days_t1 = bars_t1 * days_per_bar if horizon != "INTRADAY" else bars_t1 / 24 * (bar_min / 60)
    days_t2 = bars_t2 * days_per_bar if horizon != "INTRADAY" else bars_t2 / 24 * (bar_min / 60)
    days_t3 = bars_t3 * days_per_bar if horizon != "INTRADAY" else bars_t3 / 24 * (bar_min / 60)
    max_days = cfg["max_holding_bars"] * days_per_bar if horizon != "INTRADAY" else 1

    # 5. Position sizing
    if strategy == "WAIT":
        qty = 0; cap_pct = 0; cap_inr = 0; max_loss = 0
    else:
        # Confidence-scaled within the horizon cap
        scaled = min(cfg["position_sizing_cap_pct"],
                      max(0, (confidence - 50) / 50 * cfg["position_sizing_cap_pct"]))
        cap_pct = round(scaled, 2)
        cap_inr = round(capital * cap_pct / 100, 2)
        # Per-unit cost depends on instrument; rough heuristic
        if "OPT_" in strategy or "SPREAD" in strategy:
            per_unit = max(atr * 5, 50)
        elif "FUT_" in strategy:
            per_unit = entry * 0.15           # ~15% margin
        else:
            per_unit = entry
        qty = max(0, int(cap_inr // max(per_unit, 1)))
        max_loss = round(risk * qty, 2) if "OPT_" not in strategy else cap_inr

    # 6. Best entry time (next benefic window)
    best_time = _next_entry_window(horizon, cfg, asof)
    worst_time = _avoid_window_str(horizon, cfg)
    exit_time_str = _hard_exit_str(cfg)

    # 7. Hora alignment
    if cfg["hora_alignment_required"]:
        if hora_bias == "bullish" and direction == "BULLISH":
            hora_req = "MET"
        elif hora_bias == "bearish" and direction == "BEARISH":
            hora_req = "MET"
        elif hora_bias is None:
            hora_req = "REQUIRED — waiting for hora data"
        else:
            hora_req = f"NOT MET — current hora {hora_ruler} ({hora_bias}) — wait for benefic window"
    else:
        hora_req = "PREFERRED but not required"

    # 8. Exit rules per horizon
    exit_rules = _exit_rules_for(horizon, strategy)

    # 9. Caveats
    caveats: list[str] = []
    if fit_rating in ("MARGINAL", "POOR"):
        caveats.append(f"Horizon fit {fit_rating} — consider a different horizon if available")
    caveats.extend(fit_reasons[-3:])
    if strategy == "WAIT":
        caveats.append("System recommends WAIT for this horizon — do not force a trade")

    return HorizonPlan(
        horizon=horizon,
        fit_score=fit_score,
        fit_rating=fit_rating,
        recommended=(fit_rating in ("EXCELLENT", "GOOD") and strategy != "WAIT"),
        strategy=strategy,
        strategy_rationale=strat_rationale,
        preferred_instrument=instrument,
        entry=entry, stoploss=sl,
        target_1=t1, target_2=t2, target_3=t3,
        risk_reward_t1=rr1, risk_reward_t3=rr3,
        expected_bars_to_t1=round(bars_t1, 1),
        expected_bars_to_t2=round(bars_t2, 1),
        expected_bars_to_t3=round(bars_t3, 1),
        expected_calendar_days_to_t1=round(days_t1, 1),
        expected_calendar_days_to_t2=round(days_t2, 1),
        expected_calendar_days_to_t3=round(days_t3, 1),
        max_holding_calendar_days=round(max_days, 1),
        best_entry_time=best_time,
        worst_entry_time=worst_time,
        hard_exit_time=exit_time_str,
        hora_requirement=hora_req,
        suggested_capital_pct=cap_pct,
        suggested_capital_inr=cap_inr,
        suggested_qty=qty,
        max_loss_inr=max_loss,
        exit_rules=exit_rules,
        review_cadence={"INTRADAY": "every 15-30 min",
                         "SWING":    "daily close",
                         "POSITIONAL": "weekly close"}[horizon],
        caveats=caveats,
        regime_at_analysis=regime,
    )


def plan_all_horizons(symbol: str, spot: float, direction: str, confidence: float,
                       atr: float, iv_pct: float | None = None,
                       regime: str = "CHOPPY", hurst: float = 0.5,
                       lr_r2: float = 0.0, ou_half_life: float | None = None,
                       capital: float = 100_000,
                       hora_ruler: str | None = None,
                       hora_bias: str | None = None) -> dict:
    """Return all three horizon plans + the recommended pick."""
    plans = {h: plan(symbol, spot, direction, confidence, atr, iv_pct, h,
                      regime=regime, hurst=hurst, lr_r2=lr_r2, ou_half_life=ou_half_life,
                      capital=capital, hora_ruler=hora_ruler, hora_bias=hora_bias).to_dict()
              for h in ("INTRADAY", "SWING", "POSITIONAL")}
    # Recommended = best fit-score among non-WAIT
    eligible = {h: p for h, p in plans.items() if p["strategy"] != "WAIT"}
    if eligible:
        recommended_h = max(eligible.items(), key=lambda kv: kv[1]["fit_score"])[0]
    else:
        recommended_h = "WAIT_ALL"
    return {
        "symbol": symbol,
        "regime": regime,
        "recommended_horizon": recommended_h,
        "plans": plans,
        "note": (
            "Each horizon has a separate plan with its own strategy, instrument, "
            "stop, targets, holding time estimate, and entry/exit rules. The "
            "'recommended_horizon' is the one with the highest fit score. Skip "
            "horizons marked WAIT — forcing a trade in a poor-fit horizon is the "
            "single most common retail loss pattern."
        ),
    }


# ===========================================================================
# Time-window helpers
# ===========================================================================

def _next_entry_window(horizon: str, cfg: dict, asof: datetime) -> str:
    if horizon == "INTRADAY":
        h, m = asof.hour, asof.minute
        # Pick first best window that hasn't passed
        for (wh, wm) in cfg["best_entry_windows"]:
            if (h, m) < (wh, wm):
                return f"today {wh:02d}:{wm:02d}"
        return f"next session {cfg['best_entry_windows'][0][0]:02d}:{cfg['best_entry_windows'][0][1]:02d}"
    elif horizon == "SWING":
        # Best entry next session at 09:15 (or first hour confirmation)
        return f"next session 09:15 (or wait for first-hour breakout 10:00)"
    else:  # POSITIONAL
        return "any time today; quality of entry timing low-weight at this horizon"


def _avoid_window_str(horizon: str, cfg: dict) -> str | None:
    if not cfg["worst_entry_windows"]:
        return None
    parts = [f"{h:02d}:{m:02d}" for (h, m) in cfg["worst_entry_windows"]]
    return f"AVOID entry around: {', '.join(parts)} (first 15 min / last 30 min — choppy)"


def _hard_exit_str(cfg: dict) -> str | None:
    if cfg["hard_exit_by_minute"] is None:
        return None
    h, m = cfg["hard_exit_by_minute"]
    return f"FORCED EXIT by {h:02d}:{m:02d} IST (NSE auto-square at 15:25)"


def _exit_rules_for(horizon: str, strategy: str) -> list[str]:
    rules: list[str] = []
    if strategy == "WAIT":
        return ["No trade — wait for next confluence opportunity"]
    if horizon == "INTRADAY":
        rules = [
            "T1 hit → book 50%, move SL to entry (BE stop)",
            "T2 hit → book remaining 50%",
            "T3 acts as trail target; if reached, exit fully",
            "SL hit → exit immediately, do not double down",
            "Theta watch (for options): if delta < 0.30 after 1 hour, exit",
            "MUST close all positions by 15:20 IST regardless",
        ]
    elif horizon == "SWING":
        rules = [
            "T1 hit → book 50%, trail SL to entry",
            "T2 hit → book 25%, trail SL to T1",
            "T3 hit → book final 25% or trail with prior swing low",
            "SL hit → exit; review and re-evaluate on the next session",
            "Time stop: exit if T1 not hit within max_holding_calendar_days",
            "Re-evaluate at every daily close vs new signal",
        ]
    else:  # POSITIONAL
        rules = [
            "T1 hit → book 30%, raise SL to entry",
            "T2 hit → book 30%, raise SL to T1",
            "T3 hit → book remaining 40% or trail with 20-week moving average",
            "Major Gann time-cycle date approaching? → reduce exposure 50% as a hedge",
            "Weekly review: still in good regime? still trending? if regime flipped to CHOPPY → exit",
            "No hard time stop — let winners run; exit only on technical/regime change",
        ]
    return rules
