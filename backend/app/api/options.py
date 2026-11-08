"""Options / F&O endpoints. Tier-gated to INTERMEDIATE+ (live_options_strategy feature)."""
from datetime import date, timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import require_tier
from app.engines import options
from app.models.user import User
from app.schemas.analysis import OptionsAnalyzeRequest
from app.services import fno_recommendation

router = APIRouter()


@router.get("/recommend/{symbol}",
              summary="Complete F&O recommendation: verdict + strategy + strikes + astro overlay")
def recommend_fno(
    symbol: str,
    user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
    horizon: str = Query("INTRADAY", pattern="^(INTRADAY|SWING|POSITIONAL)$"),
    capital: float = Query(100_000, gt=0),
):
    """One-shot F&O recommendation orchestrating every engine in the platform:

    Inputs (computed internally):
      • Technical, SMC, Gann, Fibonacci, ML directional consensus
      • Vedic astrology + market sentiment overlay
      • Advanced TA (VWAP, divergences, MTF momentum)
      • Live option chain → PCR, max pain, OI walls, IV, Black-Scholes Greeks
      • Risk Guard (2%/6%/R:R/circuit breaker)
      • Recommendation Quality clarity layer (hard blocks, soft gates, promotions)

    Output:
      • verdict (STRONG_BUY/BUY/WATCH/WAIT/SELL/STRONG_SELL/AVOID)
      • strategy (CE_BUY / BULL_CALL_SPREAD / IRON_CONDOR / ...) with specific strikes
      • per-leg greeks + max profit / max loss / breakevens
      • entry & exit triggers, suggested lots & capital
      • astro_overlay { aligned, bias, score, factors }
      • technical_confluence { confirming_count, dissenting_count, names }
      • ready-to-place `execution_payload` for the broker integration

    Refuses to recommend a trade (verdict = AVOID/WATCH/WAIT) when:
      • Price sanity check failed (SUSPECT verdict)
      • Risk guard verdict is BLOCK
      • Confidence < 55%
      • Engines are conflicted
    """
    # Call symbol_detail as a plain function — FastAPI handlers are sync defs
    # so they work outside the request pipeline. We import locally to avoid a
    # circular import at module load (symbol.py imports a lot of engines).
    from app.api.symbol import symbol_detail
    try:
        symbol_data = symbol_detail(
            symbol=symbol, horizon=horizon, capital=capital, bars=120, lang="en",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"symbol analysis failed: {e}")

    return fno_recommendation.safe_build(symbol_data, capital=capital)



@router.post("/analyze", summary="Analyze an options chain (PCR, Max Pain, Greeks)")
async def analyze_chain(req: OptionsAnalyzeRequest,
                         user: Annotated[User, Depends(require_tier("INTERMEDIATE"))]):
    try:
        result = options.analyze(req.symbol, req.spot_price, req.expiry, req.chain)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(500, f"options failed: {e}")


@router.get("/synthetic/{symbol}", summary="Generate a synthetic options chain (paper mode demo)")
async def synthetic_chain(symbol: str,
                           user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
                           spot: float = Query(..., gt=0),
                           step: float = 50,
                           width: int = 10):
    try:
        chain = options.synthetic_chain(symbol, spot, step, width)
        result = options.analyze(symbol, spot, date.today() + timedelta(days=7), chain)
        return {"chain": chain, "analysis": result.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"synthetic failed: {e}")


@router.get("/greeks", summary="Black-Scholes Greeks for a single option")
async def greeks(user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
                  spot: float = Query(..., gt=0),
                  strike: float = Query(..., gt=0),
                  days: int = Query(..., ge=0),
                  iv_pct: float = Query(20.0, gt=0), is_call: bool = True,
                  r: float = 0.07):
    try:
        return options.bs_greeks(spot, strike, days / 365, r, iv_pct / 100, is_call)
    except Exception as e:
        raise HTTPException(500, f"greeks failed: {e}")
