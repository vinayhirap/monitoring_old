"""Portfolio risk endpoints — aggregate position exposure, daily P&L,
and the daily-loss-limit gate."""
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.brokers.angelone import broker_instance
from app.config import settings
from app.database import get_db
from app.models.trade import Trade
from app.services import risk as risk_svc

router = APIRouter()


@router.get("/snapshot", summary="Live risk snapshot — exposure, P&L, headroom, limits")
async def snapshot(capital: float = Query(100_000, gt=0), db: Session = Depends(get_db)):
    """Aggregate portfolio risk in one call. Combines:
       • broker positions (live or paper) for current exposure
       • today's filled trades from local DB for realized P&L
       • settings.risk_max_* for limits and headroom
    """
    try:
        positions = broker_instance.positions() or []
    except Exception:
        positions = []

    exposure_inr = 0.0
    unrealized_pnl = 0.0
    by_symbol: dict[str, dict] = {}
    for p in positions:
        try:
            qty = abs(int(p.get("netqty") or 0))
            avg = float(p.get("avgnetprice") or 0)
            ltp = float(p.get("ltp") or avg)
            sym = p.get("tradingsymbol", "?")
            ex = qty * avg
            pnl = float(p.get("pnl") or ((ltp - avg) * (int(p.get("netqty") or 0))))
            exposure_inr += ex
            unrealized_pnl += pnl
            by_symbol[sym] = {
                "symbol": sym, "qty": int(p.get("netqty") or 0),
                "avg": avg, "ltp": ltp, "exposure": round(ex, 2),
                "pnl": round(pnl, 2), "paper": bool(p.get("paper")),
            }
        except Exception:
            continue

    # Realized P&L today (from local trade log)
    today = date.today()
    realized_today = 0.0
    trade_count_today = 0
    rows = db.query(Trade).filter(Trade.created_at >= datetime.combine(today, datetime.min.time())).all()
    for r in rows:
        realized_today += float(r.pnl or 0)
        trade_count_today += 1

    total_pnl_today = realized_today + unrealized_pnl
    exposure_pct = (exposure_inr / capital * 100) if capital else 0
    max_exposure_pct = settings.risk_max_position_pct * 4   # rule of thumb: up to 4 max-positions
    max_daily_loss = capital * (settings.risk_max_daily_loss_pct / 100)
    breach = risk_svc.daily_loss_breach(total_pnl_today, capital)
    headroom_inr = max(0.0, max_daily_loss + min(0, total_pnl_today))

    return {
        "asof": datetime.now().isoformat(),
        "capital": capital,
        "exposure_inr": round(exposure_inr, 2),
        "exposure_pct": round(exposure_pct, 2),
        "exposure_pct_limit": round(max_exposure_pct, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "realized_pnl_today": round(realized_today, 2),
        "total_pnl_today": round(total_pnl_today, 2),
        "total_pnl_pct_today": round(total_pnl_today / capital * 100, 3) if capital else 0,
        "trade_count_today": trade_count_today,
        "daily_loss_limit_inr": round(max_daily_loss, 2),
        "headroom_inr": round(headroom_inr, 2),
        "daily_loss_breached": breach,
        "max_position_pct": settings.risk_max_position_pct,
        "max_daily_loss_pct": settings.risk_max_daily_loss_pct,
        "positions": list(by_symbol.values()),
        "warning": (
            "DAILY LOSS LIMIT BREACHED — further entries blocked by the risk gate."
            if breach else None
        ),
    }


@router.get("/can-trade", summary="Should a new entry be allowed right now?")
async def can_trade(capital: float = Query(100_000, gt=0), db: Session = Depends(get_db)):
    snap = await snapshot(capital=capital, db=db)
    return {
        "allowed": not snap["daily_loss_breached"]
                    and snap["exposure_pct"] < snap["exposure_pct_limit"],
        "reasons": ([] if not snap["daily_loss_breached"] else ["daily loss limit breached"])
                    + ([] if snap["exposure_pct"] < snap["exposure_pct_limit"] else ["max portfolio exposure reached"]),
        "snapshot": snap,
    }
