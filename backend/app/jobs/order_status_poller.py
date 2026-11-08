"""Background job: poll the broker for status updates on OPEN/PARTIAL orders.

Why this exists:

When a user places a LIVE order, `trade_executor` records the order with
status `OPEN` (or `PARTIAL`) after broker ack. From that moment on, the
fill events happen on the broker's side — they can arrive seconds or
hours later depending on the order type and market conditions. Without
this poller, our DB never finds out the order filled.

The poller runs every POLL_INTERVAL_SECONDS, queries the broker's
order book, and reconciles. It only touches orders in non-terminal
statuses, so it's cheap and idempotent.

Concurrency:
  • One scheduled instance per process (APScheduler `max_instances=1`)
  • Database writes are batched per polling pass
  • If the broker is unauthenticated we skip — no point trying

What this poller DOES NOT do (deliberate):
  • It doesn't reconcile orders that didn't originate from our platform
    (e.g. orders the user placed directly in the broker terminal).
    Those don't have a row in our `exec_orders` table.
  • It doesn't pick up positions opened in the broker terminal — only
    fills against our own orders.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.brokers.angelone import broker_instance
from app.database import SessionLocal
from app.models.trade_execution import (
    Order, TradeFill,
    ORDER_STATUS_OPEN, ORDER_STATUS_PARTIAL, ORDER_STATUS_FILLED,
    ORDER_STATUS_PENDING_BROKER, ORDER_STATUS_REJECTED, ORDER_STATUS_CANCELLED,
    TERMINAL_ORDER_STATUSES,
)


POLL_INTERVAL_SECONDS = 30
NON_TERMINAL_STATUSES = (
    ORDER_STATUS_OPEN, ORDER_STATUS_PARTIAL, ORDER_STATUS_PENDING_BROKER,
)
# Don't waste broker calls on orders that have been open for over a week
# without filling. They're probably stale or wrong; admin can investigate.
MAX_AGE_DAYS = 7


_scheduler = None


def _normalize_broker_status(s: str) -> str:
    """Map broker-specific status strings to our internal vocabulary.
    Angel One returns strings like 'complete', 'rejected', 'cancelled',
    'open', 'trigger pending'. Normalise for downstream handling."""
    if not s:
        return ""
    s = s.lower().strip()
    if s in ("complete", "filled", "executed"):
        return ORDER_STATUS_FILLED
    if s in ("rejected",):
        return ORDER_STATUS_REJECTED
    if s in ("cancelled", "canceled"):
        return ORDER_STATUS_CANCELLED
    if s in ("open", "trigger pending", "pending", "received"):
        return ORDER_STATUS_OPEN
    if s in ("partial", "partially filled"):
        return ORDER_STATUS_PARTIAL
    return s.upper()


def _fetch_user_order_book(user_broker) -> dict[str, dict]:
    """Pull ONE user's broker order book, keyed by broker order_id."""
    try:
        book = None
        for attr in ("orders", "order_book", "get_orders"):
            fn = getattr(user_broker, attr, None)
            if callable(fn):
                book = fn()
                break
        if book is None:
            return {}
        rows = book if isinstance(book, list) else (book.get("data") or book.get("orders") or [])
        keyed: dict[str, dict] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            oid = (r.get("orderid") or r.get("order_id") or
                    r.get("orderId") or r.get("nestordernum") or "").strip()
            if oid:
                keyed[oid] = r
        return keyed
    except Exception as e:
        logger.warning("User broker order-book fetch failed: {}", e)
        return {}


def _reconcile_one(db: Session, order: Order, broker_row: dict) -> bool:
    """Update a single order from broker data. Returns True if anything changed."""
    raw_status = (broker_row.get("status") or broker_row.get("orderstatus") or
                   broker_row.get("order_status") or "").strip()
    new_status = _normalize_broker_status(raw_status)
    filled_qty = int(broker_row.get("filledshares") or broker_row.get("filledquantity")
                      or broker_row.get("filled_quantity") or 0)
    avg_price = float(broker_row.get("averageprice") or broker_row.get("avgprice")
                        or broker_row.get("avg_price") or 0)

    changed = False

    # Status transitions — only forward through the lifecycle
    if new_status and new_status != order.status and new_status not in (
            ORDER_STATUS_PENDING_BROKER,):
        order.status = new_status
        order.broker_status = raw_status
        changed = True
        if new_status == ORDER_STATUS_FILLED:
            order.filled_at = datetime.utcnow()
        if new_status == ORDER_STATUS_CANCELLED:
            order.cancelled_at = datetime.utcnow()

    # Fill quantity / avg price
    if filled_qty > (order.filled_quantity or 0):
        # New partial fill — record a TradeFill row
        delta_qty = filled_qty - (order.filled_quantity or 0)
        fill = TradeFill(
            order_id=order.id, user_id=order.user_id,
            symbol=order.symbol, direction=order.direction,
            quantity=delta_qty,
            price=avg_price or order.price or 0,
            fill_type="OPEN",   # _apply_fill_to_position will refine
            realized_pnl=0.0,
            is_paper=False,
            broker_response={"poll_event": True, "row": broker_row},
        )
        db.add(fill)
        order.filled_quantity = filled_qty
        if avg_price:
            order.avg_fill_price = avg_price
        # Position update — reuse the executor's helper
        from app.services.trade_executor import _apply_fill_to_position
        _apply_fill_to_position(db, order, fill)
        changed = True

    if changed:
        order.updated_at = datetime.utcnow()
    return changed


def run_once() -> dict:
    """Single poll pass — iterates over users with connected broker sessions,
    fetches each user's order book separately, reconciles their orders.

    Multi-user refactor: one shared broker order book was wrong because each
    user has their own broker account. This iterates the set of users with
    `connected=True` in `user_broker_sessions` and polls each independently.
    """
    started = datetime.utcnow()
    cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)

    from app.services import broker_session_manager

    updated_count = 0
    checked_count = 0
    user_count    = 0
    skipped_users: list[int] = []

    with SessionLocal() as db:
        connected_uids = broker_session_manager.connected_user_ids(db)
        if not connected_uids:
            return {"started_at": started.isoformat(), "skipped": "no_connected_users"}

        for uid in connected_uids:
            user_count += 1
            # Pull the user's open orders we have on file
            user_orders = (db.query(Order)
                             .filter(Order.user_id == uid,
                                      Order.status.in_(NON_TERMINAL_STATUSES),
                                      Order.placed_at >= cutoff,
                                      Order.is_paper == False,
                                      Order.broker_order_id.isnot(None))
                             .all())
            if not user_orders:
                continue    # nothing to reconcile for this user

            try:
                user_broker = broker_session_manager.get_for_user(db, uid)
            except broker_session_manager.BrokerSessionError as e:
                logger.debug("Skip user {} — broker session unavailable: {}", uid, e)
                skipped_users.append(uid)
                continue

            book = _fetch_user_order_book(user_broker)
            checked_count += len(book)
            for order in user_orders:
                broker_row = book.get(order.broker_order_id)
                if not broker_row:
                    continue
                try:
                    if _reconcile_one(db, order, broker_row):
                        updated_count += 1
                except Exception as e:
                    logger.warning("Reconcile failed for order {} (user {}): {}",
                                     order.id, uid, e)
                    continue
        db.commit()

    return {
        "started_at":    started.isoformat(),
        "elapsed_sec":   round((datetime.utcnow() - started).total_seconds(), 2),
        "users_polled":  user_count,
        "users_skipped": len(skipped_users),
        "orders_checked": checked_count,
        "orders_updated": updated_count,
    }


def start_scheduler() -> None:
    """Start the poller on app startup. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("apscheduler not installed — order status poller will not run")
        return
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(run_once, "interval", seconds=POLL_INTERVAL_SECONDS,
                   id="order_status_poller", max_instances=1,
                   coalesce=True, misfire_grace_time=15)
    sched.start()
    _scheduler = sched
    logger.info("Order status poller started — interval {}s", POLL_INTERVAL_SECONDS)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
