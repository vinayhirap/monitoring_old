"""Numerology endpoints."""
from datetime import date
from fastapi import APIRouter, HTTPException, Query

from app.engines import numerology

router = APIRouter()


@router.get("/symbol/{symbol}", summary="Stock symbol numerology score")
def symbol_numerology(symbol: str, ref_date: date | None = Query(None)):
    try:
        return numerology.analyze(symbol.upper(), ref_date).to_dict()
    except Exception as e:
        raise HTTPException(500, f"numerology failed: {e}")


@router.get("/life-path", summary="Trader personal life-path number")
def life_path(dob: date = Query(..., description="YYYY-MM-DD")):
    try:
        return {"dob": dob.isoformat(), "life_path": numerology.life_path(dob)}
    except Exception as e:
        raise HTTPException(500, f"life-path failed: {e}")
