"""Portfolio optimizer — three institutional methods.

  • Mean-Variance (Markowitz)  — maximise return for a given risk, or
                                  minimise risk for a given return
  • Risk Parity                 — equal risk contribution from each position
                                  (no return forecast needed — robust)
  • Black-Litterman             — Bayesian blend of equilibrium-implied returns
                                  with the user's "views" (expected returns +
                                  confidence) — what BlackRock-style platforms
                                  use to incorporate analyst opinion cleanly

Uses CVXPY when available (proper disciplined convex programming); falls
back to closed-form/numerical solutions when not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import numpy as np
from loguru import logger

try:
    import cvxpy as cp
    HAS_CVXPY = True
except ImportError:
    HAS_CVXPY = False


@dataclass
class OptimisationResult:
    method: str
    weights: dict                       # {symbol: weight_pct}
    expected_return_pct: float
    expected_vol_pct: float
    expected_sharpe: float
    risk_contributions: dict            # {symbol: pct_of_portfolio_risk}
    constraints_applied: list[str]
    objective_value: float | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _annualise_returns(daily_returns: np.ndarray) -> np.ndarray:
    return np.mean(daily_returns, axis=1) * 252


def _annualise_cov(daily_returns: np.ndarray) -> np.ndarray:
    return np.cov(daily_returns) * 252


# ---------------------------------------------------------------------------
# Mean-Variance — maximise Sharpe under constraints
# ---------------------------------------------------------------------------

def mean_variance(
    symbols: list[str],
    daily_returns: np.ndarray,           # shape (n_assets, n_days)
    rf_annual: float = 0.065,
    max_weight: float = 0.30,
    min_weight: float = 0.00,
    target_return: float | None = None,
) -> OptimisationResult:
    n = len(symbols)
    if daily_returns.shape[0] != n:
        raise ValueError("daily_returns must have one row per symbol")

    mu = _annualise_returns(daily_returns)
    sigma = _annualise_cov(daily_returns)

    if HAS_CVXPY:
        w = cp.Variable(n)
        ret = mu @ w
        risk = cp.quad_form(w, cp.psd_wrap(sigma))
        constraints = [cp.sum(w) == 1, w >= min_weight, w <= max_weight]
        if target_return is not None:
            constraints.append(ret >= target_return)
            prob = cp.Problem(cp.Minimize(risk), constraints)
        else:
            # Maximise Sharpe = maximise mu·w - rf  s.t. sqrt(w'Σw) bound
            prob = cp.Problem(cp.Maximize(ret - 0.5 * risk), constraints)
        prob.solve()
        weights = w.value
        if weights is None:
            return _equal_weight(symbols, mu, sigma, "MEAN_VARIANCE — solver failed, fell back to equal-weight")
        weights = np.maximum(weights, 0)
        weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n
    else:
        # Closed-form mean-variance with no shorting — fallback
        try:
            inv_sigma = np.linalg.pinv(sigma)
            ones = np.ones(n)
            weights = inv_sigma @ ones
            weights = np.maximum(weights, 0)
            weights = weights / weights.sum() if weights.sum() > 0 else np.ones(n) / n
            weights = np.minimum(weights, max_weight)
            weights = weights / weights.sum()
        except Exception:
            weights = np.ones(n) / n

    return _build_result("MEAN_VARIANCE", symbols, weights, mu, sigma, rf_annual,
                          constraints=[f"sum=1", f"min={min_weight}", f"max={max_weight}"])


# ---------------------------------------------------------------------------
# Risk Parity — equal risk contribution
# ---------------------------------------------------------------------------

def risk_parity(
    symbols: list[str],
    daily_returns: np.ndarray,
    rf_annual: float = 0.065,
    max_weight: float = 0.40,
) -> OptimisationResult:
    n = len(symbols)
    sigma = _annualise_cov(daily_returns)
    mu = _annualise_returns(daily_returns)

    # Iterative Newton — minimise ||risk_contrib - 1/n||²
    weights = np.ones(n) / n
    for _ in range(200):
        port_vol = math.sqrt(weights @ sigma @ weights)
        if port_vol == 0:
            break
        mrc = sigma @ weights / port_vol           # marginal risk contribution
        rc = weights * mrc                          # absolute RC
        target = port_vol / n
        # Newton step
        grad = rc - target
        weights = weights - 0.01 * grad
        weights = np.maximum(weights, 1e-6)
        weights = weights / weights.sum()
        if np.max(np.abs(grad)) < 1e-6:
            break

    weights = np.minimum(weights, max_weight)
    weights = weights / weights.sum()

    return _build_result("RISK_PARITY", symbols, weights, mu, sigma, rf_annual,
                          constraints=[f"sum=1", f"max={max_weight}", "equal-risk-contrib"])


# ---------------------------------------------------------------------------
# Black-Litterman — Bayesian blend
# ---------------------------------------------------------------------------

def black_litterman(
    symbols: list[str],
    daily_returns: np.ndarray,
    market_caps: list[float] | None = None,
    views: dict | None = None,           # {symbol: expected_annual_return_pct}
    view_confidences: dict | None = None,  # {symbol: confidence 0..1}
    risk_aversion: float = 2.5,
    tau: float = 0.05,                    # uncertainty in prior
    rf_annual: float = 0.065,
) -> OptimisationResult:
    n = len(symbols)
    sigma = _annualise_cov(daily_returns)

    # Equilibrium weights from market caps (or equal weight if not given)
    if market_caps and len(market_caps) == n and sum(market_caps) > 0:
        w_eq = np.array(market_caps) / sum(market_caps)
    else:
        w_eq = np.ones(n) / n

    # Implied equilibrium returns: π = λ·Σ·w_eq
    pi = risk_aversion * sigma @ w_eq

    # If no views, just return equilibrium
    if not views:
        weights = w_eq
        mu_post = pi
    else:
        # Build pick matrix P + view vector q + view-uncertainty Ω
        view_items = [(symbols.index(s), r) for s, r in views.items() if s in symbols]
        k = len(view_items)
        if k == 0:
            weights = w_eq
            mu_post = pi
        else:
            P = np.zeros((k, n))
            q = np.zeros(k)
            omega_diag = []
            for i, (idx, ret) in enumerate(view_items):
                P[i, idx] = 1.0
                q[i] = ret / 100                            # convert pct → frac
                conf = (view_confidences or {}).get(symbols[idx], 0.5)
                conf = max(0.01, min(0.99, conf))
                # higher confidence → lower variance
                omega_diag.append((1 - conf) / conf * float(P[i] @ sigma @ P[i].T))
            omega = np.diag(omega_diag)
            # Posterior mean (Black-Litterman closed form)
            inv_tau_sigma = np.linalg.pinv(tau * sigma)
            inv_omega = np.linalg.pinv(omega + 1e-9 * np.eye(k))
            A = inv_tau_sigma + P.T @ inv_omega @ P
            B = inv_tau_sigma @ pi + P.T @ inv_omega @ q
            mu_post = np.linalg.pinv(A) @ B

            # Optimal weights: w* = (λ Σ)^-1 · μ_post
            weights = np.linalg.pinv(risk_aversion * sigma) @ mu_post
            weights = np.maximum(weights, 0)
            weights = weights / weights.sum() if weights.sum() > 0 else w_eq

    return _build_result("BLACK_LITTERMAN", symbols, weights, mu_post, sigma, rf_annual,
                          constraints=[f"risk_aversion={risk_aversion}", f"tau={tau}",
                                        f"{len(views or {})} views applied"])


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _build_result(method: str, symbols: list[str], weights: np.ndarray,
                   mu: np.ndarray, sigma: np.ndarray, rf_annual: float,
                   constraints: list[str]) -> OptimisationResult:
    port_ret = float(mu @ weights * 100)
    port_var = float(weights @ sigma @ weights)
    port_vol = math.sqrt(port_var) * 100
    sharpe = (port_ret / 100 - rf_annual) / (port_vol / 100) if port_vol > 0 else 0

    # Risk contributions
    mrc = sigma @ weights
    rc = weights * mrc
    total_rc = rc.sum() if rc.sum() != 0 else 1
    risk_contrib = {sym: round(float(rc[i] / total_rc * 100), 3) for i, sym in enumerate(symbols)}

    weights_dict = {sym: round(float(weights[i] * 100), 3) for i, sym in enumerate(symbols)}

    return OptimisationResult(
        method=method,
        weights=weights_dict,
        expected_return_pct=round(port_ret, 3),
        expected_vol_pct=round(port_vol, 3),
        expected_sharpe=round(sharpe, 3),
        risk_contributions=risk_contrib,
        constraints_applied=constraints,
        objective_value=None,
        notes=[
            "Annualised assuming 252 trading days",
            "Returns expected = historical mean — past performance ≠ future results",
            "No-shorting constraint (weights ≥ 0)",
        ],
    )


def _equal_weight(symbols: list[str], mu: np.ndarray, sigma: np.ndarray,
                  reason: str) -> OptimisationResult:
    n = len(symbols)
    w = np.ones(n) / n
    return _build_result("EQUAL_WEIGHT_FALLBACK", symbols, w, mu, sigma, 0.065,
                          constraints=[reason])
