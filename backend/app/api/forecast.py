"""Forward-looking forecast endpoints."""
from datetime import date
from fastapi import APIRouter, HTTPException, Query

from app.engines import forecast

router = APIRouter()


@router.get("/symbol/{symbol}", summary="Per-symbol 7/14-day astro+numerology+gann outlook")
async def symbol_outlook(
    symbol: str,
    days: int = Query(7, ge=1, le=30),
    start: date | None = Query(None, description="Default = today"),
):
    try:
        return forecast.symbol_weekly_outlook(symbol.upper(), days=days, start=start).to_dict()
    except Exception as e:
        raise HTTPException(500, f"outlook failed: {e}")


@router.get("/market", summary="Market-wide weekly calendar (ingresses, Moon, eclipses, Gann)")
async def market_calendar(
    days: int = Query(7, ge=1, le=30),
    start: date | None = Query(None),
):
    try:
        return forecast.market_weekly_calendar(days=days, start=start)
    except Exception as e:
        raise HTTPException(500, f"market calendar failed: {e}")
