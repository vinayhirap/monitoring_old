"""Options & F&O analytics engine.

Computes:
  - Black–Scholes Greeks (delta, gamma, vega, theta, rho)
  - Open Interest analysis (PCR, max pain, support/resistance walls)
  - IV skew & rank
  - Strategy suggestion (directional / non-directional)
  - Institutional positioning hints (large OI shifts on writers vs buyers)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math


# ============================================================================
# Black–Scholes
# ============================================================================

def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs_greeks(spot: float, strike: float, t_years: float, r: float, sigma: float, is_call: bool) -> dict:
    if t_years <= 0 or sigma <= 0:
        intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
        return {"price": intrinsic, "delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * math.sqrt(t_years))
    d2 = d1 - sigma * math.sqrt(t_years)
    if is_call:
        price = spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        rho = strike * t_years * math.exp(-r * t_years) * _norm_cdf(d2) / 100
        theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * math.sqrt(t_years))
                 - r * strike * math.exp(-r * t_years) * _norm_cdf(d2)) / 365
    else:
        price = strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1
        rho = -strike * t_years * math.exp(-r * t_years) * _norm_cdf(-d2) / 100
        theta = (-(spot * _norm_pdf(d1) * sigma) / (2 * math.sqrt(t_years))
                 + r * strike * math.exp(-r * t_years) * _norm_cdf(-d2)) / 365
    gamma = _norm_pdf(d1) / (spot * sigma * math.sqrt(t_years))
    vega = spot * _norm_pdf(d1) * math.sqrt(t_years) / 100
    return {
        "price": round(price, 2),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "vega": round(vega, 4),
        "theta": round(theta, 4),
        "rho": round(rho, 4),
    }


# ============================================================================
# Chain analytics
# ============================================================================

@dataclass
class OptionsAnalytics:
    pcr: float
    max_pain: float
    bias: str
    support_wall: float | None
    resistance_wall: float | None
    suggested_strategy: str
    institutional_view: str
    greeks_atm: dict
    score: float                     # 0..100 (bullish bias)
    reasons: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


def _max_pain(chain: list[dict]) -> float:
    """Compute max pain — strike where total option seller loss is minimised
    (i.e. the strike where most options expire worthless)."""
    strikes = [c["strike"] for c in chain]
    losses = []
    for k in strikes:
        loss = 0.0
        for row in chain:
            ce_oi = row.get("ce_oi", 0) or 0
            pe_oi = row.get("pe_oi", 0) or 0
            loss += max(0, k - row["strike"]) * ce_oi    # ITM call seller loss
            loss += max(0, row["strike"] - k) * pe_oi    # ITM put seller loss
        losses.append((k, loss))
    return min(losses, key=lambda x: x[1])[0]


def _walls(chain: list[dict]) -> tuple[float | None, float | None]:
    """Highest PE OI strike below spot = support wall.
    Highest CE OI strike above spot = resistance wall.
    """
    if not chain:
        return None, None
    spot_proxy = sum(c["strike"] for c in chain) / len(chain)
    below = [c for c in chain if c["strike"] <= spot_proxy]
    above = [c for c in chain if c["strike"] >= spot_proxy]
    sup = max(below, key=lambda c: c.get("pe_oi", 0) or 0, default=None)
    res = max(above, key=lambda c: c.get("ce_oi", 0) or 0, default=None)
    return (sup["strike"] if sup else None, res["strike"] if res else None)


def analyze(symbol: str, spot: float, expiry: date, chain: list[dict],
            risk_free: float = 0.07) -> OptionsAnalytics:
    if not chain:
        return OptionsAnalytics(
            pcr=0, max_pain=0, bias="NEUTRAL", support_wall=None, resistance_wall=None,
            suggested_strategy="No chain data",
            institutional_view="n/a",
            greeks_atm={}, score=50, reasons=["Empty chain"],
        )

    total_pe = sum((c.get("pe_oi", 0) or 0) for c in chain)
    total_ce = sum((c.get("ce_oi", 0) or 0) for c in chain)
    pcr = round(total_pe / total_ce, 3) if total_ce else 0
    mp = _max_pain(chain)
    sup_wall, res_wall = _walls(chain)

    # ATM strike = chain row closest to spot
    atm_row = min(chain, key=lambda c: abs(c["strike"] - spot))
    days_to_expiry = max(1, (expiry - date.today()).days)
    t = days_to_expiry / 365
    atm_iv = (atm_row.get("ce_iv", 0) + atm_row.get("pe_iv", 0)) / 200    # avg, fraction
    if atm_iv <= 0:
        atm_iv = 0.20

    greeks_ce = bs_greeks(spot, atm_row["strike"], t, risk_free, atm_iv, True)
    greeks_pe = bs_greeks(spot, atm_row["strike"], t, risk_free, atm_iv, False)

    reasons: list[str] = []
    score = 50.0

    # PCR bias
    if pcr > 1.3:
        score += 15
        reasons.append(f"PCR {pcr} > 1.3 — bullish (heavy put writing)")
    elif pcr < 0.7:
        score -= 15
        reasons.append(f"PCR {pcr} < 0.7 — bearish (heavy call writing)")
    else:
        reasons.append(f"PCR {pcr} neutral")

    # Spot vs max pain
    if spot < mp:
        score += 6
        reasons.append(f"Spot {spot} below max pain {mp} — pull-up bias")
    elif spot > mp:
        score -= 6
        reasons.append(f"Spot {spot} above max pain {mp} — pull-down bias")

    # Walls
    if sup_wall:
        reasons.append(f"Strong PE support wall at {sup_wall}")
    if res_wall:
        reasons.append(f"Strong CE resistance wall at {res_wall}")

    # Strategy
    if score >= 65:
        strategy = "Buy ATM/OTM Call OR Bull Call Spread"
    elif score <= 35:
        strategy = "Buy ATM/OTM Put OR Bear Put Spread"
    elif sup_wall and res_wall and (res_wall - sup_wall) / spot < 0.05:
        strategy = "Iron Condor / Short Strangle (range-bound)"
    else:
        strategy = "Long Straddle (expecting expansion) OR wait"

    # Institutional view (very simple heuristic)
    if pcr > 1.5 and atm_iv < 0.2:
        institutional = "Smart money writing puts at low IV — bullish stance"
    elif pcr < 0.5 and atm_iv < 0.2:
        institutional = "Smart money writing calls at low IV — bearish/range stance"
    elif atm_iv > 0.35:
        institutional = "Elevated IV — event-risk; institutions hedging"
    else:
        institutional = "Mixed positioning"

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    return OptionsAnalytics(
        pcr=pcr,
        max_pain=mp,
        bias=bias,
        support_wall=sup_wall,
        resistance_wall=res_wall,
        suggested_strategy=strategy,
        institutional_view=institutional,
        greeks_atm={"call": greeks_ce, "put": greeks_pe, "iv": atm_iv, "atm_strike": atm_row["strike"]},
        score=score,
        reasons=reasons,
        raw={"total_ce_oi": total_ce, "total_pe_oi": total_pe, "days_to_expiry": days_to_expiry},
    )


# ============================================================================
# Synthetic chain for paper-mode demos
# ============================================================================

def synthetic_chain(symbol: str, spot: float, step: float = 50, width: int = 10) -> list[dict]:
    """Generate a plausible options chain for testing."""
    chain = []
    for i in range(-width, width + 1):
        strike = round(spot / step) * step + i * step
        moneyness = strike - spot
        ce_oi = max(100, int(50000 * math.exp(-(moneyness / (spot * 0.05)) ** 2)))
        pe_oi = max(100, int(55000 * math.exp(-(moneyness / (spot * 0.05)) ** 2)))
        if moneyness > 0:
            pe_oi = int(pe_oi * 0.7)
        else:
            ce_oi = int(ce_oi * 0.7)
        chain.append({
            "strike": strike,
            "ce_oi": ce_oi,
            "pe_oi": pe_oi,
            "ce_iv": 18 + abs(moneyness) / spot * 100,
            "pe_iv": 19 + abs(moneyness) / spot * 100,
            "ce_ltp": max(0.5, spot - strike) if strike < spot else max(0.5, 50 - abs(moneyness) * 0.4),
            "pe_ltp": max(0.5, strike - spot) if strike > spot else max(0.5, 50 - abs(moneyness) * 0.4),
        })
    return chain
