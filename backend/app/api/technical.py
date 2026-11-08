"""Technical / SMC / Pivots / Ichimoku analysis endpoints."""
from fastapi import APIRouter, HTTPException, Query

from app.engines import technical, smc, pivots, ichimoku
from app.schemas.analysis import AnalysisRequest
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.post("/score", summary="Technical indicator score (RSI/MACD/EMA/etc.)")
async def technical_score(req: AnalysisRequest):
    try:
        df = get_ohlcv(req.symbol, exchange=req.exchange, periods=250)
        return technical.analyze(df).to_dict()
    except Exception as e:
        raise HTTPException(500, f"technical failed: {e}")


@router.post("/smc", summary="Smart Money Concepts + ICT analysis")
async def smc_analysis(req: AnalysisRequest):
    try:
        df = get_ohlcv(req.symbol, exchange=req.exchange, periods=250)
        return smc.analyze(df).to_dict()
    except Exception as e:
        raise HTTPException(500, f"smc failed: {e}")


@router.get("/pivots/{symbol}", summary="Pivot points (standard, Camarilla, Fibonacci)")
async def pivot_levels(symbol: str,
                       period: str = Query("daily", pattern="^(daily|weekly|monthly)$")):
    try:
        df = get_ohlcv(symbol.upper(), periods=250)
        return pivots.analyze(df, period=period)
    except Exception as e:
        raise HTTPException(500, f"pivots failed: {e}")


@router.get("/ichimoku/{symbol}", summary="Ichimoku Cloud (Tenkan, Kijun, Senkou A/B, Chikou)")
async def ichimoku_cloud(symbol: str):
    try:
        df = get_ohlcv(symbol.upper(), periods=250)
        return ichimoku.analyze(df).to_dict()
    except Exception as e:
        raise HTTPException(500, f"ichimoku failed: {e}")
