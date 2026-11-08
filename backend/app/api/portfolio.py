"""Portfolio optimisation endpoints — MV / Risk Parity / Black-Litterman."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import numpy as np

from app.engines import portfolio_optimizer
from app.services.market_data import get_ohlcv

router = APIRouter()


def _gather_returns(symbols: list[str], lookback: int = 252) -> tuple[list[str], np.ndarray]:
    rows = []
    kept = []
    for s in symbols:
        df = get_ohlcv(s, periods=lookback)
        if df is None or df.empty or len(df) < 30:
            continue
        rows.append(df["close"].astype(float).pct_change().dropna().values)
        kept.append(s)
    if not rows:
        return [], np.zeros((0, 0))
    min_len = min(len(r) for r in rows)
    aligned = np.array([r[-min_len:] for r in rows], dtype=float)
    return kept, aligned


class MVRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2)
    lookback_periods: int = 252
    max_weight: float = Field(0.30, gt=0, le=1)
    min_weight: float = Field(0.00, ge=0, le=0.5)
    target_return: float | None = None


@router.post("/mean-variance", summary="Markowitz mean-variance optimal weights")
def mean_variance(req: MVRequest):
    try:
        syms, returns = _gather_returns(req.symbols, req.lookback_periods)
        if returns.size == 0:
            raise HTTPException(404, "No price history available for any symbol")
        return portfolio_optimizer.mean_variance(
            syms, returns,
            max_weight=req.max_weight,
            min_weight=req.min_weight,
            target_return=req.target_return,
        ).to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"MV optimisation failed: {e}")


class RPRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2)
    lookback_periods: int = 252
    max_weight: float = 0.40


@router.post("/risk-parity", summary="Equal-risk-contribution portfolio")
def risk_parity(req: RPRequest):
    try:
        syms, returns = _gather_returns(req.symbols, req.lookback_periods)
        if returns.size == 0:
            raise HTTPException(404, "No price history available")
        return portfolio_optimizer.risk_parity(syms, returns, max_weight=req.max_weight).to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"risk parity failed: {e}")


class BLRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=2)
    lookback_periods: int = 252
    market_caps: list[float] | None = None
    views: dict[str, float] | None = None              # {symbol: expected_annual_return_pct}
    view_confidences: dict[str, float] | None = None   # {symbol: 0..1}
    risk_aversion: float = 2.5
    tau: float = 0.05


@router.post("/black-litterman", summary="Bayesian blend of equilibrium + analyst views")
def black_litterman(req: BLRequest):
    try:
        syms, returns = _gather_returns(req.symbols, req.lookback_periods)
        if returns.size == 0:
            raise HTTPException(404, "No price history available")
        return portfolio_optimizer.black_litterman(
            symbols=syms, daily_returns=returns,
            market_caps=req.market_caps, views=req.views,
            view_confidences=req.view_confidences,
            risk_aversion=req.risk_aversion, tau=req.tau,
        ).to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Black-Litterman failed: {e}")
