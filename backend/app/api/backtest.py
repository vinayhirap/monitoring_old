"""Backtest endpoints — honest historical accuracy reporting."""
from fastapi import APIRouter, HTTPException, Query

from app.engines import backtest
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.get("/run/{symbol}", summary="Run walk-forward backtest on a single symbol")
def run_backtest(
    symbol: str,
    lookback_bars: int = Query(180, ge=30, le=500),
    warmup_bars: int = Query(60, ge=20, le=200),
    confidence_threshold: float = Query(65.0, ge=0, le=100),
    atr_sl_mult: float = Query(1.5, gt=0),
    atr_target_mult: float = Query(3.0, gt=0),
    max_bars_held: int = Query(15, ge=1, le=100),
):
    try:
        df = get_ohlcv(symbol, periods=lookback_bars + warmup_bars + 30)
        report = backtest.run(
            symbol=symbol.upper(),
            df=df,
            lookback_bars=lookback_bars,
            warmup_bars=warmup_bars,
            confidence_threshold=confidence_threshold,
            atr_sl_mult=atr_sl_mult,
            atr_target_mult=atr_target_mult,
            max_bars_held=max_bars_held,
        )
        return report.to_dict()
    except Exception as e:
        raise HTTPException(500, f"backtest failed: {e}")


@router.get("/batch", summary="Backtest a list of symbols and return summary stats")
def batch_backtest(
    symbols: str = Query(..., description="Comma-separated"),
    lookback_bars: int = 180,
    confidence_threshold: float = 65.0,
):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out = []
    for sym in syms:
        try:
            df = get_ohlcv(sym, periods=lookback_bars + 100)
            report = backtest.run(
                symbol=sym, df=df,
                lookback_bars=lookback_bars,
                confidence_threshold=confidence_threshold,
            )
            out.append({
                "symbol": sym,
                "total_trades": report.total_trades,
                "hit_rate": report.hit_rate,
                "profit_factor": report.profit_factor,
                "expectancy_pct": report.expectancy_pct,
                "total_return_pct": report.total_return_pct,
                "max_drawdown_pct": report.max_drawdown_pct,
            })
        except Exception as e:
            out.append({"symbol": sym, "error": str(e)})
    # rank by profit factor desc
    valid = [r for r in out if "error" not in r]
    valid.sort(key=lambda r: -(r["profit_factor"] if r["profit_factor"] != float("inf") else 999))
    return {"results": valid, "errors": [r for r in out if "error" in r]}
