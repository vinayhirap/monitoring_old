"""Professional risk analytics — the "Aladdin half" of the platform.

Implements the standard institutional risk measures:

  • Historical VaR (simulation method)        — quantile of past returns
  • Parametric VaR (variance-covariance)      — assumes normality
  • Monte Carlo VaR                           — geometric Brownian motion sims
  • Expected Shortfall / CVaR                 — average loss beyond VaR
  • Max Drawdown projection                   — over a horizon
  • Stress-test scenarios                     — applies historical or hypothetical shocks
  • Portfolio aggregation                     — VaR across positions with correlation

Returns are expected as daily log-returns. Confidence is the *level* (0.95 →
5% worst-case). All outputs are in the same currency unit as `position_value`.

Disclaimer: VaR/ES on instruments with non-normal returns (i.e. most equities)
can understate fat-tail risk. Treat outputs as a floor, not a ceiling, on
plausible loss.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal
import math

import numpy as np


# ---------------------------------------------------------------------------
# Single-position risk
# ---------------------------------------------------------------------------

@dataclass
class RiskSummary:
    position_value: float
    horizon_days: int
    confidence: float
    var_historical: float
    var_parametric: float
    var_monte_carlo: float
    expected_shortfall: float
    expected_shortfall_pct: float
    max_drawdown_estimate: float
    annualised_vol_pct: float
    sharpe_estimate: float | None
    sortino_estimate: float | None
    method_notes: list[str] = field(default_factory=list)
    disclaimer: str = (
        "VaR/ES assume return distribution shape continues. Fat-tail events "
        "(2008, COVID, flash crashes) historically exceed parametric VaR by "
        "3-10x. Use as a floor on plausible loss, never as a hard ceiling."
    )

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    """VaR via empirical quantile of past returns. confidence=0.95 → 5% tail."""
    if returns.size == 0:
        return 0.0
    q = np.percentile(returns, (1 - confidence) * 100)
    return float(-q)                  # express as positive loss fraction


def parametric_var(returns: np.ndarray, confidence: float = 0.95,
                    horizon_days: int = 1) -> float:
    """Variance-covariance VaR assuming returns ~ N(μ, σ²)."""
    if returns.size == 0:
        return 0.0
    mu = float(np.mean(returns))
    sigma = float(np.std(returns))
    # Normal-inverse: 95% → 1.645, 99% → 2.326 etc.
    from math import sqrt
    from statistics import NormalDist
    z = NormalDist().inv_cdf(1 - confidence)
    var_1d = -(mu + z * sigma)        # loss is positive
    return float(var_1d * sqrt(horizon_days))


def monte_carlo_var(returns: np.ndarray, confidence: float = 0.95,
                    horizon_days: int = 1, n_sims: int = 10_000,
                    seed: int | None = 42) -> float:
    """GBM simulation. Draws daily returns from observed μ/σ, compounds for
    horizon_days, returns the (1-confidence) quantile."""
    if returns.size == 0:
        return 0.0
    rng = np.random.default_rng(seed)
    mu = float(np.mean(returns))
    sigma = float(np.std(returns))
    # Daily shocks then sum (log space) — i.e. compounded over horizon
    shocks = rng.normal(loc=mu, scale=sigma, size=(n_sims, horizon_days))
    horizon_returns = shocks.sum(axis=1)
    q = np.percentile(horizon_returns, (1 - confidence) * 100)
    return float(-q)


def expected_shortfall(returns: np.ndarray, confidence: float = 0.95) -> tuple[float, float]:
    """CVaR — the mean of returns beyond the VaR cutoff.
    Returns (es_fraction, es_pct_of_var)."""
    if returns.size == 0:
        return 0.0, 0.0
    cutoff = np.percentile(returns, (1 - confidence) * 100)
    tail = returns[returns <= cutoff]
    if tail.size == 0:
        return 0.0, 0.0
    es = float(-tail.mean())
    var = float(-cutoff)
    ratio = es / var if var > 0 else 1.0
    return es, ratio


def max_drawdown_estimate(returns: np.ndarray, horizon_days: int = 252,
                          n_sims: int = 2_000, seed: int | None = 42) -> float:
    """Monte Carlo max-DD estimate over horizon_days. Returns the *median*
    max-DD across n_sims paths.
    """
    if returns.size == 0:
        return 0.0
    rng = np.random.default_rng(seed)
    mu = float(np.mean(returns))
    sigma = float(np.std(returns))
    shocks = rng.normal(loc=mu, scale=sigma, size=(n_sims, horizon_days))
    paths = np.cumsum(shocks, axis=1)
    cum_max = np.maximum.accumulate(paths, axis=1)
    drawdowns = paths - cum_max
    max_dd_per_sim = drawdowns.min(axis=1)
    return float(-np.median(max_dd_per_sim))


def analyse_position(returns_pct: list[float] | np.ndarray,
                      position_value: float,
                      confidence: float = 0.95,
                      horizon_days: int = 1) -> RiskSummary:
    """Full risk summary for a single position. `returns_pct` is daily-pct
    returns history (NOT log; e.g. 0.012 for +1.2%)."""
    arr = np.asarray(returns_pct, dtype=float).flatten()
    if arr.size < 30:
        # Too little history — fall back to placeholder
        return RiskSummary(
            position_value=position_value, horizon_days=horizon_days,
            confidence=confidence, var_historical=0, var_parametric=0,
            var_monte_carlo=0, expected_shortfall=0, expected_shortfall_pct=0,
            max_drawdown_estimate=0, annualised_vol_pct=0,
            sharpe_estimate=None, sortino_estimate=None,
            method_notes=["Less than 30 return observations — risk estimates unreliable"],
        )

    h_var = historical_var(arr, confidence)
    p_var = parametric_var(arr, confidence, horizon_days)
    m_var = monte_carlo_var(arr, confidence, horizon_days)
    es, es_pct_of_var = expected_shortfall(arr, confidence)
    mdd = max_drawdown_estimate(arr, horizon_days=252)
    ann_vol = float(np.std(arr) * math.sqrt(252)) * 100

    daily_mu = float(np.mean(arr))
    ann_return = daily_mu * 252
    sharpe = (ann_return / (np.std(arr) * math.sqrt(252))) if np.std(arr) > 0 else None
    downside = arr[arr < 0]
    sortino = None
    if downside.size > 0 and np.std(downside) > 0:
        sortino = ann_return / (float(np.std(downside)) * math.sqrt(252))

    return RiskSummary(
        position_value=position_value,
        horizon_days=horizon_days,
        confidence=confidence,
        var_historical=h_var * position_value * math.sqrt(horizon_days),
        var_parametric=p_var * position_value,
        var_monte_carlo=m_var * position_value,
        expected_shortfall=es * position_value,
        expected_shortfall_pct=es * 100,
        max_drawdown_estimate=mdd * position_value,
        annualised_vol_pct=ann_vol,
        sharpe_estimate=round(sharpe, 3) if sharpe is not None else None,
        sortino_estimate=round(sortino, 3) if sortino is not None else None,
        method_notes=[
            f"Based on {arr.size} return observations",
            "Three VaR methods reported — divergence > 30% means non-normal distribution",
        ],
    )


# ---------------------------------------------------------------------------
# Portfolio aggregation — correlated VaR
# ---------------------------------------------------------------------------

@dataclass
class PortfolioRisk:
    total_value: float
    portfolio_var_95: float
    portfolio_var_99: float
    portfolio_es_95: float
    diversification_benefit_pct: float
    concentration_top1_pct: float
    concentration_top3_pct: float
    component_vars: list[dict]
    correlation_matrix: list[list[float]]
    method_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def portfolio_risk(positions: list[dict]) -> PortfolioRisk:
    """positions = [{symbol, value, returns_pct: [...]}]

    Returns aggregate VaR using parametric variance-covariance method:
        portfolio_var = sqrt(w' · Σ · w) · z_alpha
    """
    if not positions:
        return PortfolioRisk(0, 0, 0, 0, 0, 0, 0, [], [], ["Empty portfolio"])

    valid = [p for p in positions if len(p.get("returns_pct", []) or []) >= 30]
    if not valid:
        return PortfolioRisk(
            total_value=sum(p["value"] for p in positions),
            portfolio_var_95=0, portfolio_var_99=0, portfolio_es_95=0,
            diversification_benefit_pct=0,
            concentration_top1_pct=0, concentration_top3_pct=0,
            component_vars=[], correlation_matrix=[],
            method_notes=["No position has ≥30 returns — cannot compute portfolio risk"],
        )

    # Align returns length to minimum
    min_len = min(len(p["returns_pct"]) for p in valid)
    R = np.array([list(p["returns_pct"])[-min_len:] for p in valid], dtype=float)
    values = np.array([p["value"] for p in valid], dtype=float)
    total = float(values.sum())
    weights = values / total

    cov = np.cov(R)                                # K x K
    if cov.ndim == 0:                              # single-asset portfolio
        cov = np.array([[float(cov)]])
    port_var = float(np.sqrt(weights @ cov @ weights))   # daily σ of portfolio return

    from statistics import NormalDist
    z95 = -NormalDist().inv_cdf(0.05)
    z99 = -NormalDist().inv_cdf(0.01)

    port_var_95 = port_var * z95 * total
    port_var_99 = port_var * z99 * total
    port_es_95  = port_var * 2.063 * total          # ES95 of normal ≈ 2.063σ

    # Sum of standalone VaRs
    standalone_vars = []
    for i, p in enumerate(valid):
        sd = float(np.std(R[i]))
        standalone = sd * z95 * values[i]
        standalone_vars.append({
            "symbol": p["symbol"],
            "value": float(values[i]),
            "weight_pct": float(weights[i] * 100),
            "standalone_var_95": float(standalone),
        })
    sum_standalone = sum(c["standalone_var_95"] for c in standalone_vars)
    diversification = (1 - port_var_95 / sum_standalone) * 100 if sum_standalone > 0 else 0

    sorted_weights = sorted(weights, reverse=True)
    top1 = sorted_weights[0] * 100
    top3 = sum(sorted_weights[:3]) * 100

    # Correlation matrix
    if len(valid) > 1:
        std = np.std(R, axis=1, ddof=0)
        std[std == 0] = 1e-9
        corr = cov / np.outer(std, std)
        corr_list = corr.tolist()
    else:
        corr_list = [[1.0]]

    return PortfolioRisk(
        total_value=total,
        portfolio_var_95=port_var_95,
        portfolio_var_99=port_var_99,
        portfolio_es_95=port_es_95,
        diversification_benefit_pct=float(diversification),
        concentration_top1_pct=float(top1),
        concentration_top3_pct=float(top3),
        component_vars=standalone_vars,
        correlation_matrix=corr_list,
        method_notes=[
            "Parametric portfolio VaR — assumes joint-normal returns",
            "Diversification benefit = 1 - portfolio_var / sum(standalone_vars)",
        ],
    )


# ---------------------------------------------------------------------------
# Stress test scenarios
# ---------------------------------------------------------------------------

# Historical worst-cases — daily % shocks
STRESS_SCENARIOS: dict[str, dict] = {
    "BLACK_MONDAY_1987":   {"equity": -22.6, "vol_spike": +20.0, "narrative": "Oct 19 1987: DJIA -22.6% in one day"},
    "LTCM_1998":           {"equity":  -7.0, "vol_spike": +15.0, "narrative": "Aug 1998: LTCM unwind, EM contagion"},
    "DOT_COM_BUST_2000":   {"equity": -10.0, "vol_spike":  +8.0, "narrative": "Apr 2000: Nasdaq peak-to-trough rapid decline"},
    "LEHMAN_2008":         {"equity":  -9.0, "vol_spike": +25.0, "narrative": "Sep 15 2008: Lehman bankruptcy, credit freeze"},
    "FLASH_CRASH_2010":    {"equity":  -9.0, "vol_spike": +30.0, "narrative": "May 6 2010: 36-min flash crash + recovery"},
    "TAPER_TANTRUM_2013":  {"equity":  -5.0, "vol_spike": +10.0, "narrative": "May 22 2013: Fed taper signalled, EM equities sold"},
    "VOLMAGEDDON_2018":    {"equity":  -4.5, "vol_spike": +95.0, "narrative": "Feb 5 2018: XIV blow-up, vol-of-vol spike"},
    "COVID_CRASH_2020":    {"equity": -12.0, "vol_spike": +60.0, "narrative": "Mar 16 2020: COVID lockdowns, fastest bear market"},
    "INDIA_DEMONETIZATION_2016": {"equity": -6.0, "vol_spike": +12.0, "narrative": "Nov 8 2016: ₹500/₹1000 notes invalidated overnight"},
}


def stress_test(positions: list[dict],
                scenarios: list[str] | None = None) -> dict:
    """Apply historical stress scenarios to current positions.
    positions = [{symbol, value, beta?}]
    """
    scenarios = scenarios or list(STRESS_SCENARIOS.keys())
    out = {"asof": date.today().isoformat(), "results": []}
    for sc_name in scenarios:
        sc = STRESS_SCENARIOS.get(sc_name)
        if not sc:
            continue
        equity_shock = sc["equity"] / 100
        total_pnl = 0.0
        components = []
        for p in positions:
            beta = float(p.get("beta", 1.0))
            value = float(p["value"])
            pnl = value * equity_shock * beta
            total_pnl += pnl
            components.append({
                "symbol": p["symbol"],
                "value": value,
                "beta": beta,
                "pnl_inr": round(pnl, 2),
                "pnl_pct": round(equity_shock * beta * 100, 4),
            })
        total_value = sum(p["value"] for p in positions) or 1
        out["results"].append({
            "scenario": sc_name,
            "narrative": sc["narrative"],
            "equity_shock_pct": sc["equity"],
            "vol_spike_pct": sc["vol_spike"],
            "portfolio_pnl_inr": round(total_pnl, 2),
            "portfolio_pnl_pct": round(total_pnl / total_value * 100, 4),
            "components": components,
        })
    out["worst_case"] = min(out["results"], key=lambda r: r["portfolio_pnl_inr"]) if out["results"] else None
    return out
