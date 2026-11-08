"""Gann endpoints.

Auth: all endpoints require a logged-in user. Tier-gating is NOT applied here
because Gann is part of the core analyzer toolkit available to every paid
tier (and FREE — once they're logged in). If you later want a "premium Gann"
tier-gated subset, wrap individual handlers with `require_tier(...)`.
"""
from datetime import date
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_current_user
from app.engines import gann, gann_vibration, gann_master, gann_natural_squares, fibonacci_fractal
from app.models.user import User
from app.schemas.analysis import (
    GannSquare9Request, GannSquare9Response,
    GannCyclesRequest, GannCyclesResponse,
)
from app.services.market_data import get_ohlcv, LiveDataUnavailable

# Router-level auth — every handler under /api/gann requires a logged-in user.
# Using router dependencies keeps the per-handler signatures clean and ensures
# we cannot accidentally add a new endpoint that bypasses auth.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/square9", summary="Square of 9 supports / resistances around a price")
def square9(req: GannSquare9Request):
    try:
        return gann.square_of_9_levels(req.price, req.levels)
    except Exception as e:
        raise HTTPException(500, f"square9 failed: {e}")


@router.post("/time-cycles", summary="Time-reversal date projections from anchor")
def time_cycles(req: GannCyclesRequest):
    try:
        return {
            "anchor_date": req.anchor_date.isoformat(),
            "projected_dates": gann.time_cycles(req.anchor_date, req.cycles),
        }
    except Exception as e:
        raise HTTPException(500, f"cycles failed: {e}")


@router.get("/score", summary="Gann confluence score for a live price")
def gann_score(price: float, anchor_price: float | None = None):
    try:
        return gann.analyze(price, anchor_price=anchor_price).to_dict()
    except Exception as e:
        raise HTTPException(500, f"gann score failed: {e}")


# ===========================================================================
# Law of Vibration
# ===========================================================================

@router.get("/vibration/symbol/{symbol}", summary="Symbol's Gann vibration profile")
def vibration_symbol(symbol: str):
    """Returns symbol's raw sum, digital root, ruling planet, and base
    vibration cycle days. Computed from Gann's letter-value table."""
    try:
        return gann_vibration.symbol_vibration(symbol).to_dict()
    except Exception as e:
        raise HTTPException(500, f"vibration failed: {e}")


@router.get("/vibration/price-levels", summary="All-planet longitudes converted to price levels")
def vibration_price_levels(anchor_price: float = Query(..., gt=0),
                                  cycle_size: float = 360.0):
    """For each of the 9 graha, returns its current longitude converted to a
    price level (linear + Square-of-9 readings). Use as additional S/R."""
    try:
        return {
            "anchor_price": anchor_price,
            "cycle_size": cycle_size,
            "levels": gann_vibration.all_planet_price_levels(anchor_price, cycle_size=cycle_size),
        }
    except Exception as e:
        raise HTTPException(500, f"price-levels failed: {e}")


@router.get("/vibration/resonance", summary="Harmonic resonance score for live price vs planetary lines")
def vibration_resonance(live_price: float = Query(..., gt=0),
                               anchor_price: float = Query(..., gt=0),
                               symbol: str | None = None,
                               tolerance_pct: float = 0.6):
    try:
        res = gann_vibration.harmonic_resonance(
            live_price=live_price, anchor_price=anchor_price,
            symbol=symbol, tolerance_pct=tolerance_pct,
        )
        return res.to_dict()
    except Exception as e:
        raise HTTPException(500, f"resonance failed: {e}")


@router.get("/vibration/next-dates/{symbol}", summary="Forward dates when symbol's ruling planet hits harmonic")
def vibration_next_dates(symbol: str, horizon_days: int = Query(90, ge=7, le=365)):
    try:
        return {
            "symbol": symbol,
            "horizon_days": horizon_days,
            "dates": gann_vibration.next_vibration_dates(symbol, horizon_days=horizon_days),
        }
    except Exception as e:
        raise HTTPException(500, f"next-dates failed: {e}")


# ===========================================================================
# Master Charts — 144 / 52 / Hexagon
# ===========================================================================

@router.get("/master144", summary="Master 144 price + time grid around an anchor")
def master144(anchor_price: float = Query(..., gt=0),
                    anchor_date: date | None = None,
                    range_factor: float | None = None):
    try:
        price_grid = gann_master.master_144(anchor_price, range_factor=range_factor)
        time_grid = gann_master.master_144_time(anchor_date) if anchor_date else []
        return {"price_grid": price_grid, "time_grid": time_grid}
    except Exception as e:
        raise HTTPException(500, f"master144 failed: {e}")


@router.get("/master52", summary="Master 52 (weekly) price + time grid")
def master52(anchor_price: float = Query(..., gt=0),
                   anchor_date: date | None = None):
    try:
        price_grid = gann_master.master_52(anchor_price)
        time_grid = gann_master.master_52_time(anchor_date) if anchor_date else []
        return {"price_grid": price_grid, "time_grid": time_grid}
    except Exception as e:
        raise HTTPException(500, f"master52 failed: {e}")


@router.get("/hexagon", summary="Hexagon chart — 6-faced master spiral")
def hexagon(anchor_price: float = Query(..., gt=0),
                  rings: int = Query(8, ge=1, le=16)):
    try:
        return gann_master.hexagon_chart(anchor_price, rings=rings)
    except Exception as e:
        raise HTTPException(500, f"hexagon failed: {e}")


@router.get("/master/summary", summary="S/R summary across Master 144 / 52 / Hexagon")
def master_summary(live_price: float = Query(..., gt=0),
                          anchor_price: float = Query(..., gt=0)):
    try:
        return gann_master.summarise(live_price, anchor_price).to_dict()
    except Exception as e:
        raise HTTPException(500, f"master summary failed: {e}")


# ===========================================================================
# Pine-Script ports — natural-square levels + nested fractal Fib
# ===========================================================================

@router.get("/natural-squares/{symbol}", summary="Integer perfect-square Gann levels (Pine Script port)")
def natural_squares(symbol: str,
                           exchange: str = "NSE",
                           levels: int = Query(4, ge=1, le=10),
                           bars: int = Query(20, ge=5, le=200)):
    """Pine Script v4 "[A618] Fibonacci and Gann based S/R" — natural-squares half.

    Returns the integer perfect-square ladder around live spot:
      base_n = floor(sqrt(spot)); zero = base_n²
      upper_k = (base_n + k)²;    lower_k = (base_n - k)²
    """
    sym = symbol.upper().strip()
    try:
        df = get_ohlcv(sym, exchange=exchange, periods=bars)
        spot = float(df["close"].iloc[-1])
        return gann_natural_squares.compute(spot, levels=levels).to_dict()
    except LiveDataUnavailable as e:
        raise HTTPException(503, f"Live data unavailable for {sym}: {e}")
    except Exception as e:
        raise HTTPException(500, f"natural-squares failed: {e}")


@router.get("/fractal-fib/{symbol}", summary="Nested Fibonacci fractal grid (Pine Script port)")
def fractal_fib(symbol: str,
                       exchange: str = "NSE",
                       lookback: int = Query(100, ge=20, le=400)):
    """Pine Script v4 "[A618] Fibonacci and Gann based S/R" — fractal-Fib half.

    Returns primary Fibs + extensions + nested sub-Fibs across 7 bands, plus
    confluence clusters (zones where 3+ levels overlap within 0.3%).
    """
    sym = symbol.upper().strip()
    try:
        df = get_ohlcv(sym, exchange=exchange, periods=lookback)
        return fibonacci_fractal.compute(df, lookback=lookback).to_dict()
    except LiveDataUnavailable as e:
        raise HTTPException(503, f"Live data unavailable for {sym}: {e}")
    except Exception as e:
        raise HTTPException(500, f"fractal-fib failed: {e}")
