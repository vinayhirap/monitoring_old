"""Live signals — runs the decision engine across a watchlist."""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.engines import decision
from app.models.signal import Signal
from app.services.market_data import get_ohlcv

router = APIRouter()

DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "ITC", "LT", "AXISBANK", "BAJFINANCE",
    "NIFTY", "BANKNIFTY",
]


@router.get("/live", summary="Run decision engine on a watchlist (paper mode safe)")
async def live_signals(
    symbols: str | None = Query(None, description="Comma-separated symbols; default = top 12"),
    horizon: str = "SWING",
    capital: float = 100_000,
    persist: bool = False,
    db: Session = Depends(get_db),
):
    syms = [s.strip().upper() for s in (symbols.split(",") if symbols else DEFAULT_WATCHLIST) if s.strip()]
    out = []
    for sym in syms:
        try:
            df = get_ohlcv(sym, periods=250)
            res = decision.aggregate(symbol=sym, df=df, horizon=horizon, capital=capital)
            out.append(res)
            if persist:
                row = Signal(
                    symbol=sym,
                    signal=res["signal"],
                    trend=res["trend"],
                    confidence=res["confidence"],
                    entry=res["entry"],
                    stoploss=res["stoploss"],
                    targets=res["targets"],
                    risk_reward=res["risk_reward"],
                    capital_allocation_pct=res["capital_allocation_pct"],
                    technical_score=res["engines"]["technical"]["score"],
                    astro_score=res["engines"]["astrology"]["score"],
                    gann_score=res["engines"]["gann"]["score"],
                    numerology_score=res["engines"]["numerology"]["score"],
                    options_score=res["engines"]["options"]["score"],
                    reasons=res["reasons"],
                    horizon=horizon,
                )
                db.add(row)
        except Exception as e:
            out.append({"symbol": sym, "error": str(e)})
    if persist:
        db.commit()
    return {"count": len(out), "signals": out}


@router.get("/recent", summary="Recently persisted signals")
async def recent_signals(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(Signal).order_by(Signal.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "symbol": r.symbol, "signal": r.signal, "trend": r.trend,
            "confidence": r.confidence, "entry": r.entry, "stoploss": r.stoploss,
            "targets": r.targets, "rr": r.risk_reward,
            "scores": {
                "technical": r.technical_score, "astro": r.astro_score,
                "gann": r.gann_score, "numerology": r.numerology_score,
                "options": r.options_score,
            },
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
