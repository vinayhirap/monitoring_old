"""Quantitative / advanced-math indicators endpoint."""
from fastapi import APIRouter, HTTPException, Query

from app.engines import quant_indicators, pivots as pivots_eng
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.get(
    "/{symbol}",
    summary="Advanced-math indicators — Hurst, Kalman, GARCH, OU half-life, LR channel, etc.",
)
async def quant_analysis(
    symbol: str,
    exchange: str = "NSE",
    periods: int = Query(250, ge=50, le=2000),
):
    try:
        df = get_ohlcv(symbol.upper(), exchange=exchange, periods=periods)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV data for {symbol}")
        result = quant_indicators.analyze(df, symbol=symbol.upper())
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"quant analysis failed: {e}")


@router.get(
    "/{symbol}/pivots",
    summary="Camarilla + Standard + Fibonacci pivot levels (daily / weekly / monthly)",
)
async def pivot_levels(
    symbol: str,
    exchange: str = "NSE",
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
):
    try:
        df = get_ohlcv(symbol.upper(), exchange=exchange, periods=250)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV data for {symbol}")
        return pivots_eng.analyze(df, period=period)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"pivots failed: {e}")
