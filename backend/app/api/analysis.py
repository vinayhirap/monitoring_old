"""POST /api/analysis/full — run all engines and return final signal."""
from fastapi import APIRouter, HTTPException

from app.engines import decision
from app.schemas.analysis import AnalysisRequest
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.post("/full", summary="Run full multi-engine analysis on a symbol")
def full_analysis(req: AnalysisRequest):
    try:
        df = get_ohlcv(req.symbol, exchange=req.exchange, periods=250)
        result = decision.aggregate(
            symbol=req.symbol,
            df=df,
            horizon=req.horizon,
            capital=req.capital,
        )
        return result
    except Exception as e:
        raise HTTPException(500, f"analysis failed: {e}")
