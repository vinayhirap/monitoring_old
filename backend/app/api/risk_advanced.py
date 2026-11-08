"""Advanced risk analytics endpoints — VaR / ES / Monte Carlo / stress."""
from fastapi import APIRouter, HTTPException, Body, Query
from pydantic import BaseModel, Field

import numpy as np

from app.engines import risk_analytics
from app.services.market_data import get_ohlcv

router = APIRouter()


class PositionRisk(BaseModel):
    symbol: str
    position_value: float = Field(..., gt=0)
    confidence: float = Field(0.95, ge=0.5, le=0.999)
    horizon_days: int = Field(1, ge=1, le=252)
    lookback_periods: int = Field(252, ge=30, le=2000)


@router.post("/position", summary="VaR / ES / Monte Carlo / Sharpe / Sortino for a single position")
def position_risk(req: PositionRisk):
    try:
        df = get_ohlcv(req.symbol, periods=req.lookback_periods)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV data for {req.symbol}")
        returns = df["close"].astype(float).pct_change().dropna().values
        return risk_analytics.analyse_position(
            returns_pct=returns,
            position_value=req.position_value,
            confidence=req.confidence,
            horizon_days=req.horizon_days,
        ).to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"position risk failed: {e}")


class PortfolioRiskRequest(BaseModel):
    positions: list[dict]   # [{symbol, value}]
    lookback_periods: int = Field(252, ge=30, le=2000)


@router.post("/portfolio", summary="Aggregate portfolio VaR with correlation matrix")
def portfolio_risk(req: PortfolioRiskRequest):
    try:
        positions_with_returns = []
        for p in req.positions:
            df = get_ohlcv(p["symbol"], periods=req.lookback_periods)
            if df is None or df.empty:
                continue
            returns = df["close"].astype(float).pct_change().dropna().values
            positions_with_returns.append({
                "symbol": p["symbol"],
                "value": float(p["value"]),
                "returns_pct": returns.tolist(),
            })
        if not positions_with_returns:
            raise HTTPException(404, "No price data for any position")
        return risk_analytics.portfolio_risk(positions_with_returns).to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"portfolio risk failed: {e}")


class StressTestRequest(BaseModel):
    positions: list[dict]   # [{symbol, value, beta?}]
    scenarios: list[str] | None = None


@router.post("/stress-test", summary="Apply historical stress scenarios to current positions")
def stress_test(req: StressTestRequest):
    try:
        return risk_analytics.stress_test(req.positions, scenarios=req.scenarios)
    except Exception as e:
        raise HTTPException(500, f"stress test failed: {e}")


@router.get("/scenarios", summary="List available historical stress scenarios")
def list_scenarios():
    return {
        "scenarios": [
            {"key": k, **v} for k, v in risk_analytics.STRESS_SCENARIOS.items()
        ]
    }
