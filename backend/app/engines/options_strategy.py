"""Options strategy recommender — picks specific strikes + delta/theta-driven
entry & exit triggers, projects max profit / max loss with live chain greeks.

Given:
  • symbol, spot, direction, confidence, capital
  • live options chain (from Angel One or synthetic for paper)
  • days to expiry
  • horizon (INTRADAY / SWING / POSITIONAL)

Returns:
  • picked strategy (CE_BUY / PE_BUY / SPREAD / IRON_CONDOR / etc.)
  • specific strikes for each leg
  • computed greeks per leg (delta, gamma, theta, vega) using Black-Scholes
  • net premium debit/credit, max profit, max loss, breakeven(s)
  • entry triggers — "enter when delta crosses 0.55", "wait for IV crush", etc.
  • exit triggers — target % gain, theta-burn cutoff, delta-inflection cutoff,
                    time-stop (close before EOD for intraday), SL on underlying
  • intraday gamma exposure tracking
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
import math

from app.engines.options import bs_greeks


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

@dataclass
class OptionsTradePlan:
    symbol: str
    spot: float
    direction: str                              # BULLISH / BEARISH / NEUTRAL
    confidence: float
    expiry: str
    days_to_expiry: int
    iv_pct: float
    iv_regime: str                              # LOW / MID / HIGH / VERY_HIGH
    strategy: str
    strategy_subtype: str
    legs: list[dict]                            # detailed per-leg breakdown w/ greeks
    net_premium_inr: float                      # negative = debit, positive = credit
    max_profit_inr: float
    max_loss_inr: float
    breakeven_prices: list[float]
    risk_reward: float
    suggested_lots: int
    suggested_capital_inr: float
    margin_required_inr: float | None
    entry_triggers: list[str]
    exit_triggers: list[str]
    portfolio_greeks: dict                      # net delta/gamma/theta/vega of the basket
    intraday_notes: list[str]
    confidence_caveats: list[str]
    disclaimer: str = (
        "Options carry significant risk — premium decay (theta), IV crush, and "
        "gap risk can wipe a position overnight. Recommended strikes assume the "
        "live chain greeks at time of analysis; re-verify before entry. "
        "NOT SEBI-registered advice."
    )

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# IV regime
# ---------------------------------------------------------------------------

def _iv_regime(iv_pct: float) -> str:
    if iv_pct < 15:    return "LOW"
    if iv_pct < 22:    return "MID"
    if iv_pct < 32:    return "HIGH"
    return "VERY_HIGH"


# ---------------------------------------------------------------------------
# Strike selection helpers
# ---------------------------------------------------------------------------

def _round_to_strike_step(price: float, step: float) -> float:
    return round(price / step) * step


def _nearest_strike_row(chain: list[dict], strike: float) -> dict | None:
    if not chain:
        return None
    return min(chain, key=lambda r: abs(r["strike"] - strike))


def _strike_step_for(spot: float) -> float:
    """Heuristic strike step for Indian F&O.
    NIFTY=50, BANKNIFTY=100, large stocks=50, mid stocks=10/20.
    """
    if spot > 30000:   return 100.0    # BANKNIFTY-ish
    if spot > 10000:   return 50.0
    if spot > 1000:    return 20.0
    if spot > 200:     return 10.0
    return 5.0


# ---------------------------------------------------------------------------
# Per-strategy strike picking + greeks computation
# ---------------------------------------------------------------------------

def _build_leg(action: str, opt_type: str, strike: float, chain: list[dict],
               spot: float, t_years: float, r: float, iv: float, lot_size: int) -> dict:
    row = _nearest_strike_row(chain, strike)
    actual_strike = row["strike"] if row else strike
    is_call = (opt_type == "CE")
    greeks = bs_greeks(spot, actual_strike, t_years, r, iv, is_call)
    ltp_key = "ce_ltp" if is_call else "pe_ltp"
    ltp = float(row.get(ltp_key, greeks["price"])) if row else greeks["price"]
    return {
        "action": action,                # BUY / SELL
        "type": opt_type,                # CE / PE
        "strike": actual_strike,
        "ltp": round(ltp, 2),
        "theoretical_price": greeks["price"],
        "delta": greeks["delta"],
        "gamma": greeks["gamma"],
        "theta": greeks["theta"],
        "vega": greeks["vega"],
        "rho": greeks["rho"],
        "lot_size": lot_size,
        "premium_per_lot_inr": round(ltp * lot_size, 2),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def recommend(
    symbol: str,
    spot: float,
    direction: str,                              # BULLISH / BEARISH / NEUTRAL
    confidence: float,                           # 0..100
    chain: list[dict],                           # [{strike, ce_oi, pe_oi, ce_iv, pe_iv, ce_ltp, pe_ltp}]
    expiry: date,
    capital: float = 100_000,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    lot_size: int = 1,
    risk_free: float = 0.07,
) -> OptionsTradePlan:
    """Pick the right strategy + concrete strikes + entry/exit triggers."""

    days = max(1, (expiry - date.today()).days)
    t = days / 365

    # ATM IV (avg CE + PE)
    if chain:
        atm_row = min(chain, key=lambda c: abs(c["strike"] - spot))
        iv_frac = ((atm_row.get("ce_iv", 0) + atm_row.get("pe_iv", 0)) / 2) / 100
    else:
        iv_frac = 0.20
    iv_frac = max(0.05, iv_frac)
    iv_pct = iv_frac * 100
    regime = _iv_regime(iv_pct)
    step = _strike_step_for(spot)
    atm = _round_to_strike_step(spot, step)

    legs: list[dict] = []
    strategy = "WAIT"
    subtype = "n/a"
    entry_triggers: list[str] = []
    exit_triggers: list[str] = []
    confidence_caveats: list[str] = []

    # --------------------------------------------------------------
    # Strategy selection — direction × confidence × IV regime
    # --------------------------------------------------------------
    if confidence < 55:
        strategy = "WAIT"
        subtype = "Confidence below 55% — no edge"
        confidence_caveats.append("Sub-55% confidence — preserving capital")

    elif direction == "BULLISH":
        if regime == "LOW":
            strategy = "CE_BUY"
            subtype = f"Naked ATM Call — IV {iv_pct:.1f}% is cheap"
            legs.append(_build_leg("BUY", "CE", atm, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = [
                f"Enter when CE delta crosses 0.55 (currently {legs[0]['delta']:.2f})",
                "OR enter on intraday breakout above today's high with volume",
                "Avoid entry in last 15 min before close (carry risk overnight)",
            ]
            exit_triggers = [
                "Target 1: when CE LTP rises 40% → book 50%",
                "Target 2: when CE LTP rises 80% → book remaining or trail",
                "Stop loss: underlying breaks below today's low OR CE LTP drops 30%",
                "Theta stop: if held overnight and tomorrow's IV crushes >20%, exit",
                f"Time stop: close all by {'15:25 today' if horizon == 'INTRADAY' else 'expiry-2 days'}",
            ]
        elif regime == "MID":
            strategy = "BULL_CALL_SPREAD"
            subtype = f"Bull-call spread — IV {iv_pct:.1f}% mid, cap cost"
            legs.append(_build_leg("BUY",  "CE", atm,        chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("SELL", "CE", atm + step, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = [
                "Enter as single combined order to lock in spread cost",
                f"Net debit ≈ {abs(legs[0]['ltp'] - legs[1]['ltp']) * lot_size:.0f} per lot",
            ]
            exit_triggers = [
                "Exit at 70% of max profit (don't chase the last rupee)",
                "Stop loss: underlying breaks 1.5×ATR below entry",
                "Time stop: close 3-5 days before expiry to avoid gamma blowup",
            ]
        else:                            # HIGH / VERY_HIGH IV
            strategy = "FUT_LONG_or_DEEP_ITM_CE"
            subtype = f"IV {iv_pct:.1f}% too rich — buy futures or deep-ITM CE instead"
            deep_itm = atm - 2 * step
            legs.append(_build_leg("BUY", "CE", deep_itm, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = [
                "Prefer FUT_LONG if margin available (cleaner delta, no theta)",
                "If using deep-ITM CE: delta should be >0.80 (acts like a stock)",
            ]
            exit_triggers = [
                "Target: 1.5×ATR move",
                "Stop loss: 1×ATR below entry",
                "Theta is low on deep-ITM but still real — exit 5d before expiry",
            ]

    elif direction == "BEARISH":
        if regime == "LOW":
            strategy = "PE_BUY"
            subtype = f"Naked ATM Put — IV {iv_pct:.1f}% is cheap"
            legs.append(_build_leg("BUY", "PE", atm, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = [
                f"Enter when PE delta crosses -0.55 (currently {legs[0]['delta']:.2f})",
                "OR enter on intraday breakdown below today's low",
            ]
            exit_triggers = [
                "Target 1: PE LTP +40% → book 50%",
                "Target 2: PE LTP +80% → trail or book",
                "Stop loss: underlying reclaims VWAP OR PE LTP drops 30%",
                "Time stop: close by EOD if intraday; expiry-2 if swing",
            ]
        elif regime == "MID":
            strategy = "BEAR_PUT_SPREAD"
            subtype = f"Bear-put spread — IV {iv_pct:.1f}% mid"
            legs.append(_build_leg("BUY",  "PE", atm,        chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("SELL", "PE", atm - step, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = [
                "Enter as single combined order to lock spread cost",
                f"Net debit ≈ {abs(legs[0]['ltp'] - legs[1]['ltp']) * lot_size:.0f} per lot",
            ]
            exit_triggers = [
                "Exit at 70% of max profit",
                "Stop loss: underlying reclaims 1.5×ATR above entry",
            ]
        else:                            # HIGH IV
            strategy = "FUT_SHORT"
            subtype = f"IV {iv_pct:.1f}% rich — futures short cleaner than puts"
            entry_triggers = ["Place futures short with hard SL"]
            exit_triggers = ["Target 1.5×ATR; SL 1×ATR above; trail in 0.5×ATR steps"]

    else:                                # NEUTRAL / SIDEWAYS
        if regime == "VERY_HIGH":
            strategy = "SHORT_STRANGLE"
            subtype = f"IV {iv_pct:.1f}% very rich — strangle harvest"
            legs.append(_build_leg("SELL", "CE", atm + 2 * step, chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("SELL", "PE", atm - 2 * step, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = ["Enter only with explicit SL alerts — undefined risk"]
            exit_triggers = [
                "Exit at 50% of max profit (theta-decay capture is non-linear)",
                "Stop loss: when underlying touches either short strike",
                "Roll the threatened side ONE TIME if needed; otherwise exit",
            ]
        elif regime == "HIGH":
            strategy = "IRON_CONDOR"
            subtype = f"Iron condor — IV {iv_pct:.1f}% rich, defined wings"
            legs.append(_build_leg("SELL", "CE", atm + step,     chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("BUY",  "CE", atm + 2 * step, chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("SELL", "PE", atm - step,     chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("BUY",  "PE", atm - 2 * step, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = ["Enter all 4 legs as single combo order"]
            exit_triggers = [
                "Exit at 50% of max profit",
                "Stop loss: when underlying breaches a short strike",
                "Roll inner short OR exit",
            ]
        elif regime == "LOW":
            strategy = "LONG_STRADDLE"
            subtype = f"IV {iv_pct:.1f}% compressed — vol-expansion straddle"
            legs.append(_build_leg("BUY", "CE", atm, chain, spot, t, risk_free, iv_frac, lot_size))
            legs.append(_build_leg("BUY", "PE", atm, chain, spot, t, risk_free, iv_frac, lot_size))
            entry_triggers = ["Enter before known event/breakout setup"]
            exit_triggers = [
                "Target: net premium grows 50% (vol expanded)",
                "Stop: if IV stays flat for 2 sessions, theta is winning — exit",
            ]
        else:
            strategy = "WAIT"
            subtype = "Neutral + mid IV — no edge"
            confidence_caveats.append("Sideways direction in mid-IV regime — no premium edge either way")

    # --------------------------------------------------------------
    # P&L envelope + portfolio greeks
    # --------------------------------------------------------------
    net_premium = sum(
        (-1 if leg["action"] == "BUY" else 1) * leg["premium_per_lot_inr"]
        for leg in legs
    )                                                  # negative = debit
    port_delta = sum((1 if leg["action"] == "BUY" else -1) * leg["delta"] * leg["lot_size"] for leg in legs)
    port_gamma = sum((1 if leg["action"] == "BUY" else -1) * leg["gamma"] * leg["lot_size"] for leg in legs)
    port_theta = sum((1 if leg["action"] == "BUY" else -1) * leg["theta"] * leg["lot_size"] for leg in legs)
    port_vega  = sum((1 if leg["action"] == "BUY" else -1) * leg["vega"]  * leg["lot_size"] for leg in legs)

    max_profit, max_loss, breakevens = _pnl_envelope(strategy, legs, net_premium, spot, step)

    rr = (max_profit / abs(max_loss)) if max_loss not in (None, 0) else 0.0

    # Sizing
    if strategy == "WAIT":
        lots = 0; cap_inr = 0.0; margin = 0.0
    else:
        max_alloc_pct = min(5.0, (confidence - 50) / 10)
        cap_budget = capital * max_alloc_pct / 100
        per_lot_cost = abs(net_premium) if net_premium < 0 else max(abs(net_premium), 1000)
        lots = max(1, int(cap_budget // per_lot_cost)) if per_lot_cost > 0 else 0
        cap_inr = round(lots * per_lot_cost, 2)
        # Rough margin estimate for short-premium strategies
        margin = round(spot * lot_size * lots * 0.15, 2) if any(l["action"] == "SELL" for l in legs) else None

    intraday_notes = []
    if horizon == "INTRADAY":
        intraday_notes.extend([
            f"Intraday: square off by 15:20 (NSE auto-square at 15:25)",
            f"Net theta drag/day = ₹{port_theta * lots * lot_size:.2f} — if held overnight",
            f"Gamma exposure = {port_gamma * lots * lot_size:.4f} per ₹1 spot move",
        ])

    confidence_caveats.append(
        f"Strategy assumes chain greeks remain stable — re-verify deltas before entry"
    )

    return OptionsTradePlan(
        symbol=symbol,
        spot=spot,
        direction=direction,
        confidence=round(confidence, 2),
        expiry=expiry.isoformat(),
        days_to_expiry=days,
        iv_pct=round(iv_pct, 2),
        iv_regime=regime,
        strategy=strategy,
        strategy_subtype=subtype,
        legs=legs,
        net_premium_inr=round(net_premium * lots, 2),
        max_profit_inr=round(max_profit * lots, 2) if max_profit is not None else 0,
        max_loss_inr=round(max_loss * lots, 2) if max_loss is not None else 0,
        breakeven_prices=breakevens,
        risk_reward=round(rr, 3),
        suggested_lots=lots,
        suggested_capital_inr=cap_inr,
        margin_required_inr=margin,
        entry_triggers=entry_triggers,
        exit_triggers=exit_triggers,
        portfolio_greeks={
            "net_delta": round(port_delta * lots, 4),
            "net_gamma": round(port_gamma * lots, 6),
            "net_theta_per_day": round(port_theta * lots * lot_size, 2),
            "net_vega":  round(port_vega  * lots * lot_size, 2),
        },
        intraday_notes=intraday_notes,
        confidence_caveats=confidence_caveats,
    )


# ---------------------------------------------------------------------------
# P&L envelope per strategy
# ---------------------------------------------------------------------------

def _pnl_envelope(strategy: str, legs: list[dict], net_prem: float,
                   spot: float, step: float) -> tuple[float, float, list[float]]:
    """Returns (max_profit_per_lot, max_loss_per_lot, breakeven_prices)."""
    if not legs:
        return 0, 0, []

    if strategy == "CE_BUY":
        ltp = legs[0]["ltp"]; k = legs[0]["strike"]; ls = legs[0]["lot_size"]
        return (float("inf"), -ltp * ls, [k + ltp])
    if strategy == "PE_BUY":
        ltp = legs[0]["ltp"]; k = legs[0]["strike"]; ls = legs[0]["lot_size"]
        return (k * ls, -ltp * ls, [k - ltp])
    if strategy == "BULL_CALL_SPREAD":
        debit = abs(net_prem)
        spread = abs(legs[1]["strike"] - legs[0]["strike"]) * legs[0]["lot_size"]
        return (spread - debit, -debit, [legs[0]["strike"] + debit / legs[0]["lot_size"]])
    if strategy == "BEAR_PUT_SPREAD":
        debit = abs(net_prem)
        spread = abs(legs[0]["strike"] - legs[1]["strike"]) * legs[0]["lot_size"]
        return (spread - debit, -debit, [legs[0]["strike"] - debit / legs[0]["lot_size"]])
    if strategy == "IRON_CONDOR":
        credit = net_prem                          # positive — collected premium
        wing_width = abs(legs[1]["strike"] - legs[0]["strike"]) * legs[0]["lot_size"]
        return (credit, -(wing_width - credit), [
            legs[0]["strike"] + credit / legs[0]["lot_size"],
            legs[2]["strike"] - credit / legs[2]["lot_size"],
        ])
    if strategy == "LONG_STRADDLE":
        debit = abs(net_prem)
        k = legs[0]["strike"]; ls = legs[0]["lot_size"]
        return (float("inf"), -debit, [k - debit / ls, k + debit / ls])
    if strategy == "SHORT_STRANGLE":
        credit = net_prem
        return (credit, float("-inf"), [
            legs[0]["strike"] + credit / legs[0]["lot_size"],
            legs[1]["strike"] - credit / legs[1]["lot_size"],
        ])
    return 0, 0, []
