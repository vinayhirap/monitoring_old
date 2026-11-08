"""Advanced+ analysis endpoints: multi-timeframe + sector heatmap."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.engines import mtf, decision
from app.services.market_data import get_ohlcv
from app.services.universe import SECTORS, sector_of

router = APIRouter()


@router.get("/mtf/{symbol}", summary="Multi-timeframe (Daily / Weekly / Monthly) agreement")
def multi_timeframe(symbol: str, periods: int = Query(500, ge=200, le=2000)):
    try:
        df = get_ohlcv(symbol.upper(), periods=periods)
        return {"symbol": symbol.upper(), **mtf.analyze(df)}
    except Exception as e:
        raise HTTPException(500, f"mtf failed: {e}")


@router.get("/sectors/heatmap", summary="Sector rotation heatmap — bullish vs bearish stock counts per sector")
def sector_heatmap(parallel: int = Query(6, ge=1, le=16)):
    """For every sector, runs decision.aggregate on each constituent and
    aggregates how many came back bullish vs bearish. Surface as a heatmap
    to spot rotation (e.g. money rotating out of IT into Banking).
    """
    def _score_one(sym: str):
        try:
            df = get_ohlcv(sym, periods=200)
            r = decision.aggregate(symbol=sym, df=df)
            return sym, r["signal"], r["confidence"]
        except Exception as e:
            logger.debug("sector heatmap {} failed: {}", sym, e)
            return sym, "ERROR", 0

    sector_data = []
    for sector_name, symbols in SECTORS.items():
        bulls, bears, neutral, total_conf, count = 0, 0, 0, 0.0, 0
        top = []
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = {pool.submit(_score_one, s): s for s in symbols}
            for fut in as_completed(futures):
                try:
                    sym, sig, conf = fut.result()
                except Exception:
                    continue
                if sig in ("BUY", "STRONG_BUY"):
                    bulls += 1
                elif sig in ("SELL", "STRONG_SELL"):
                    bears += 1
                else:
                    neutral += 1
                total_conf += conf
                count += 1
                top.append({"symbol": sym, "signal": sig, "confidence": conf})
        avg_conf = round(total_conf / max(1, count), 2)
        top.sort(key=lambda x: -x["confidence"])
        sector_data.append({
            "sector": sector_name,
            "count": count,
            "bulls": bulls, "bears": bears, "neutral": neutral,
            "net_bias": bulls - bears,
            "avg_confidence": avg_conf,
            "top_3": top[:3],
        })
    sector_data.sort(key=lambda s: -s["net_bias"])
    return {"sectors": sector_data, "total_sectors": len(sector_data)}
