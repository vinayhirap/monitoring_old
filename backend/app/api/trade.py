"""Trade execution + portfolio endpoints.

Public surface:

  POST   /api/trade/place              place an order (paper or live)
  GET    /api/trade/orders             user's recent orders
  GET    /api/trade/positions          user's open positions + unrealized P&L
  GET    /api/trade/fills              recent fills (history of executed trades)
  GET    /api/trade/orders/{id}        single order detail
  DELETE /api/trade/orders/{id}        cancel an outstanding order

All endpoints are auth-gated (require_tier BASIC) and operate per-user —
one user cannot see another user's orders/positions.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, require_tier
from app.models.trade_execution import Order, Position, TradeFill
from app.models.user import User
from app.services import trade_executor
from app.services.market_data import get_ohlcv

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PlaceOrderRequest(BaseModel):
    """Trade intent as submitted by the user/UI. Mirrors OrderIntent but
    excludes user_id (filled from auth context).

    Every order is LIVE. There is no paper-mode parameter. The user must
    have `trading_enabled=true` on their account for the order to be
    accepted — otherwise the executor refuses with TRADING_DISABLED.

    For F&O option orders, set `option_strike` + `option_type` + `option_expiry`
    and the executor will resolve the broker tradingsymbol automatically. In
    that case, `symbol` is interpreted as the UNDERLYING (e.g. "NIFTY") and
    `exchange` is forced to "NFO".
    """
    symbol: str = Field(..., min_length=1, max_length=32)
    exchange: str = Field("NSE", max_length=8)
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    product_type: str = Field("DELIVERY", pattern="^(DELIVERY|INTRADAY|MARGIN|MIS|CNC|NRML)$")
    order_type: str = Field("MARKET", pattern="^(MARKET|LIMIT|SL|SL-M)$")
    price: Optional[float] = Field(None, gt=0)
    trigger_price: Optional[float] = Field(None, gt=0)
    stoploss: Optional[float] = Field(None, gt=0)
    target_1: Optional[float] = Field(None, gt=0)
    target_2: Optional[float] = Field(None, gt=0)
    target_3: Optional[float] = Field(None, gt=0)
    source_signal_id: Optional[int] = None
    source_type: str = Field("MANUAL", pattern="^(MANUAL|AUTO_SIGNAL)$")
    capital: float = Field(100_000, gt=0,
                             description="User's trading capital — used by risk-guard for position sizing")

    # ---- Option-contract meta (only for F&O orders) ----
    option_strike: Optional[float] = Field(None, gt=0,
                                             description="Option strike price — required for CE/PE orders")
    option_type:   Optional[str]   = Field(None, pattern="^(CE|PE)$",
                                             description="CE (call) or PE (put)")
    option_expiry: Optional[str]   = Field(None,
                                             pattern=r"^\d{4}-\d{2}-\d{2}$",
                                             description="ISO date YYYY-MM-DD")


class MultiLegOrderRequest(BaseModel):
    """Multi-leg order intent for option spreads, condors, straddles.

    Each leg is a self-contained PlaceOrderRequest. The executor places them
    atomically — if any leg fails after others are placed, the placed ones
    are auto-reversed (saga rollback).

    Use cases:
      • BULL_CALL_SPREAD = [BUY ATM CE, SELL OTM CE]
      • BEAR_PUT_SPREAD  = [BUY ATM PE, SELL OTM PE]
      • LONG_STRADDLE    = [BUY ATM CE, BUY ATM PE]
      • IRON_CONDOR      = [SELL OTM CE, BUY further-OTM CE, SELL OTM PE, BUY further-OTM PE]
    """
    legs: list[PlaceOrderRequest] = Field(..., min_length=2, max_length=8,
                                            description="2-8 leg basket")
    strategy_name: Optional[str] = Field(None, max_length=64,
                                           description="Display label e.g. 'BULL_CALL_SPREAD'")


class TradingToggleRequest(BaseModel):
    """Per-user trading kill switch."""
    enabled: bool


class ModifyOrderRequest(BaseModel):
    """Partial-update for an existing OPEN/PARTIAL order. All fields optional —
    only the fields supplied are changed.

    Broker-side fields (price, qty, trigger) require a broker.modify_order
    call. Companion fields (sl, t1) update locally only.
    """
    quantity:      Optional[int]   = Field(None, gt=0)
    price:         Optional[float] = Field(None, gt=0)
    trigger_price: Optional[float] = Field(None, gt=0)
    stoploss:      Optional[float] = Field(None, gt=0)
    target_1:      Optional[float] = Field(None, gt=0)


# ---------------------------------------------------------------------------
# Place order
# ---------------------------------------------------------------------------

@router.post("/place",
              summary="Place a trade order (paper or live) with full safety pipeline")
def place_order(req: PlaceOrderRequest,
                 user: Annotated[User, Depends(require_tier("BASIC"))],
                 db: Annotated[Session, Depends(get_db)]):
    """Submit an order. Flow:

      1. Auth — user must be BASIC tier or above (FREE cannot trade)
      2. Pre-trade risk gate (position sizing, R:R, portfolio cap, loss circuit breaker)
      3. Idempotency check (30s window prevents double-clicks)
      4. Order row created in DB BEFORE broker contact
      5. If risk passes → submit to broker (or simulate if paper)
      6. Response includes risk-guard verdict + order_id + status

    Never returns success without a corresponding DB record. The order_id
    can be used in subsequent /orders/{id} or DELETE /orders/{id} calls.
    """
    intent = trade_executor.OrderIntent(
        user_id=user.id,
        symbol=req.symbol.upper().strip(),
        exchange=req.exchange,
        direction=req.direction,
        quantity=req.quantity,
        product_type=req.product_type,
        order_type=req.order_type,
        price=req.price,
        trigger_price=req.trigger_price,
        stoploss=req.stoploss,
        target_1=req.target_1,
        target_2=req.target_2,
        target_3=req.target_3,
        source_signal_id=req.source_signal_id,
        source_type=req.source_type,
        capital=req.capital,
        option_strike=req.option_strike,
        option_type=req.option_type,
        option_expiry=req.option_expiry,
    )

    result = trade_executor.execute(db, intent)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Place multi-leg order (option spreads, condors, straddles)
# ---------------------------------------------------------------------------

@router.post("/place-multi-leg",
              summary="Place an N-leg option strategy atomically (BULL_CALL_SPREAD, IRON_CONDOR, etc.)")
def place_multi_leg(req: MultiLegOrderRequest,
                     user: Annotated[User, Depends(require_tier("INTERMEDIATE"))],
                     db: Annotated[Session, Depends(get_db)]):
    """Place 2–8 related legs as one atomic basket.

    Behavior:
      • Tier-gated to INTERMEDIATE+ (F&O strategies)
      • All legs validated upfront — bad input = nothing placed
      • Legs placed sequentially with a shared `multi_leg_group_id`
      • If any leg fails AFTER others succeeded → already-placed legs are
        automatically reversed (opposing market orders) so the user is not
        left with a naked exposure they didn't ask for
      • Returns the group_id + per-leg ExecutionResults so the UI can render
        the basket as one trade card

    On rollback failure (e.g. broker session drops mid-rollback), the
    response contains rolled_back_count < placed_count plus a clear message
    so the user knows to intervene manually.
    """
    intents = [
        trade_executor.OrderIntent(
            user_id=user.id,
            symbol=leg.symbol.upper().strip(),
            exchange=leg.exchange,
            direction=leg.direction,
            quantity=leg.quantity,
            product_type=leg.product_type,
            order_type=leg.order_type,
            price=leg.price,
            trigger_price=leg.trigger_price,
            stoploss=leg.stoploss,
            target_1=leg.target_1,
            target_2=leg.target_2,
            target_3=leg.target_3,
            source_signal_id=leg.source_signal_id,
            source_type=leg.source_type,
            capital=leg.capital,
            option_strike=leg.option_strike,
            option_type=leg.option_type,
            option_expiry=leg.option_expiry,
        )
        for leg in req.legs
    ]

    result = trade_executor.execute_multi_leg(db, intents)
    return {
        **result.to_dict(),
        "strategy_name": req.strategy_name,
    }


@router.get("/multi-leg/{group_id}",
              summary="Look up all legs of a multi-leg basket")
def get_multi_leg_group(group_id: str,
                         user: Annotated[User, Depends(get_current_user)],
                         db: Annotated[Session, Depends(get_db)]):
    """Returns every Order row tagged with this multi_leg_group_id, ordered by
    leg_index. Used by the UI to render the basket as a single card with all
    legs' status."""
    from app.models.trade_execution import Order as _Order
    rows = (
        db.query(_Order)
          .filter(_Order.user_id == user.id, _Order.multi_leg_group_id == group_id)
          .order_by(_Order.leg_index.asc().nullslast(), _Order.id.asc())
          .all()
    )
    if not rows:
        raise HTTPException(404, f"No multi-leg basket found with group_id={group_id}")
    return {
        "group_id": group_id,
        "leg_count": sum(1 for r in rows if r.leg_index is not None),
        "rollback_count": sum(1 for r in rows
                                if r.leg_index is None and (r.source_type or "").startswith("ROLLBACK:")),
        "legs": [
            {
                "id":              r.id,
                "leg_index":       r.leg_index,
                "symbol":          r.symbol,
                "direction":       r.direction,
                "quantity":        r.quantity,
                "status":          r.status,
                "client_order_id": r.client_order_id,
                "broker_order_id": r.broker_order_id,
                "filled_quantity": r.filled_quantity,
                "avg_fill_price":  r.avg_fill_price,
                "is_rollback":     (r.source_type or "").startswith("ROLLBACK:"),
                "notes":           r.notes,
                "placed_at":       r.placed_at.isoformat() if r.placed_at else None,
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# Trading kill switch
# ---------------------------------------------------------------------------

@router.get("/status", summary="Is trading currently enabled for this user?")
def trading_status(user: Annotated[User, Depends(get_current_user)]):
    """Lightweight check the UI uses to render the ON/OFF banner.
    Returns the trading_enabled flag + broker auth status (since you can't
    actually trade without both)."""
    from app.brokers.angelone import broker_instance
    return {
        "trading_enabled": bool(user.trading_enabled),
        "broker_authenticated": broker_instance.is_authenticated(),
        "can_place_orders": bool(user.trading_enabled) and broker_instance.is_authenticated(),
        "message": (
            "Trading is ON" if user.trading_enabled
            else "Trading is OFF — orders will be refused. Toggle ON from profile to enable."
        ),
    }


@router.post("/toggle", summary="Turn trading ON/OFF for this user")
def trading_toggle(
    req: TradingToggleRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Per-user kill switch. When OFF, the executor refuses all orders
    outright. When ON, orders flow to the broker (live, real money).

    No re-authentication required to flip — but every flip is audited so
    a user can prove what state they were in at any past time.
    """
    prev = user.trading_enabled
    user.trading_enabled = req.enabled
    db.commit()
    db.refresh(user)

    from app.services import audit
    audit.record(
        actor=user, action="trade.toggle",
        summary=f"Trading {'ENABLED' if req.enabled else 'DISABLED'} by {user.email}",
        target=user,
        details_before={"trading_enabled": prev},
        details_after={"trading_enabled": user.trading_enabled},
    )
    return {
        "trading_enabled": user.trading_enabled,
        "previous":        prev,
        "message":         "Trading is now ON" if user.trading_enabled else "Trading is now OFF",
    }


# ---------------------------------------------------------------------------
# List orders
# ---------------------------------------------------------------------------

@router.get("/orders", summary="List user's recent orders")
def list_orders(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(7, ge=1, le=90),
    status: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
):
    """User's orders in the last N days, newest first. Filterable by status
    and symbol."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = (db.query(Order)
           .filter(Order.user_id == user.id, Order.placed_at >= cutoff)
           .order_by(Order.placed_at.desc()))
    if status:
        q = q.filter(Order.status == status)
    if symbol:
        q = q.filter(Order.symbol == symbol.upper())
    rows = q.limit(limit).all()

    return {
        "count": len(rows),
        "orders": [
            {
                "id": r.id, "client_order_id": r.client_order_id,
                "broker_order_id": r.broker_order_id,
                "symbol": r.symbol, "exchange": r.exchange,
                "direction": r.direction, "quantity": r.quantity,
                "filled_quantity": r.filled_quantity,
                "product_type": r.product_type, "order_type": r.order_type,
                "price": r.price, "trigger_price": r.trigger_price,
                "stoploss": r.stoploss,
                "targets": [r.target_1, r.target_2, r.target_3],
                "avg_fill_price": r.avg_fill_price,
                "status": r.status,
                "is_paper": r.is_paper,
                "placed_at": r.placed_at.isoformat() if r.placed_at else None,
                "filled_at": r.filled_at.isoformat() if r.filled_at else None,
                "realized_pnl": r.realized_pnl,
                "source_type": r.source_type,
                "source_signal_id": r.source_signal_id,
                "notes": r.notes,
            } for r in rows
        ],
    }


@router.get("/orders/{order_id}", summary="Single order detail")
def order_detail(order_id: int,
                  user: Annotated[User, Depends(get_current_user)],
                  db: Annotated[Session, Depends(get_db)]):
    order = (db.query(Order)
               .filter_by(id=order_id, user_id=user.id)
               .one_or_none())
    if not order:
        raise HTTPException(404, "Order not found")
    fills = (db.query(TradeFill)
                .filter_by(order_id=order.id, user_id=user.id)
                .order_by(TradeFill.filled_at)
                .all())
    return {
        "order": {
            "id": order.id, "client_order_id": order.client_order_id,
            "broker_order_id": order.broker_order_id,
            "symbol": order.symbol, "direction": order.direction,
            "quantity": order.quantity, "filled_quantity": order.filled_quantity,
            "product_type": order.product_type, "order_type": order.order_type,
            "price": order.price, "stoploss": order.stoploss,
            "targets": [order.target_1, order.target_2, order.target_3],
            "avg_fill_price": order.avg_fill_price,
            "status": order.status, "is_paper": order.is_paper,
            "placed_at": order.placed_at.isoformat() if order.placed_at else None,
            "filled_at": order.filled_at.isoformat() if order.filled_at else None,
            "risk_guard_snapshot": order.risk_guard_snapshot,
            "broker_response": order.broker_response,
            "notes": order.notes,
        },
        "fills": [
            {"id": f.id, "quantity": f.quantity, "price": f.price,
             "filled_at": f.filled_at.isoformat() if f.filled_at else None,
             "fill_type": f.fill_type, "realized_pnl": f.realized_pnl}
            for f in fills
        ],
    }


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@router.delete("/orders/{order_id}", summary="Cancel an outstanding order")
def cancel_order(order_id: int,
                  user: Annotated[User, Depends(get_current_user)],
                  db: Annotated[Session, Depends(get_db)]):
    result = trade_executor.cancel(db, user.id, order_id)
    if not result.ok:
        # Map common reasons to HTTP codes
        code = 404 if result.rejected_reason == "Order not found" else 400
        raise HTTPException(code, result.message or result.rejected_reason or "Cancel failed")
    return result.to_dict()


@router.get("/cost-estimate",
              summary="All-in cost estimate (brokerage + STT + GST + stamp duty + exchange charges)")
def cost_estimate(
    user: Annotated[User, Depends(get_current_user)],
    entry: float = Query(..., gt=0),
    quantity: int = Query(..., gt=0),
    segment: str = Query("EQUITY_DELIVERY",
                           pattern="^(EQUITY_DELIVERY|EQUITY_INTRADAY|FUTURES|OPTIONS)$"),
    direction: str = Query("BUY", pattern="^(BUY|SELL)$"),
    lot_size: int = Query(1, ge=1),
):
    """Returns the full statutory cost breakdown for a single leg of a trade.

    Use this in the OrderConfirmModal to show users the all-in cost BEFORE
    they confirm. Most users expect notional only and get surprised when
    the broker debits ~0.5% extra in charges.
    """
    from app.services import brokerage_estimator
    return brokerage_estimator.estimate(
        entry=entry, quantity=quantity, segment=segment,
        direction=direction, lot_size=lot_size,
    ).to_dict()


@router.patch("/orders/{order_id}", summary="Modify an OPEN/PARTIAL order")
def modify_order(order_id: int, req: ModifyOrderRequest,
                  user: Annotated[User, Depends(get_current_user)],
                  db: Annotated[Session, Depends(get_db)]):
    """Modify quantity / price / trigger (broker-side) and/or SL/target
    (local). Only OPEN and PARTIAL orders can be modified. Returns
    `result.ok=false` when the order is terminal or broker rejects.
    """
    result = trade_executor.modify(
        db, user.id, order_id,
        quantity=req.quantity, price=req.price,
        trigger_price=req.trigger_price,
        stoploss=req.stoploss, target_1=req.target_1,
    )
    if not result.ok:
        code = 404 if result.rejected_reason == "Order not found" else 400
        raise HTTPException(code, result.message or result.rejected_reason or "Modify failed")
    return result.to_dict()


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@router.get("/positions", summary="User's currently-open positions with live P&L")
def list_positions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Open positions with unrealized P&L computed at read time from LTP."""
    q = db.query(Position).filter_by(user_id=user.id, status="OPEN")
    rows = q.order_by(Position.opened_at.desc()).all()

    out = []
    total_unrealized = 0.0
    for p in rows:
        ltp = _safe_ltp(p.symbol, p.exchange)
        unrealized = (
            (ltp - p.avg_entry_price) * p.net_quantity if ltp and p.avg_entry_price
            else 0.0
        )
        total_unrealized += unrealized
        out.append({
            "id": p.id, "symbol": p.symbol, "exchange": p.exchange,
            "product_type": p.product_type,
            "net_quantity": p.net_quantity,
            "direction": "LONG" if p.net_quantity > 0 else "SHORT",
            "avg_entry_price": p.avg_entry_price,
            "ltp": ltp,
            "unrealized_pnl": round(unrealized, 2),
            "unrealized_pnl_pct": round(unrealized / (abs(p.net_quantity) * p.avg_entry_price) * 100, 2)
                                  if (p.avg_entry_price and p.net_quantity) else 0,
            "current_sl": p.current_sl,
            "current_t1": p.current_t1,
            "current_t2": p.current_t2,
            "current_t3": p.current_t3,
            "realized_pnl": p.realized_pnl,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "is_paper": p.is_paper,
        })

    return {
        "count": len(out),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "positions": out,
    }


def _safe_ltp(symbol: str, exchange: str) -> float:
    try:
        df = get_ohlcv(symbol, exchange=exchange, periods=2)
        return float(df["close"].iloc[-1])
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Fills (trade history)
# ---------------------------------------------------------------------------

@router.get("/fills", summary="User's recent executed trades")
def list_fills(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
    symbol: Optional[str] = None,
    fill_type: Optional[str] = Query(None, pattern="^(OPEN|ADD_TO|REDUCE|CLOSE)$"),
    limit: int = Query(200, ge=1, le=1000),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = (db.query(TradeFill)
           .filter(TradeFill.user_id == user.id, TradeFill.filled_at >= cutoff)
           .order_by(TradeFill.filled_at.desc()))
    if symbol:
        q = q.filter(TradeFill.symbol == symbol.upper())
    if fill_type:
        q = q.filter(TradeFill.fill_type == fill_type)
    rows = q.limit(limit).all()

    total_realized = sum(f.realized_pnl or 0 for f in rows)

    return {
        "count": len(rows),
        "total_realized_pnl": round(total_realized, 2),
        "fills": [
            {
                "id": f.id, "order_id": f.order_id,
                "symbol": f.symbol, "direction": f.direction,
                "quantity": f.quantity, "price": f.price,
                "fill_type": f.fill_type,
                "realized_pnl": f.realized_pnl,
                "filled_at": f.filled_at.isoformat() if f.filled_at else None,
                "is_paper": f.is_paper,
            } for f in rows
        ],
    }


# ---------------------------------------------------------------------------
# Summary KPIs
# ---------------------------------------------------------------------------

@router.get("/summary", summary="Trading summary — open count + P&L roll-up")
def trading_summary(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(30, ge=1, le=365),
):
    cutoff = datetime.utcnow() - timedelta(days=days)
    open_positions = (db.query(Position)
                        .filter_by(user_id=user.id, status="OPEN").count())
    closed_positions = (db.query(Position)
                         .filter(Position.user_id == user.id,
                                  Position.status == "CLOSED",
                                  Position.closed_at >= cutoff).count())
    realized = (db.query(TradeFill)
                  .filter(TradeFill.user_id == user.id,
                           TradeFill.filled_at >= cutoff,
                           TradeFill.fill_type.in_(("REDUCE", "CLOSE"))).all())
    total_realized = sum(f.realized_pnl or 0 for f in realized)
    winning_closes = sum(1 for f in realized if (f.realized_pnl or 0) > 0)
    losing_closes  = sum(1 for f in realized if (f.realized_pnl or 0) < 0)

    return {
        "lookback_days":       days,
        "open_positions":      open_positions,
        "closed_positions":    closed_positions,
        "total_realized_pnl":  round(total_realized, 2),
        "winning_closes":      winning_closes,
        "losing_closes":       losing_closes,
        "win_rate":            round(winning_closes / max(1, winning_closes + losing_closes), 3),
    }
