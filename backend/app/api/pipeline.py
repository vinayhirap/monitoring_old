"""Pipeline endpoints — sequential gated analysis."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query

from app.engines import pipeline, fibonacci, astrology
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.get("/run", summary="Run the full gated pipeline (esoteric → technical → strategy → consistency → accuracy)")
async def run(
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = 100_000,
    esoteric_min: float = Query(55.0, ge=50, le=100),
    technical_min: float = Query(55.0, ge=50, le=100),
    require_agreement: bool = True,
    max_finalists: int = Query(15, ge=1, le=30),
    parallel: int = Query(6, ge=1, le=16),
    attach_accuracy: bool = True,
    consistency_mode: Literal["strict", "warn", "block"] = Query(
        "strict",
        description=("strict = downgrade to WAIT on HIGH conflicts (astro/hora veto); "
                     "warn = annotate only; block = downgrade on any conflict")
    ),
    universe: str | None = Query(None, description="Comma-separated symbol override"),
    quick: bool = Query(True, description="True = top-50 most-liquid (~30s). False = full ~180-symbol universe (~120s)."),
    diamond_only: bool = Query(False, description="Only DIAMOND-tier finalists — 6/6 confluence + lunar PROCEED + 0 HIGH conflicts + historical hit-rate ≥70%. Typically 0-3 per run."),
    min_backtest_hit_rate: float = Query(0.0, ge=0, le=100,
        description="Drop any finalist whose mini-backtest hit-rate is below this (0=disabled)."),
):
    try:
        syms = [s.strip().upper() for s in universe.split(",")] if universe else None
        res = pipeline.run_pipeline(
            universe=syms,
            horizon=horizon, capital=capital,
            esoteric_min=esoteric_min, technical_min=technical_min,
            require_agreement=require_agreement,
            max_finalists=max_finalists,
            parallel=parallel,
            attach_accuracy=attach_accuracy,
            consistency_mode=consistency_mode,
            quick=quick,
            diamond_only=diamond_only,
            min_backtest_hit_rate=min_backtest_hit_rate,
        )
        return res.to_dict()
    except Exception as e:
        raise HTTPException(500, f"pipeline failed: {e}")


@router.get("/esoteric/{symbol}", summary="Stage 1 only — esoteric reading for a single symbol")
async def esoteric_single(symbol: str):
    try:
        r = pipeline.esoteric_evaluate(symbol.upper())
        return {
            "symbol": r.symbol, "sector": r.sector,
            "score": r.score, "direction": r.direction,
            "components": r.components, "reasons": r.reasons,
        }
    except Exception as e:
        raise HTTPException(500, f"esoteric failed: {e}")


@router.get("/fibonacci/{symbol}", summary="Auto-detected Fibonacci levels for a symbol")
async def fib_single(symbol: str, lookback: int = 60):
    try:
        df = get_ohlcv(symbol.upper(), periods=lookback + 30)
        return fibonacci.analyze(df, lookback=lookback).to_dict()
    except Exception as e:
        raise HTTPException(500, f"fib failed: {e}")


@router.get("/symbol-astro/{symbol}", summary="Per-symbol astrology match (nakshatra alignment)")
async def symbol_astro(symbol: str):
    try:
        return astrology.symbol_astro_match(symbol.upper())
    except Exception as e:
        raise HTTPException(500, f"symbol-astro failed: {e}")
