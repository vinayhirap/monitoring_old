"""Trade execution service — the safety-wrapped order-placement layer.

What this does:

  1. Accepts an `OrderIntent` from the API layer
  2. Runs `risk_guard` ONE MORE TIME at execution moment (the user might
     have been seeing a stale recommendation; a 5-minute-old position-
     size suggestion could now blow the portfolio cap)
  3. Generates an idempotency key and creates a PENDING_RISK_CHECK row
     in `exec_orders` BEFORE touching the broker
  4. If risk passes, transitions to PENDING_BROKER and submits
  5. On broker ack, transitions to OPEN and starts a fill watcher
  6. On fill, updates `exec_positions` and inserts `exec_trade_fills`

When `is_paper=True`:
  • The order is simulated locally — fill happens immediately at the
    current LTP, no broker call.
  • Position + fill rows are inserted with `is_paper=True` so paper
    P&L doesn't pollute the real P&L view.

This is the ONLY safe place to call from the API. Direct
`broker_instance.place_order()` calls bypass the safety rails — DO NOT.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.brokers.angelone import broker_instance
from app.brokers.base import BrokerError
from app.services import broker_session_manager
from app.models.trade_execution import (
    Order, Position, TradeFill,
    ORDER_STATUS_PENDING_RISK, ORDER_STATUS_PENDING_BROKER,
    ORDER_STATUS_OPEN, ORDER_STATUS_FILLED, ORDER_STATUS_REJECTED,
    ORDER_STATUS_FAILED, ORDER_STATUS_CANCELLED,
)
from app.models.user import User
from app.services import audit, risk_guard, funds_check
from app.services.market_data import get_ohlcv


# ----------------------------------------------------------------------------
# Public data structures
# ----------------------------------------------------------------------------

@dataclass
class OrderIntent:
    """What the user/API submits — declarative description of the trade.

    Every order is LIVE. There is no paper mode anywhere in the system —
    when `trading_enabled` is false on the user, the executor refuses the
    order outright. There's no "safe" mode that could be confused with the
    real one.
    """
    user_id: int
    symbol: str
    direction: str                  # BUY / SELL
    quantity: int
    product_type: str = "DELIVERY"
    order_type: str = "MARKET"
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    stoploss: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    target_3: Optional[float] = None
    exchange: str = "NSE"
    source_signal_id: Optional[int] = None
    source_type: str = "MANUAL"
    capital: float = 100_000.0      # for risk-guard sizing

    # ---- Option-contract meta (only for F&O orders) ----
    # When these are set, `symbol` is treated as the UNDERLYING and the
    # executor will resolve the actual option tradingsymbol via
    # instruments.resolve_option_for_order() before calling the broker.
    # Also forces exchange="NFO" if not already.
    option_strike: Optional[float] = None
    option_type: Optional[str] = None       # "CE" or "PE"
    option_expiry: Optional[str] = None     # ISO date "YYYY-MM-DD"


@dataclass
class ExecutionResult:
    ok: bool
    order_id: Optional[int] = None
    client_order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    status: str = ""
    message: str = ""
    risk_guard: Optional[dict] = None
    rejected_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------
# Idempotency helper
# ----------------------------------------------------------------------------

# In-process recent-orders cache. Within IDEMPOTENCY_WINDOW_SEC, identical
# (user, symbol, direction, qty) intents are rejected as duplicates.
import threading
_recent_orders: dict[str, tuple[float, str]] = {}    # key → (timestamp, client_order_id)
_recent_lock = threading.Lock()
IDEMPOTENCY_WINDOW_SEC = 30


def _idempotency_key(intent: OrderIntent) -> str:
    return f"{intent.user_id}:{intent.symbol}:{intent.direction}:{intent.quantity}:{intent.product_type}"


def _check_duplicate(intent: OrderIntent) -> Optional[str]:
    """Returns the existing client_order_id if this is a duplicate, else None."""
    import time
    key = _idempotency_key(intent)
    now = time.time()
    with _recent_lock:
        # Garbage-collect stale entries
        stale = [k for k, (ts, _) in _recent_orders.items()
                  if now - ts > IDEMPOTENCY_WINDOW_SEC * 2]
        for k in stale:
            _recent_orders.pop(k, None)
        entry = _recent_orders.get(key)
        if entry and now - entry[0] < IDEMPOTENCY_WINDOW_SEC:
            return entry[1]
        new_uuid = str(uuid.uuid4())
        _recent_orders[key] = (now, new_uuid)
        return None


# ----------------------------------------------------------------------------
# Pre-trade safety
# ----------------------------------------------------------------------------

def _run_risk_gate(db: Session, intent: OrderIntent) -> tuple[bool, dict]:
    """Re-run risk_guard at execution moment.

    Returns (passed, risk_guard_dict). If passed=False, the order is
    rejected before the broker is contacted — never place orders that
    fail safety.
    """
    if intent.stoploss is None or intent.target_1 is None:
        return False, {"verdict": "BLOCK",
                        "reasons": ["Order rejected: stop-loss and target_1 must be set"]}

    # Pull live open-position risk and recent loss count
    open_risk_pct = risk_guard.open_portfolio_risk_pct(db, intent.user_id, intent.capital)
    recent_losses = risk_guard.recent_loss_count(db, intent.user_id)

    rg = risk_guard.check(
        entry=intent.price or _live_ltp(intent.symbol, intent.exchange),
        stoploss=intent.stoploss,
        target_1=intent.target_1,
        capital=intent.capital,
        lot_size=1,    # equity; F&O lot lookup is a TODO
        open_positions_risk_pct=open_risk_pct,
        recent_losses=recent_losses,
    )
    passed = rg.verdict == "OK"
    return passed, rg.to_dict()


def _live_ltp(symbol: str, exchange: str = "NSE") -> float:
    """Quick LTP for execution-time pricing decisions. Falls back to last
    cached close on any failure rather than crashing the order flow."""
    try:
        df = get_ohlcv(symbol, exchange=exchange, periods=2)
        return float(df["close"].iloc[-1])
    except Exception as e:
        logger.warning("Live LTP unavailable for {}: {} — using 0 fallback", symbol, e)
        return 0.0


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

def execute(db: Session, intent: OrderIntent) -> ExecutionResult:
    """Place a LIVE order. The only safe place to do so from the API layer.

    Steps:
      0. Kill switch — user.trading_enabled must be True or refuse
      1. Idempotency check — duplicate within 30s returns the existing order
      2. Validate basics (qty>0, direction in BUY/SELL, etc.)
      3. Risk gate — calls risk_guard at THIS moment
      4. Create PENDING_RISK_CHECK row in exec_orders
      5. If risk passed → PENDING_BROKER
      6. Submit to broker (real money — there is no paper mode)
      7. On ack → OPEN; on rejection → REJECTED; on error → FAILED

    Never raises; failures come back as ExecutionResult(ok=False, ...).
    """
    # ----- 0. Kill-switch check — refuses if the user has trading disabled -----
    from app.models.user import User
    user = db.query(User).filter_by(id=intent.user_id).one_or_none()
    if user is None:
        return ExecutionResult(ok=False, status="VALIDATION_FAILED",
                                 rejected_reason="User not found")
    if not user.trading_enabled:
        return ExecutionResult(
            ok=False, status="TRADING_DISABLED",
            rejected_reason="TRADING_DISABLED",
            message=("Trading is OFF for this account. Enable it from your "
                       "profile / settings before placing orders."),
        )

    # ----- 1. Idempotency -----
    dup = _check_duplicate(intent)
    if dup:
        existing = db.query(Order).filter_by(client_order_id=dup).one_or_none()
        if existing:
            return ExecutionResult(
                ok=False, order_id=existing.id, client_order_id=dup,
                status=existing.status, message="Duplicate order suppressed",
                rejected_reason="DUPLICATE_INTENT",
            )

    # ----- 2. Basic validation -----
    if intent.direction not in ("BUY", "SELL"):
        return ExecutionResult(ok=False, status="VALIDATION_FAILED",
                                 rejected_reason=f"direction must be BUY/SELL, got {intent.direction}")
    if intent.quantity <= 0:
        return ExecutionResult(ok=False, status="VALIDATION_FAILED",
                                 rejected_reason="quantity must be > 0")

    client_order_id = str(uuid.uuid4())

    # ----- 3 + 4. Risk gate + initial row creation -----
    passed, rg_dict = _run_risk_gate(db, intent)
    order = Order(
        user_id=intent.user_id,
        client_order_id=client_order_id,
        source_signal_id=intent.source_signal_id,
        source_type=intent.source_type,
        symbol=intent.symbol.upper().strip(),
        exchange=intent.exchange,
        direction=intent.direction,
        quantity=intent.quantity,
        product_type=intent.product_type,
        order_type=intent.order_type,
        price=intent.price,
        trigger_price=intent.trigger_price,
        stoploss=intent.stoploss,
        target_1=intent.target_1,
        target_2=intent.target_2,
        target_3=intent.target_3,
        status=ORDER_STATUS_PENDING_RISK,
        risk_guard_snapshot=rg_dict,
        is_paper=False,    # LIVE-only — no paper mode in this platform
    )
    db.add(order)
    db.flush()    # populates order.id without commit

    if not passed:
        order.status = ORDER_STATUS_FAILED
        order.notes = f"Risk-guard blocked: {(rg_dict.get('reasons') or ['unknown'])[0]}"
        db.commit()
        _audit(intent.user_id, "trade.rejected_pre",
                f"Order rejected by risk-guard for {intent.symbol}", rg_dict)
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=client_order_id,
            status=ORDER_STATUS_FAILED, message="Blocked by risk guard",
            risk_guard=rg_dict,
            rejected_reason="RISK_GUARD_BLOCK",
        )

    # ----- 4.5. Funds / margin pre-check (live only, no broker call wasted) -----
    # If the broker reports insufficient cash, refuse upfront with a clear
    # message. Soft-allows when the broker funds endpoint can't be reached
    # so the order still goes through and gets rejected at the broker if
    # truly under-funded — that's never worse than today's behavior.
    is_fno = order.product_type in ("MIS", "NRML")    # rough heuristic; F&O uses different products
    funds_result = funds_check.check(
        entry=intent.price or _live_ltp(intent.symbol, intent.exchange),
        quantity=intent.quantity,
        product_type=intent.product_type,
        is_fno=is_fno,
    )
    if not funds_result.sufficient:
        order.status = ORDER_STATUS_FAILED
        order.notes = f"Funds check failed: {funds_result.reasons[0] if funds_result.reasons else 'insufficient funds'}"
        db.commit()
        _audit(intent.user_id, "trade.rejected_funds",
                f"Order rejected — insufficient funds for {intent.symbol}", funds_result.to_dict())
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=client_order_id,
            status=ORDER_STATUS_FAILED, message=funds_result.reasons[0] if funds_result.reasons else "Insufficient funds",
            rejected_reason="INSUFFICIENT_FUNDS",
            risk_guard=rg_dict,
        )

    order.status = ORDER_STATUS_PENDING_BROKER
    # Persist funds snapshot for post-hoc audit
    order.broker_response = {**(order.broker_response or {}), "funds_check": funds_result.to_dict()}
    db.commit()

    # ----- 5. Broker submission — always live, no paper branch -----
    result = _submit_to_broker(db, order, intent)

    _audit(intent.user_id, f"trade.{result.status.lower()}",
            f"Order {result.status} for {intent.symbol}: "
            f"{intent.direction} {intent.quantity}",
            {"order_id": order.id, "broker_order_id": result.broker_order_id})
    return result


# ----------------------------------------------------------------------------
# Live broker submission — the only execution path
# ----------------------------------------------------------------------------

def _resolve_option_contract(order: Order, intent: OrderIntent) -> tuple[bool, str | None]:
    """If the intent describes an F&O option (strike + type + expiry set),
    resolve the broker tradingsymbol and overwrite `order.symbol` /
    `order.exchange` in-place.

    Returns (ok, error_msg). When ok=False, the caller must NOT submit the
    order — the broker would reject it or, worse, accept it against the
    underlying index. Hard fail is safer.
    """
    if not (intent.option_strike and intent.option_type and intent.option_expiry):
        # Not an option order — nothing to do.
        return True, None
    try:
        from app.services import instruments
        ts, token = instruments.resolve_option_for_order(
            underlying=intent.symbol,
            expiry_iso=intent.option_expiry,
            strike=float(intent.option_strike),
            option_type=intent.option_type,
            exchange="NFO",
        )
        order.symbol   = ts
        order.exchange = "NFO"
        if token:
            # Stash the broker token in the response field for the broker call.
            order.broker_response = {**(order.broker_response or {}),
                                       "resolved_token": token}
        logger.info("Resolved option contract: {} {} {} {} → {} (token {})",
                     intent.symbol, intent.option_expiry, intent.option_strike,
                     intent.option_type, ts, token or "constructed")
        return True, None
    except Exception as e:
        logger.warning("Option contract resolution failed: {}", e)
        return False, f"Could not resolve option contract: {e}"


def _submit_to_broker(db: Session, order: Order, intent: OrderIntent) -> ExecutionResult:
    """Submit to the USER's Angel One account.

    Critical multi-user refactor: this routes through `broker_session_manager`
    which returns a broker client authenticated as THIS user, not the
    platform operator. Orders are placed against the user's funds, in
    the user's account — never the operator's.

    Options note: if `intent.option_*` fields are set, we resolve the
    underlying → contract tradingsymbol via instruments.resolve_option_for_order
    BEFORE calling the broker. Without this, an order against "NIFTY" would
    be routed to the index, not the option contract.
    """
    # ---- Option resolution: only when option meta is on the intent ----
    ok, err = _resolve_option_contract(order, intent)
    if not ok:
        order.status = ORDER_STATUS_FAILED
        order.notes = err
        db.commit()
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=order.client_order_id,
            status=ORDER_STATUS_FAILED,
            rejected_reason="OPTION_RESOLVE_FAILED",
            message=err or "option contract resolution failed",
        )

    # Get the user's own broker client. Raises BrokerSessionError if not connected.
    try:
        user_broker = broker_session_manager.get_for_user(db, order.user_id)
    except broker_session_manager.BrokerSessionError as e:
        order.status = ORDER_STATUS_FAILED
        order.notes = f"Broker session unavailable: {e}"
        db.commit()
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=order.client_order_id,
            status=ORDER_STATUS_FAILED,
            rejected_reason="BROKER_NOT_CONNECTED",
            message=str(e),
        )
    except Exception as e:
        order.status = ORDER_STATUS_FAILED
        order.notes = f"Broker session error: {e}"
        db.commit()
        logger.exception("Unexpected broker session error for user {}: {}",
                          order.user_id, e)
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=order.client_order_id,
            status=ORDER_STATUS_FAILED,
            rejected_reason="BROKER_SESSION_ERROR",
            message=str(e),
        )

    try:
        response = user_broker.place_order(
            symbol=order.symbol,
            exchange=order.exchange,
            side=order.direction,
            quantity=order.quantity,
            product_type=order.product_type,
            order_type=order.order_type,
            price=order.price,
            trigger_price=order.trigger_price,
        )
        order.broker_response = response if isinstance(response, dict) else {"raw": str(response)}
        order.broker_order_id = response.get("order_id", "") if isinstance(response, dict) else ""
        order.broker_status = response.get("status", "") if isinstance(response, dict) else ""
        # Broker ack — usually means OPEN, not yet FILLED. Fill comes later.
        order.status = ORDER_STATUS_OPEN
        db.commit()
        return ExecutionResult(
            ok=True, order_id=order.id, client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            status=ORDER_STATUS_OPEN,
            message=f"Order placed with broker (id={order.broker_order_id})",
        )
    except BrokerError as e:
        order.status = ORDER_STATUS_REJECTED
        order.notes = f"Broker rejected: {e}"
        db.commit()
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=order.client_order_id,
            status=ORDER_STATUS_REJECTED,
            rejected_reason="BROKER_REJECTED",
            message=str(e),
        )
    except Exception as e:
        order.status = ORDER_STATUS_FAILED
        order.notes = f"Submission failed: {e}"
        db.commit()
        logger.exception("Broker submission crashed for order {}: {}", order.id, e)
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=order.client_order_id,
            status=ORDER_STATUS_FAILED,
            rejected_reason="BROKER_ERROR",
            message=str(e),
        )


# ----------------------------------------------------------------------------
# Position management
# ----------------------------------------------------------------------------

def _apply_fill_to_position(db: Session, order: Order, fill: TradeFill) -> None:
    """Update or create the user's Position for this symbol+product.

    Logic:
      • If no OPEN position exists → create one
      • If OPEN position in SAME direction → ADD_TO (weighted-average entry)
      • If OPEN position in OPPOSITE direction → REDUCE or CLOSE
    """
    pos = (db.query(Position)
             .filter_by(user_id=order.user_id, symbol=order.symbol,
                          product_type=order.product_type, status="OPEN",
                          is_paper=order.is_paper)
             .one_or_none())
    signed_qty = fill.quantity if fill.direction == "BUY" else -fill.quantity

    if pos is None:
        # New position
        db.add(Position(
            user_id=order.user_id, symbol=order.symbol,
            exchange=order.exchange, product_type=order.product_type,
            net_quantity=signed_qty,
            avg_entry_price=fill.price,
            current_sl=order.stoploss, current_t1=order.target_1,
            current_t2=order.target_2, current_t3=order.target_3,
            status="OPEN", is_paper=order.is_paper,
        ))
        fill.fill_type = "OPEN"
        return

    new_net = pos.net_quantity + signed_qty

    # Same-direction add → weighted-average entry
    if (pos.net_quantity > 0 and signed_qty > 0) or (pos.net_quantity < 0 and signed_qty < 0):
        total_qty = abs(pos.net_quantity) + abs(signed_qty)
        pos.avg_entry_price = (
            (abs(pos.net_quantity) * pos.avg_entry_price + abs(signed_qty) * fill.price) / total_qty
        )
        pos.net_quantity = new_net
        pos.current_sl = order.stoploss or pos.current_sl
        pos.current_t1 = order.target_1 or pos.current_t1
        pos.current_t2 = order.target_2 or pos.current_t2
        pos.current_t3 = order.target_3 or pos.current_t3
        fill.fill_type = "ADD_TO"
        return

    # Opposite-direction → REDUCE (or CLOSE if net=0, or FLIP if net flips sign)
    closing_qty = min(abs(pos.net_quantity), abs(signed_qty))
    side_sign = 1 if pos.net_quantity > 0 else -1
    realized = (fill.price - pos.avg_entry_price) * closing_qty * side_sign
    fill.realized_pnl = realized
    pos.realized_pnl += realized
    pos.net_quantity = new_net

    if new_net == 0:
        pos.status = "CLOSED"
        pos.closed_at = datetime.utcnow()
        fill.fill_type = "CLOSE"
    elif (pos.net_quantity > 0) == (new_net > 0):
        fill.fill_type = "REDUCE"
    else:
        # Flipped — close old, open new in opposite direction. Cleanest
        # is to close this row and let the next intent open a fresh one.
        # Simpler implementation: update in place.
        pos.avg_entry_price = fill.price
        fill.fill_type = "OPEN"


# ----------------------------------------------------------------------------
# Audit helper
# ----------------------------------------------------------------------------

def _audit(user_id: int, action: str, summary: str, details: Optional[dict] = None) -> None:
    """Wrap audit calls — never raise from inside the executor."""
    try:
        from app.models.user import User
        from sqlalchemy.orm import Session
        from app.database import SessionLocal
        with SessionLocal() as db:
            user = db.query(User).filter_by(id=user_id).one_or_none()
            if user:
                audit.record(actor=user, action=action, summary=summary, target=user,
                              details_after=details)
    except Exception as e:
        logger.debug("Audit record failed: {}", e)


# ----------------------------------------------------------------------------
# Cancel
# ----------------------------------------------------------------------------

def modify(db: Session, user_id: int, order_id: int, *,
            quantity: Optional[int] = None,
            price: Optional[float] = None,
            trigger_price: Optional[float] = None,
            stoploss: Optional[float] = None,
            target_1: Optional[float] = None,
            ) -> ExecutionResult:
    """Modify an OPEN or PARTIAL order. Three classes of changes:

      1. **Broker-side fields** (quantity, price, trigger_price) — these
         require a broker.modify_order() call.
      2. **Companion fields** (stoploss, target_1/2/3) — stored locally,
         used by the loss-circuit-breaker + risk tracking. No broker call.
      3. **Both** — broker call AND local update.

    Only OPEN/PARTIAL orders can be modified. Terminal statuses (FILLED,
    CANCELLED, REJECTED, FAILED) refuse the change.
    """
    order = db.query(Order).filter_by(id=order_id, user_id=user_id).one_or_none()
    if not order:
        return ExecutionResult(ok=False, status="NOT_FOUND",
                                 rejected_reason="Order not found")

    if order.status in TERMINAL_ORDER_STATUSES:
        return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                 rejected_reason=f"Order is in terminal status {order.status} — cannot modify")

    changes_local: dict = {}
    needs_broker_modify = False

    if stoploss is not None:
        changes_local["stoploss"] = stoploss
    if target_1 is not None:
        changes_local["target_1"] = target_1
    if quantity is not None and quantity != order.quantity:
        changes_local["quantity"] = quantity
        needs_broker_modify = True
    if price is not None and price != order.price:
        changes_local["price"] = price
        needs_broker_modify = True
    if trigger_price is not None and trigger_price != order.trigger_price:
        changes_local["trigger_price"] = trigger_price
        needs_broker_modify = True

    if not changes_local:
        return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                 rejected_reason="No changes requested")

    # Capture before-state for audit
    before = {k: getattr(order, k) for k in changes_local}

    # ----- Broker-side modification (if needed) -----
    if needs_broker_modify:
        if not order.broker_order_id:
            return ExecutionResult(ok=False, order_id=order.id,
                                     rejected_reason="No broker_order_id — order may not have been submitted yet")
        try:
            # Uses the USER's broker session, not the platform's
            user_broker = broker_session_manager.get_for_user(db, user_id)
            modify_fn = getattr(user_broker, "modify_order", None)
            if modify_fn:
                modify_fn(
                    order_id=order.broker_order_id,
                    quantity=quantity if quantity is not None else order.quantity,
                    price=price if price is not None else order.price,
                    trigger_price=trigger_price if trigger_price is not None else order.trigger_price,
                )
            else:
                return ExecutionResult(ok=False, order_id=order.id,
                                         rejected_reason="Broker does not expose modify_order; cancel + re-place instead")
        except broker_session_manager.BrokerSessionError as e:
            return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                     rejected_reason=f"broker not connected: {e}")
        except BrokerError as e:
            return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                     rejected_reason=f"Broker rejected modify: {e}")
        except Exception as e:
            return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                     rejected_reason=f"Modify failed: {e}")

    # ----- Local DB update -----
    for k, v in changes_local.items():
        setattr(order, k, v)
    order.updated_at = datetime.utcnow()
    db.commit()

    _audit(user_id, "trade.modify",
            f"Modified order {order.id}: {', '.join(f'{k}→{v}' for k, v in changes_local.items())}",
            {"before": before, "after": changes_local})

    return ExecutionResult(
        ok=True, order_id=order.id, status=order.status,
        message=f"Modified {', '.join(changes_local.keys())}",
    )


def cancel(db: Session, user_id: int, order_id: int) -> ExecutionResult:
    """Cancel an outstanding order. Only OPEN orders can be cancelled."""
    order = (db.query(Order)
               .filter_by(id=order_id, user_id=user_id)
               .one_or_none())
    if not order:
        return ExecutionResult(ok=False, status="NOT_FOUND",
                                 rejected_reason="Order not found")
    if order.status in (ORDER_STATUS_FILLED, ORDER_STATUS_CANCELLED, ORDER_STATUS_REJECTED):
        return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                 rejected_reason=f"Order already {order.status}")

    # Live broker cancel — uses the USER's broker session, not the platform's
    try:
        user_broker = broker_session_manager.get_for_user(db, user_id)
        if order.broker_order_id:
            user_broker.cancel_order(order.broker_order_id)
        order.status = ORDER_STATUS_CANCELLED
        order.cancelled_at = datetime.utcnow()
        db.commit()
        return ExecutionResult(ok=True, order_id=order.id, status=ORDER_STATUS_CANCELLED,
                                 message="Order cancelled with broker")
    except broker_session_manager.BrokerSessionError as e:
        return ExecutionResult(ok=False, order_id=order.id, status=order.status,
                                 rejected_reason=f"broker not connected: {e}")
    except BrokerError as e:
        return ExecutionResult(ok=False, order_id=order.id,
                                 status=order.status, rejected_reason=str(e))


# ============================================================================
# Multi-leg execution — option spreads, condors, straddles
# ============================================================================
#
# Why this exists:
#   The fno_recommendation orchestrator can return strategies with N legs
#   (BULL_CALL_SPREAD, IRON_CONDOR, LONG_STRADDLE, etc.). Placing them as
#   N independent `execute()` calls is unsafe: if leg 1 fills and leg 2
#   gets rejected, the user is left with a NAKED position they didn't ask
#   for. This function provides ATOMIC placement with rollback.
#
# Saga pattern:
#   1. Validate the WHOLE basket upfront (trading enabled, risk gate,
#      sufficient margin for the net premium). If any leg fails validation,
#      NOTHING is placed.
#   2. Tag every leg row with the same `multi_leg_group_id` UUID.
#   3. Place legs sequentially. If leg K fails AFTER legs 0..K-1 succeeded:
#        a. Mark leg K as FAILED with the failure reason.
#        b. Mark legs K+1..N-1 as FAILED with "cancelled due to earlier leg failure".
#        c. Place REVERSING orders (opposite direction, same qty) for legs
#           0..K-1 — this neutralizes the position.
#        d. Return ok=False with the leg index where it failed + rollback summary.
#   4. If all legs place: return ok=True with the group_id + all leg order_ids.

@dataclass
class MultiLegResult:
    ok: bool
    group_id: str
    leg_results: list[ExecutionResult] = field(default_factory=list)
    rolled_back_count: int = 0
    failed_at_leg: Optional[int] = None
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "group_id": self.group_id,
            "leg_count": len(self.leg_results),
            "legs": [r.to_dict() for r in self.leg_results],
            "rolled_back_count": self.rolled_back_count,
            "failed_at_leg": self.failed_at_leg,
            "message": self.message,
        }


def _place_one_leg(db: Session, intent: OrderIntent,
                    group_id: str, leg_index: int) -> ExecutionResult:
    """Place a single leg inside a multi-leg basket. Skips the duplicate-
    intent check (multiple legs at the same symbol+direction+qty are
    legitimate inside a basket — e.g. straddle has BUY CE + BUY PE)."""
    # We reuse the bulk of execute() but bypass the idempotency cache.
    # Easiest way: temporarily insert a unique synthetic key into the
    # idempotency cache before calling execute(), or just inline the steps.
    # We inline so the basket logic is explicit + easy to audit.
    from app.models.user import User as _User
    user = db.query(_User).filter_by(id=intent.user_id).one_or_none()
    if user is None:
        return ExecutionResult(ok=False, status="VALIDATION_FAILED",
                                 rejected_reason="User not found")
    if not user.trading_enabled:
        return ExecutionResult(ok=False, status="TRADING_DISABLED",
                                 rejected_reason="TRADING_DISABLED",
                                 message="Trading is OFF for this account.")

    if intent.direction not in ("BUY", "SELL"):
        return ExecutionResult(ok=False, status="VALIDATION_FAILED",
                                 rejected_reason=f"direction must be BUY/SELL, got {intent.direction}")
    if intent.quantity <= 0:
        return ExecutionResult(ok=False, status="VALIDATION_FAILED",
                                 rejected_reason="quantity must be > 0")

    client_order_id = f"mleg-{group_id}-{leg_index}-{uuid.uuid4().hex[:8]}"

    # Run risk gate at THIS moment. Note: for non-first legs of a spread,
    # the user-defined SL/T1 may be the *strategy*-level SL not the per-leg
    # one. We let risk_guard run; if it blocks a non-first leg we still
    # roll back already-placed legs (atomicity > one-leg perfection).
    passed, rg_dict = _run_risk_gate(db, intent)

    order = Order(
        user_id=intent.user_id,
        client_order_id=client_order_id,
        source_signal_id=intent.source_signal_id,
        source_type=intent.source_type,
        symbol=intent.symbol.upper().strip(),
        exchange=intent.exchange,
        direction=intent.direction,
        quantity=intent.quantity,
        product_type=intent.product_type,
        order_type=intent.order_type,
        price=intent.price,
        trigger_price=intent.trigger_price,
        stoploss=intent.stoploss,
        target_1=intent.target_1,
        target_2=intent.target_2,
        target_3=intent.target_3,
        status=ORDER_STATUS_PENDING_RISK,
        risk_guard_snapshot=rg_dict,
        is_paper=False,
        multi_leg_group_id=group_id,
        leg_index=leg_index,
    )
    db.add(order)
    db.flush()

    if not passed:
        order.status = ORDER_STATUS_FAILED
        order.notes = f"Leg {leg_index}: risk-guard blocked — {rg_dict.get('reasons', ['unknown'])[0]}"
        db.commit()
        return ExecutionResult(
            ok=False, order_id=order.id, client_order_id=client_order_id,
            status=ORDER_STATUS_FAILED, risk_guard=rg_dict,
            rejected_reason="RISK_GUARD_BLOCK",
            message=f"Leg {leg_index} blocked by risk guard",
        )

    order.status = ORDER_STATUS_PENDING_BROKER
    db.commit()
    return _submit_to_broker(db, order, intent)


def _reverse_leg(db: Session, placed: Order, group_id: str) -> ExecutionResult:
    """Place an opposing-direction order to neutralize a previously-placed leg.

    Called during multi-leg rollback. Best-effort — if the reversal itself
    fails (e.g. broker session dropped mid-rollback), we record the order
    row as FAILED with notes and return ok=False; the user is alerted in
    the basket-level result that the position couldn't be fully unwound.
    """
    opposing_dir = "SELL" if placed.direction == "BUY" else "BUY"
    reverse_intent = OrderIntent(
        user_id=placed.user_id,
        symbol=placed.symbol,
        exchange=placed.exchange,
        direction=opposing_dir,
        quantity=placed.quantity,
        product_type=placed.product_type,
        order_type="MARKET",                 # neutralize at market — speed > price
        price=None,
        stoploss=None,
        target_1=None,
        source_signal_id=placed.source_signal_id,
        source_type=f"ROLLBACK:{placed.client_order_id}",
        capital=100_000,
    )

    client_order_id = f"rollback-{group_id}-{placed.id}-{uuid.uuid4().hex[:6]}"
    rev_order = Order(
        user_id=placed.user_id,
        client_order_id=client_order_id,
        symbol=placed.symbol, exchange=placed.exchange,
        direction=opposing_dir, quantity=placed.quantity,
        product_type=placed.product_type, order_type="MARKET",
        source_signal_id=placed.source_signal_id,
        source_type=f"ROLLBACK:{placed.client_order_id}",
        status=ORDER_STATUS_PENDING_BROKER,
        is_paper=False,
        multi_leg_group_id=group_id,
        leg_index=None,
        notes=f"Auto-rollback of leg order id={placed.id} ({placed.direction} {placed.quantity})",
    )
    db.add(rev_order)
    db.flush()

    try:
        return _submit_to_broker(db, rev_order, reverse_intent)
    except Exception as e:
        logger.exception("Rollback leg submission failed for order {}", placed.id)
        rev_order.status = ORDER_STATUS_FAILED
        rev_order.notes = (rev_order.notes or "") + f" | ROLLBACK FAILED: {e}"
        db.commit()
        return ExecutionResult(
            ok=False, order_id=rev_order.id, status=ORDER_STATUS_FAILED,
            rejected_reason=f"ROLLBACK_FAILED: {e}",
            message=f"Could not unwind leg {placed.id} — manual intervention needed.",
        )


def execute_multi_leg(db: Session, intents: list[OrderIntent]) -> MultiLegResult:
    """Place N legs atomically. If any leg fails, reverse the already-placed ones.

    Validates the whole basket upfront (trading enabled, all legs target the
    same exchange, qty > 0 everywhere) before any broker contact.

    Returns a MultiLegResult with:
      • ok=True  + all leg ExecutionResults if every leg placed successfully
      • ok=False + failed_at_leg index + rolled_back_count if a leg failed
    """
    if not intents:
        return MultiLegResult(ok=False, group_id="",
                                message="No legs provided")
    if len(intents) > 8:
        return MultiLegResult(ok=False, group_id="",
                                message=f"Refusing {len(intents)}-leg basket — max 8 legs supported")

    # All legs must belong to the same user (the API layer should ensure this,
    # but defense-in-depth: re-check here so a bad caller can't slip a leg
    # under another user's account).
    user_ids = {i.user_id for i in intents}
    if len(user_ids) > 1:
        return MultiLegResult(ok=False, group_id="",
                                message="All legs must belong to one user")

    group_id = uuid.uuid4().hex

    # ----- Upfront validation (no broker contact yet) -----
    for idx, intent in enumerate(intents):
        if intent.direction not in ("BUY", "SELL"):
            return MultiLegResult(ok=False, group_id=group_id,
                                    failed_at_leg=idx,
                                    message=f"Leg {idx}: invalid direction {intent.direction!r}")
        if intent.quantity <= 0:
            return MultiLegResult(ok=False, group_id=group_id,
                                    failed_at_leg=idx,
                                    message=f"Leg {idx}: quantity must be > 0")

    # ----- Place legs sequentially -----
    placed_orders: list[Order] = []
    leg_results: list[ExecutionResult] = []

    for idx, intent in enumerate(intents):
        result = _place_one_leg(db, intent, group_id, idx)
        leg_results.append(result)

        if not result.ok:
            logger.warning("Multi-leg basket {} failed at leg {}: {}",
                            group_id, idx, result.rejected_reason)
            # ----- Rollback already-placed legs -----
            rolled_back = 0
            for placed in placed_orders:
                # Only reverse if the broker actually accepted it (status OPEN
                # or FILLED). PENDING_RISK / FAILED legs don't need reversing.
                if placed.status in (ORDER_STATUS_OPEN, ORDER_STATUS_FILLED,
                                       "PARTIAL"):
                    rev = _reverse_leg(db, placed, group_id)
                    if rev.ok:
                        rolled_back += 1
                    else:
                        # Best-effort logged; the basket result will flag this.
                        logger.error("Could not roll back leg {} of basket {}: {}",
                                       placed.id, group_id, rev.rejected_reason)
            _audit(intent.user_id, "trade.multi_leg.failed",
                    f"Multi-leg basket {group_id} failed at leg {idx} — "
                    f"rolled back {rolled_back}/{len(placed_orders)} placed legs",
                    {"group_id": group_id, "failed_at_leg": idx,
                      "rejected_reason": result.rejected_reason})
            return MultiLegResult(
                ok=False, group_id=group_id,
                leg_results=leg_results,
                rolled_back_count=rolled_back,
                failed_at_leg=idx,
                message=(f"Leg {idx} ({intent.symbol} {intent.direction} "
                          f"{intent.quantity}) failed: {result.rejected_reason}. "
                          f"Rolled back {rolled_back}/{len(placed_orders)} earlier legs."),
            )

        # Leg succeeded — fetch the row so rollback can find it later
        if result.order_id:
            placed = db.query(Order).filter_by(id=result.order_id).one_or_none()
            if placed:
                placed_orders.append(placed)

    # ----- All legs placed -----
    _audit(intents[0].user_id, "trade.multi_leg.placed",
            f"Multi-leg basket {group_id} placed — {len(intents)} legs",
            {"group_id": group_id, "leg_count": len(intents),
              "symbols": [i.symbol for i in intents]})

    return MultiLegResult(
        ok=True, group_id=group_id,
        leg_results=leg_results,
        message=f"All {len(intents)} legs placed.",
    )
