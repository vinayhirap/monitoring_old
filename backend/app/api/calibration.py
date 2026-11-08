"""Calibration / confidence-quality endpoints.

GET  /api/calibration/{symbol}       — walk-forward calibration of the engine for one symbol
POST /api/calibration/run-suite       — calibration across the top-N most-liquid symbols
"""
from fastapi import APIRouter, HTTPException, Query

from app.engines import calibration
from app.services.market_data import get_ohlcv
from app.services.universe import top_liquid

router = APIRouter()


@router.get(
    "/{symbol}",
    summary="Walk-forward calibration self-check (is the engine honestly calibrated?)",
)
async def calibrate_symbol(
    symbol: str,
    exchange: str = "NSE",
    lookback_bars: int = Query(150, ge=50, le=500,
                                description="How many recent bars to test predictions on"),
    warmup_bars: int = Query(60, ge=30, le=200,
                              description="Minimum history before predictions start"),
):
    """For each of the last `lookback_bars`, replay the forecast using only
    data available up to that bar, then compare to actual next-bar outcome.

    Returns calibration buckets (50-55, 55-60, ...) with realized win rate
    per bucket — and tells you if the engine is honestly calibrated.

    WARNING: heavy. Each prediction re-runs the full decision aggregator.
    Expect ~30-90s for 150 bars on a small EC2 instance.
    """
    try:
        df = get_ohlcv(symbol.upper(), exchange=exchange, periods=warmup_bars + lookback_bars + 30)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV data for {symbol}. "
                                       f"Run backfill first: POST /api/backfill/run?symbols={symbol}")
        # Hard guard: calibration needs more bars than the user asked for.
        # If we don't have enough, return a clear 400 instead of crashing
        # mid-loop with a slice-index error.
        required_total = warmup_bars + lookback_bars
        if len(df) < required_total:
            raise HTTPException(400, (
                f"Need at least {required_total} bars to calibrate (warmup={warmup_bars} + "
                f"lookback={lookback_bars}), only have {len(df)}. "
                f"Either reduce lookback_bars or run backfill: "
                f"POST /api/backfill/run?symbols={symbol}&days_back=365"
            ))
        report = calibration.calibrate(
            df, symbol=symbol.upper(),
            lookback_bars=lookback_bars,
            warmup_bars=warmup_bars,
        )
        return report.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        from loguru import logger
        logger.exception("calibration crashed for {}", symbol)
        raise HTTPException(500, f"calibration failed: {type(e).__name__}: {e}")


@router.get(
    "/quick/{symbol}",
    summary="Light calibration (fewer bars, faster ~10s)",
)
async def quick_calibrate(symbol: str, exchange: str = "NSE"):
    try:
        df = get_ohlcv(symbol.upper(), exchange=exchange, periods=120)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV data for {symbol}. "
                                       f"Run backfill first: POST /api/backfill/run?symbols={symbol}")
        if len(df) < 100:
            raise HTTPException(400, (
                f"Need at least 100 bars for quick calibration; only have {len(df)}. "
                f"Run backfill: POST /api/backfill/run?symbols={symbol}&days_back=180"
            ))
        report = calibration.calibrate(
            df, symbol=symbol.upper(),
            lookback_bars=50, warmup_bars=50,
        )
        return report.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        from loguru import logger
        logger.exception("quick calibration crashed for {}", symbol)
        raise HTTPException(500, f"quick calibration failed: {type(e).__name__}: {e}")
