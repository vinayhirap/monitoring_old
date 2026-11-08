"""Historical OHLCV backfill endpoints.

POST /api/backfill/run        — start a backfill (returns immediately, runs in background)
GET  /api/backfill/status     — current state, progress, errors
POST /api/backfill/run-sync   — blocking variant (use only for small symbol lists)
"""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query

from app.services import backfill

router = APIRouter()


@router.post(
    "/run",
    summary="Start OHLCV backfill in background — pulls historical bars from Angel One",
)
async def start_backfill(
    interval: Literal["5m", "15m", "1h", "1d"] = Query("1d"),
    days_back: int = Query(730, ge=30, le=3650,
                            description="How many calendar days back to fetch"),
    quick: bool = Query(False, description="True = top-50 most liquid F&O only"),
    symbols: str | None = Query(None, description="Optional comma-separated symbols (overrides quick)"),
    exchange: str = "NSE",
):
    """Idempotent. Re-running fills holes without duplicating bars. Existing
    rows are upserted (latest close/volume wins). Safe to interrupt and resume.

    Approximate runtime:
      • quick=True, interval=1d, days_back=730    →  ~ 1 minute
      • full universe, interval=1d, days_back=730 →  ~ 3-5 minutes
      • full universe, interval=15m, days_back=90 →  ~ 15-25 minutes
    """
    try:
        sym_list = [s.strip().upper() for s in symbols.split(",")] if symbols else None
        return backfill.run_in_background(
            symbols=sym_list, interval=interval,
            days_back=days_back, exchange=exchange, quick=quick,
        )
    except Exception as e:
        raise HTTPException(500, f"backfill start failed: {e}")


@router.post(
    "/run-sync",
    summary="Blocking backfill — for small symbol lists only",
)
async def run_sync(
    symbols: str = Query(..., description="Comma-separated symbols"),
    interval: Literal["5m", "15m", "1h", "1d"] = "1d",
    days_back: int = Query(365, ge=30, le=3650),
    exchange: str = "NSE",
):
    try:
        sym_list = [s.strip().upper() for s in symbols.split(",")]
        return backfill.run(
            symbols=sym_list, interval=interval,
            days_back=days_back, exchange=exchange,
        )
    except Exception as e:
        raise HTTPException(500, f"backfill sync failed: {e}")


@router.get("/status", summary="Backfill progress")
async def status():
    return backfill.get_status()
