"""Signals journal writer — call this every time the pipeline emits a signal.

Designed to be drop-in: any place that calls `decision.aggregate()` can also
call `log_signal()` with the result. Failures are swallowed so logging never
breaks the signal emission path.

Also handles retention — `purge_older_than_days()` keeps the journal from
growing indefinitely. Default policy: keep 14 days of signal history.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from loguru import logger

from app.database import SessionLocal
from app.models.signals_journal import SignalJournalEntry


def log_signal(signal: dict, horizon: str = "SWING",
               grade: dict | None = None) -> int | None:
    """Insert a signal row. Returns the id or None on failure."""
    try:
        targets = list(signal.get("targets", [])) or []
        engines = signal.get("engines", {}) or {}
        engines_snap = {
            name: {"score": eng.get("score"), "bias": eng.get("bias")}
            for name, eng in engines.items()
        }
        with SessionLocal() as sess:
            row = SignalJournalEntry(
                emitted_at=datetime.utcnow(),
                symbol=signal.get("symbol", "?"),
                exchange=signal.get("exchange", "NSE"),
                horizon=horizon,
                signal_label=signal.get("signal"),
                direction=signal.get("trend"),
                confidence=signal.get("confidence"),
                stars=(grade or {}).get("stars"),
                entry=signal.get("entry"),
                stoploss=signal.get("stoploss"),
                target_1=targets[0] if len(targets) > 0 else None,
                target_2=targets[1] if len(targets) > 1 else None,
                target_3=targets[2] if len(targets) > 2 else None,
                engines_snapshot=engines_snap,
                reasons=signal.get("reasons"),
                grade=grade,
                outcome_status="PENDING",
            )
            sess.add(row)
            sess.commit()
            return row.id
    except Exception as e:
        logger.warning("signals_logger: failed to log signal for {}: {}",
                       signal.get("symbol"), e)
        return None


def purge_older_than_days(days: int = 14) -> dict:
    """Delete journal rows older than `days`. Default 14-day retention.

    Returns: {deleted, remaining, oldest_remaining}.
    Run from a cron daily or call from /api/journal/purge.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    try:
        with SessionLocal() as sess:
            deleted = (sess.query(SignalJournalEntry)
                        .filter(SignalJournalEntry.emitted_at < cutoff)
                        .delete(synchronize_session=False))
            remaining = sess.query(SignalJournalEntry).count()
            oldest_row = (sess.query(SignalJournalEntry)
                           .order_by(SignalJournalEntry.emitted_at.asc())
                           .first())
            oldest = oldest_row.emitted_at.isoformat() if oldest_row else None
            sess.commit()
        logger.info("Signals journal purged: deleted={} remaining={}", deleted, remaining)
        return {"deleted": int(deleted), "remaining": remaining,
                "oldest_remaining": oldest, "retention_days": days}
    except Exception as e:
        logger.warning("purge failed: {}", e)
        return {"error": str(e)}


def history_for_symbol(symbol: str, days: int = 14, limit: int = 100) -> list[dict]:
    """Return recent signal history for ONE symbol."""
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as sess:
        rows = (sess.query(SignalJournalEntry)
                  .filter(
                      SignalJournalEntry.symbol == symbol.upper(),
                      SignalJournalEntry.emitted_at >= since,
                  )
                  .order_by(SignalJournalEntry.emitted_at.desc())
                  .limit(limit)
                  .all())
    return [_row_to_dict(r) for r in rows]


def recent_signals(days: int = 14, limit: int = 200,
                    direction: str | None = None,
                    min_confidence: float | None = None) -> list[dict]:
    """Return recent signals across all symbols with optional filters."""
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as sess:
        q = (sess.query(SignalJournalEntry)
              .filter(SignalJournalEntry.emitted_at >= since))
        if direction:
            q = q.filter(SignalJournalEntry.direction == direction.upper())
        if min_confidence is not None:
            q = q.filter(SignalJournalEntry.confidence >= min_confidence)
        rows = (q.order_by(SignalJournalEntry.emitted_at.desc())
                 .limit(limit).all())
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(r) -> dict:
    return {
        "id": r.id,
        "emitted_at": r.emitted_at.isoformat() if r.emitted_at else None,
        "symbol": r.symbol,
        "horizon": r.horizon,
        "signal_label": r.signal_label,
        "direction": r.direction,
        "confidence": r.confidence,
        "stars": r.stars,
        "entry": r.entry,
        "stoploss": r.stoploss,
        "targets": [r.target_1, r.target_2, r.target_3],
        "outcome": {
            "status": r.outcome_status,
            "pnl_5d_pct": r.outcome_5d_pnl_pct,
            "pnl_20d_pct": r.outcome_20d_pnl_pct,
            "target_hit": r.outcome_target_hit,
            "stoploss_hit": r.outcome_stoploss_hit,
        },
    }
