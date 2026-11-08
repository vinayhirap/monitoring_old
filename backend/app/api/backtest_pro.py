"""Professional backtesting endpoints."""
from fastapi import APIRouter, HTTPException, Query

from app.engines import backtester_pro
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.get(
    "/run/{symbol}",
    summary="Run pipeline-driven backtest with Sharpe/Sortino/Calmar/max-DD",
)
def run(symbol: str,
              periods: int = Query(500, ge=100, le=2000),
              min_confidence: float = Query(60, ge=0, le=100),
              risk_per_trade_pct: float = Query(1.0, gt=0, le=10),
              starting_capital: float = Query(100_000, gt=0)):
    try:
        df = get_ohlcv(symbol, periods=periods)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {symbol}")
        signals = backtester_pro.generate_signals_from_pipeline(
            df, symbol, min_confidence=min_confidence,
        )
        return backtester_pro.backtest(
            symbol=symbol, df=df, signals=signals,
            starting_capital=starting_capital,
            risk_per_trade_pct=risk_per_trade_pct,
        ).to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"backtest_pro failed: {e}")
