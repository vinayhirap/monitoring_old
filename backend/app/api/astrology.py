"""Astrology endpoints."""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

from app.engines import astrology

router = APIRouter()


@router.get("/transits", summary="Live planetary positions (sidereal Lahiri)")
def transits(asof: datetime | None = Query(None, description="ISO datetime; defaults to now")):
    try:
        return astrology.transits_snapshot(asof)
    except Exception as e:
        raise HTTPException(500, f"transits failed: {e}")


@router.get("/market-sentiment", summary="Aggregated bullish/bearish planetary read")
def market_sentiment(asof: datetime | None = Query(None)):
    try:
        return astrology.market_sentiment(asof).to_dict()
    except Exception as e:
        raise HTTPException(500, f"sentiment failed: {e}")


@router.get("/moon-phase", summary="Current Moon phase + tithi + paksha")
def moon_phase_endpoint(asof: datetime | None = Query(None)):
    try:
        return astrology.moon_phase(asof or datetime.utcnow())
    except Exception as e:
        raise HTTPException(500, f"moon failed: {e}")
