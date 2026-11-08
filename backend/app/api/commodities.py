"""MCX commodity recommendations + per-commodity analysis.

GET  /api/commodities/list             — universe with ruling planets
GET  /api/commodities/scan             — scan all commodities and rank
GET  /api/commodities/{symbol}         — per-commodity deep analysis
GET  /api/commodities/astro/{symbol}   — commodity-specific astrology only
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Annotated
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.dependencies import require_tier
from app.models.user import User

from app.brokers.angelone import broker_instance
from app.config import settings
from app.engines import (
    technical, smc, fibonacci, gann, astrology, numerology,
    strategy as strategy_eng, hora as hora_eng, options_strategy, gap_forecast,
    options as options_eng,
)
from app.services import commodities_universe as cu
from app.services import instruments
from app.services.market_data import get_ohlcv, LiveDataUnavailable

router = APIRouter()


# ---------------------------------------------------------------------------
# Universe listing
# ---------------------------------------------------------------------------

@router.get("/list", summary="List all MCX commodities with their ruling planets")
def list_commodities(
    user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
):
    return {
        "exchange": "MCX",
        "commodities": [
            {"symbol": sym, **info}
            for sym, info in cu.COMMODITIES.items()
        ],
        "disclaimer": (
            "Planetary rulership of commodities is from traditional Mundane "
            "astrology. Confluence layer only — not a guaranteed predictor."
        ),
    }


# ---------------------------------------------------------------------------
# Commodity-specific astrology
# ---------------------------------------------------------------------------

@router.get("/astro/{symbol}", summary="Commodity-specific astrology score (ruling-planet driven)")
def commodity_astro(symbol: str,
                           user: Annotated[User, Depends(require_tier("INTERMEDIATE"))]):
    try:
        return cu.commodity_astro_match(symbol.upper())
    except Exception as e:
        raise HTTPException(500, f"commodity astro failed: {e}")


# ---------------------------------------------------------------------------
# Per-commodity deep analysis (mirrors /api/symbol/{sym} but for MCX)
# ---------------------------------------------------------------------------

@router.get("/{symbol}", summary="Per-commodity full analysis (chart, engines, options, gap forecast)")
def commodity_detail(symbol: str,
                            user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
                            horizon: str = Query("SWING", pattern="^(INTRADAY|SWING|POSITIONAL)$"),
                            capital: float = Query(100_000, gt=0),
                            bars: int = Query(120, ge=20, le=400)):
    sym = symbol.upper().strip()
    info = cu.info(sym)
    if not info:
        raise HTTPException(404, f"{sym} is not a recognized MCX commodity")

    try:
        df = get_ohlcv(sym, exchange="MCX", periods=bars)
    except LiveDataUnavailable as e:
        if settings.live_only:
            raise HTTPException(503, f"Live MCX data unavailable for {sym}: {e}")
        from app.engines.technical import synthetic_ohlcv
        df = synthetic_ohlcv(sym, periods=bars)

    # Run engines
    tech = technical.analyze(df)
    smc_res = smc.analyze(df)
    fib = fibonacci.analyze(df)
    spot = tech.indicators["last"]
    g = gann.analyze(spot)
    num = numerology.analyze(sym)
    commodity_astro_res = cu.commodity_astro_match(sym)

    # Direction = majority of bullish/bearish biases
    biases = [tech.bias, g.bias, fib.bias, commodity_astro_res["bias"], num.bias]
    bulls = sum(1 for b in biases if b == "BULLISH")
    bears = sum(1 for b in biases if b == "BEARISH")
    direction = "BULLISH" if bulls > bears else "BEARISH" if bears > bulls else "NEUTRAL"

    # Confidence — average of engine scores
    confidence = round(
        (tech.score + g.score + fib.score + commodity_astro_res["score"] + num.score) / 5, 2
    )

    # Strategy plan — same engine, just routed to MCX
    plan = strategy_eng.select(
        symbol=sym, spot=spot, direction=direction, confidence=confidence,
        atr=tech.indicators["atr14"], iv_pct=20.0,
        horizon=horizon, capital=capital, is_fno=True,
    )

    hora_now = hora_eng.current_hora().to_dict()
    gf = gap_forecast.forecast(symbol=sym, df=df,
                                next_session_date=(date.today() + timedelta(days=1)).isoformat()).to_dict()

    return {
        "symbol": sym,
        "exchange": "MCX",
        "display": info["display"],
        "category": info["category"],
        "ruling_planet": info["ruler"],
        "secondary_planet": info["second"],
        "asof": datetime.now().isoformat(),
        "ltp": {
            "ltp": float(df["close"].iloc[-1]),
            "open": float(df["open"].iloc[-1]),
            "high": float(df["high"].iloc[-1]),
            "low":  float(df["low"].iloc[-1]),
            "close": float(df["close"].iloc[-2]) if len(df) > 1 else float(df["close"].iloc[-1]),
        },
        "direction": direction,
        "confidence": confidence,
        "analyzers": {
            "technical":  {"score": round(tech.score, 1), "bias": tech.bias,
                            "reasons": tech.reasons[:5], "indicators": tech.indicators},
            "smc":        {"score": round(smc_res.score, 1), "bias": smc_res.market_structure,
                            "reasons": smc_res.reasons[:4]},
            "gann":       {"score": round(g.score, 1), "bias": g.bias,
                            "nearest_support": g.nearest_support,
                            "nearest_resistance": g.nearest_resistance,
                            "reasons": g.reasons[:3]},
            "fibonacci":  {"score": round(fib.score, 1), "bias": fib.bias,
                            "swing_high": fib.swing_high, "swing_low": fib.swing_low,
                            "nearest_level": fib.nearest_level,
                            "reasons": fib.reasons[:3]},
            "mundane_astro": commodity_astro_res,
            "numerology": {"score": round(num.score, 1), "bias": num.bias,
                            "ruler": num.planetary_ruler,
                            "reasons": num.reasons[:3]},
        },
        "context": {
            "hora": hora_now,
        },
        "strategy": plan.to_dict(),
        "gap_forecast": gf,
    }


# ---------------------------------------------------------------------------
# Scan all commodities and rank
# ---------------------------------------------------------------------------

def _score_one(sym: str, horizon: str, capital: float) -> dict | None:
    try:
        df = get_ohlcv(sym, exchange="MCX", periods=120)
        tech = technical.analyze(df)
        g = gann.analyze(tech.indicators["last"])
        fib = fibonacci.analyze(df)
        num = numerology.analyze(sym)
        astro = cu.commodity_astro_match(sym)
        biases = [tech.bias, g.bias, fib.bias, astro["bias"], num.bias]
        bulls = sum(1 for b in biases if b == "BULLISH")
        bears = sum(1 for b in biases if b == "BEARISH")
        direction = "BULLISH" if bulls > bears else "BEARISH" if bears > bulls else "NEUTRAL"
        confidence = round((tech.score + g.score + fib.score + astro["score"] + num.score) / 5, 2)
        info = cu.info(sym)
        return {
            "symbol": sym,
            "display": info["display"],
            "category": info["category"],
            "ruling_planet": info["ruler"],
            "spot": tech.indicators["last"],
            "direction": direction,
            "confidence": confidence,
            "signal": "BUY" if direction == "BULLISH" and confidence >= 60 else
                       "SELL" if direction == "BEARISH" and confidence <= 40 else "NEUTRAL",
            "engines": {
                "technical": {"score": round(tech.score, 1), "bias": tech.bias},
                "gann": {"score": round(g.score, 1), "bias": g.bias},
                "fibonacci": {"score": round(fib.score, 1), "bias": fib.bias},
                "mundane_astro": {"score": astro["score"], "bias": astro["bias"]},
                "numerology": {"score": round(num.score, 1), "bias": num.bias},
            },
            "top_astro_reason": astro["reasons"][0] if astro["reasons"] else None,
        }
    except Exception as e:
        logger.warning("commodity scan failed for {}: {}", sym, e)
        return {"symbol": sym, "error": str(e)}


@router.get("/scan", summary="Scan all MCX commodities and rank")
def scan(user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
                horizon: str = Query("SWING", pattern="^(INTRADAY|SWING|POSITIONAL)$"),
                capital: float = Query(100_000, gt=0),
                min_confidence: float = Query(55.0, ge=0, le=100),
                parallel: int = Query(4, ge=1, le=10)):
    universe = cu.all_commodities()
    asof = datetime.now().isoformat()
    results: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_score_one, sym, horizon, capital): sym for sym in universe}
        for fut in as_completed(futures):
            r = fut.result()
            if r is None:
                continue
            if "error" in r:
                errors.append(f"{r['symbol']}: {r['error']}")
            else:
                results.append(r)

    buys = [r for r in results if r["signal"] == "BUY" and r["confidence"] >= min_confidence]
    sells = [r for r in results if r["signal"] == "SELL"]
    buys.sort(key=lambda x: -x["confidence"])
    sells.sort(key=lambda x: x["confidence"])

    # Group by category
    by_category: dict[str, list] = {}
    for r in results:
        by_category.setdefault(r["category"], []).append({
            "symbol": r["symbol"], "display": r["display"],
            "confidence": r["confidence"], "direction": r["direction"],
            "ruling_planet": r["ruling_planet"],
        })

    return {
        "asof": asof,
        "universe_size": len(universe),
        "scanned": len(results),
        "min_confidence": min_confidence,
        "horizon": horizon,
        "top_buy": buys,
        "top_sell": sells,
        "by_category": by_category,
        "errors": errors,
        "disclaimer": (
            "MCX commodity scan. Uses Mundane astrology (planetary rulership) "
            "in place of equity letter-vibration. Verify each signal before "
            "deploying capital. Not SEBI-registered advice."
        ),
    }
