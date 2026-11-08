"""Moon endpoints."""
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

from app.engines import moon

router = APIRouter()


@router.get("/reading", summary="Complete lunar reading with trading gate (PROCEED/CAUTION/WAIT/AVOID)")
def reading(asof: datetime | None = Query(None)):
    try:
        return moon.reading(asof).to_dict()
    except Exception as e:
        raise HTTPException(500, f"moon failed: {e}")
