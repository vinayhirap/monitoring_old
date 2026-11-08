"""Auto-optimize engine weights from measured historical performance.

Three endpoints:
  • GET  /api/optimize/measure/{symbol}    — analyze without changes
  • POST /api/optimize/apply                — write the suggested weights to disk
  • POST /api/optimize/reset                — restore baseline weights
  • GET  /api/optimize/current              — what's currently active
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.engines import weight_optimizer
from app.services.market_data import get_ohlcv


router = APIRouter()


@router.get("/measure/{symbol}",
             summary="Measure each engine's hit rate on historical bars (no changes)")
def measure(symbol: str,
                   exchange: str = "NSE",
                   lookback_bars: int = Query(150, ge=50, le=500)):
    try:
        df = get_ohlcv(symbol.upper(), exchange=exchange, periods=lookback_bars + 70)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {symbol}")
        report = weight_optimizer.optimize_for_symbol(df, symbol.upper(),
                                                       lookback_bars=lookback_bars)
        return report.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"measure failed: {e}")


class ApplyRequest(BaseModel):
    symbol: str = "NIFTY"
    lookback_bars: int = 150
    source: str = "auto-optimize"
    custom_weights: dict | None = None     # If supplied, skip measurement and use these


@router.post("/apply",
              summary="Run optimizer + apply suggested weights system-wide")
def apply(req: ApplyRequest):
    try:
        if req.custom_weights:
            # Direct manual override (e.g. user wants to test "astro=0")
            weights = req.custom_weights
            total = sum(weights.values())
            if abs(total - 1.0) > 0.05:
                raise HTTPException(400, f"weights must sum to ~1.0 (got {total})")
            weight_optimizer.save_weights(weights, source=f"manual: {req.source}")
            return {"applied": True, "weights": weights,
                     "source": f"manual: {req.source}"}

        df = get_ohlcv(req.symbol.upper(), periods=req.lookback_bars + 70)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {req.symbol}")
        report = weight_optimizer.optimize_for_symbol(df, req.symbol.upper(),
                                                       lookback_bars=req.lookback_bars)
        weight_optimizer.save_weights(report.suggested_weights,
                                        source=f"auto from {req.symbol}")
        return {
            "applied": True,
            "weights": report.suggested_weights,
            "baseline": report.baseline_weights,
            "expected_improvement_pp": report.expected_improvement_pp,
            "engine_hit_rates": report.engine_hit_rates,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"apply failed: {e}")


@router.post("/reset", summary="Restore the baseline weights (delete tuned config)")
def reset():
    try:
        if weight_optimizer.CONFIG_PATH.exists():
            weight_optimizer.CONFIG_PATH.unlink()
        return {"reset": True, "weights": weight_optimizer.BASELINE_WEIGHTS}
    except Exception as e:
        raise HTTPException(500, f"reset failed: {e}")


@router.get("/current", summary="Currently-active engine weights + source")
def current():
    return weight_optimizer.current_config()
