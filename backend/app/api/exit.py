"""Exit-signal endpoints — when to sell / book / trail an existing position."""
from datetime import date, datetime
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.engines import exit as exit_engine
from app.services.market_data import get_ohlcv

router = APIRouter()


class ExitRequest(BaseModel):
    symbol: str = Field(..., examples=["RELIANCE"])
    side: Literal["LONG", "SHORT"] = "LONG"
    entry_price: float = Field(..., gt=0)
    qty: int = Field(..., gt=0)
    entry_date: date
    current_stop: float | None = None
    trail_atr_mult: float = 1.5
    profit_target_atr_mult: float = 4.0
    max_days: int = 30


@router.post("/evaluate", summary="Should I exit this position? (HOLD/TRAIL/PARTIAL/FULL)")
def evaluate_exit(req: ExitRequest):
    try:
        df = get_ohlcv(req.symbol, periods=250)
        decision = exit_engine.evaluate(
            symbol=req.symbol,
            df=df,
            entry_price=req.entry_price,
            qty=req.qty,
            entry_date=req.entry_date,
            side=req.side,
            current_stop=req.current_stop,
            trail_atr_mult=req.trail_atr_mult,
            profit_target_atr_mult=req.profit_target_atr_mult,
            max_days=req.max_days,
        )
        return decision.to_dict()
    except Exception as e:
        raise HTTPException(500, f"exit evaluation failed: {e}")
