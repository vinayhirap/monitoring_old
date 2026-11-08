"""Daily recommendation endpoints."""
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.engines import recommender, signal_stability

router = APIRouter()


@router.get("/scan", summary="Scan a universe of symbols and return ranked Top-N recommendations")
async def scan(
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = 100_000,
    min_confidence: float = Query(60.0, ge=0, le=100),
    top_n: int = Query(10, ge=1, le=50),
    universe: str | None = Query(
        None,
        description=(
            "Universe selector OR comma-separated list. "
            "Names: 'fno_top50' (~50 syms, ~20s), 'fno' (~180, ~90s), "
            "'nifty500' (500, ~5min), 'all_nse' (~2000, ~30min). "
            "Or pass comma-separated symbols like 'RELIANCE,TCS,JPPOWER'."
        ),
    ),
    parallel: int = Query(6, ge=1, le=16),
    quick: bool = Query(True, description="If universe not specified: True=top50, False=fno-full"),
):
    from app.services.universe import universe_for
    try:
        # Resolve universe → symbol list
        if universe is None:
            symbols = None     # let recommender use its default (top50/all)
        elif "," in universe:
            symbols = [s.strip().upper() for s in universe.split(",") if s.strip()]
        elif universe.lower() in ("fno_top50", "fno", "nifty500", "all_nse", "top50"):
            symbols = universe_for(universe)
        else:
            # Single symbol passed
            symbols = [universe.strip().upper()]

        res = recommender.scan(
            symbols=symbols,
            horizon=horizon,
            capital=capital,
            min_confidence=min_confidence,
            top_n=top_n,
            parallel=parallel,
            quick=quick,
        )
        return res.to_dict()
    except Exception as e:
        raise HTTPException(500, f"recommender failed: {e}")


@router.get(
    "/professional",
    summary="Professional-grade ranked recommendations (BlackRock-style)",
    description=(
        "Returns ranked recommendations with: 7-tier conviction label "
        "(STRONG_BUY..STRONG_SELL), conviction stars (1-5) reflecting engine "
        "agreement, instrument ranking (EQUITY/FUTURES/OPTIONS best-fit), "
        "risk-profile variants (AGGRESSIVE/MODERATE/CONSERVATIVE sizing of the "
        "same signal), and a stability layer so recommendations don't flip on "
        "noise. Recommendation per (symbol, horizon) is sticky for the "
        "horizon's min-hold period."
    ),
)
async def professional(
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = Query(100_000, gt=0),
    min_stars: int = Query(3, ge=1, le=5),
    top_n: int = Query(10, ge=1, le=50),
    universe: str | None = Query(
        None,
        description=(
            "Universe selector OR comma-separated list: "
            "'fno_top50' / 'fno' / 'nifty500' / 'all_nse' / 'RELIANCE,TCS,JPPOWER'"
        ),
    ),
    parallel: int = Query(6, ge=1, le=16),
    quick: bool = Query(True),
    apply_stability: bool = Query(True, description="Apply hysteresis layer so signals don't flip on noise"),
):
    from app.services.universe import universe_for
    try:
        # Resolve universe selector → symbol list
        if universe is None:
            symbols = None
        elif "," in universe:
            symbols = [s.strip().upper() for s in universe.split(",") if s.strip()]
        elif universe.lower() in ("fno_top50", "fno", "nifty500", "all_nse", "top50"):
            symbols = universe_for(universe)
        else:
            symbols = [universe.strip().upper()]
        return recommender.professional_scan(
            symbols=symbols,
            horizon=horizon,
            capital=capital,
            min_stars=min_stars,
            top_n=top_n,
            parallel=parallel,
            quick=quick,
            apply_stability=apply_stability,
        )
    except Exception as e:
        raise HTTPException(500, f"professional scan failed: {e}")


@router.get(
    "/stability/{symbol}",
    summary="Current sticky recommendation for a symbol (stability layer state)",
)
async def stability_status(
    symbol: str,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
):
    try:
        cur = signal_stability.get_current(symbol.upper(), horizon)
        if cur is None:
            return {"symbol": symbol.upper(), "horizon": horizon, "state": "no_observation_yet"}
        return cur
    except Exception as e:
        raise HTTPException(500, f"stability lookup failed: {e}")


@router.get("/sectors", summary="Sector-level bullish/bearish breakdown")
async def sectors(
    horizon: str = "SWING",
    capital: float = 100_000,
    min_confidence: float = 0,
    parallel: int = 6,
):
    try:
        res = recommender.scan(horizon=horizon, capital=capital,
                               min_confidence=min_confidence, top_n=0, parallel=parallel)
        sectors_sorted = sorted(res.by_sector.values(),
                                 key=lambda s: -(s["bullish"] - s["bearish"]))
        return {
            "asof": res.asof,
            "universe_size": res.universe_size,
            "sectors": sectors_sorted,
        }
    except Exception as e:
        raise HTTPException(500, f"sector scan failed: {e}")
