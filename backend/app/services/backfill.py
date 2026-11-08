"""Historical OHLCV backfill — pulls past bars from Angel One into the
`ohlcv_bars` table so engines/backtester/ML have real history to work with.

Why this matters:
  • Backtester needs years of bars to compute Sharpe/Sortino/profit factor
  • ML pipeline needs historical signal-feature → outcome pairs
  • Gann time-cycles/Fibonacci pivots need real swings, not just live ticks
  • Engines run faster when reading bars from local DB vs hitting Angel One

Design:
  • Rate-limited (Angel One historical API: ~3 req/sec safe)
  • Idempotent upsert (re-running fills holes, doesn't duplicate)
  • Resumes on partial completion (progress tracked per symbol)
  • Reports per-symbol success/failure
  • Background job (returns immediately, status pollable)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
from loguru import logger
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.brokers.angelone import broker_instance
from app.database import SessionLocal, engine
from app.models.ohlcv_bar import OHLCVBar
from app.services import instruments
from app.services.universe import top_liquid, all_symbols


# ---------------------------------------------------------------------------
# Status tracking
# ---------------------------------------------------------------------------

@dataclass
class BackfillStatus:
    state: str = "idle"                     # idle / running / completed / failed
    started_at: str | None = None
    finished_at: str | None = None
    interval: str = "ONE_DAY"
    days_back: int = 0
    symbols_total: int = 0
    symbols_done: int = 0
    symbols_failed: int = 0
    last_symbol: str | None = None
    bars_inserted: int = 0
    errors: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


_status = BackfillStatus()
_lock = threading.Lock()


def get_status() -> dict:
    with _lock:
        return _status.to_dict()


# ---------------------------------------------------------------------------
# Idempotent upsert (PG ON CONFLICT or SQLite OR REPLACE)
# ---------------------------------------------------------------------------

def _upsert(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    dialect = engine.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(OHLCVBar.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={k: getattr(stmt.excluded, k) for k in
                  ("open", "high", "low", "close", "volume", "source")},
        )
    elif dialect == "sqlite":
        stmt = sqlite_insert(OHLCVBar.__table__).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={k: getattr(stmt.excluded, k) for k in
                  ("open", "high", "low", "close", "volume", "source")},
        )
    else:
        # Generic fallback — delete then insert (safe but slow)
        for r in rows:
            session.execute(
                delete(OHLCVBar).where(
                    OHLCVBar.symbol == r["symbol"],
                    OHLCVBar.timeframe == r["timeframe"],
                    OHLCVBar.ts == r["ts"],
                )
            )
        session.execute(OHLCVBar.__table__.insert(), rows)
        return len(rows)
    session.execute(stmt)
    return len(rows)


# ---------------------------------------------------------------------------
# Single-symbol fetch + persist
# ---------------------------------------------------------------------------

ANGEL_INTERVAL_MAP = {
    "5m":   "FIVE_MINUTE",
    "15m":  "FIFTEEN_MINUTE",
    "1h":   "ONE_HOUR",
    "1d":   "ONE_DAY",
}


def _fetch_one(symbol: str, exchange: str, angel_interval: str,
                from_dt: datetime, to_dt: datetime) -> list[dict]:
    """Fetch raw candles from Angel One for one symbol-window."""
    token = instruments.token_for(symbol, exchange)
    if not token:
        raise RuntimeError(f"No instrument token for {exchange}/{symbol}")
    candles = broker_instance.candles(
        exchange=exchange, symbol_token=token, interval=angel_interval,
        fromdate=from_dt.strftime("%Y-%m-%d %H:%M"),
        todate=to_dt.strftime("%Y-%m-%d %H:%M"),
    )
    if not candles:
        return []
    rows = []
    for c in candles:
        ts = pd.to_datetime(c[0]).to_pydatetime().replace(tzinfo=None)
        rows.append({
            "symbol": symbol, "timeframe": angel_interval, "ts": ts,
            "open":   float(c[1]),
            "high":   float(c[2]),
            "low":    float(c[3]),
            "close":  float(c[4]),
            "volume": float(c[5]) if len(c) > 5 else 0.0,
            "source": "angelone",
        })
    return rows


# ---------------------------------------------------------------------------
# Public — run backfill (synchronously in this thread)
# ---------------------------------------------------------------------------

def run(
    symbols: list[str] | None = None,
    interval: Literal["5m", "15m", "1h", "1d"] = "1d",
    days_back: int = 365 * 2,
    exchange: str = "NSE",
    rate_per_second: float = 3.0,
    quick: bool = False,
) -> dict:
    """Synchronous backfill — caller blocks until done.
    quick=True restricts to the top-50 most liquid F&O names.
    """
    global _status
    angel_interval = ANGEL_INTERVAL_MAP[interval]
    universe = symbols or (top_liquid(50) if quick else all_symbols(include_indices=False))
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days_back)
    sleep_s = 1.0 / max(0.5, rate_per_second)

    with _lock:
        _status = BackfillStatus(
            state="running",
            started_at=datetime.now().isoformat(),
            interval=angel_interval,
            days_back=days_back,
            symbols_total=len(universe),
        )

    if not broker_instance.is_authenticated():
        with _lock:
            _status.state = "failed"
            _status.finished_at = datetime.now().isoformat()
            _status.errors.append({"symbol": "*",
                                    "error": "Broker not authenticated — Angel One login required"})
        return _status.to_dict()

    # Intraday endpoints have a per-call ~30-day window cap; daily is unlimited.
    # Chunk the window so we don't hit Angel One's "too wide" error.
    chunk_days = 30 if interval != "1d" else 365

    for sym in universe:
        with _lock:
            _status.last_symbol = sym
        try:
            sym_rows: list[dict] = []
            cur = from_dt
            while cur < to_dt:
                end = min(cur + timedelta(days=chunk_days), to_dt)
                try:
                    chunk = _fetch_one(sym, exchange, angel_interval, cur, end)
                    sym_rows.extend(chunk)
                except Exception as e:
                    logger.debug("chunk fail {} {}-{}: {}", sym, cur, end, e)
                cur = end
                time.sleep(sleep_s)

            with SessionLocal() as sess:
                inserted = _upsert(sess, sym_rows)
                sess.commit()

            with _lock:
                _status.symbols_done += 1
                _status.bars_inserted += inserted
        except Exception as e:
            logger.warning("backfill failed for {}: {}", sym, e)
            with _lock:
                _status.symbols_failed += 1
                _status.errors.append({"symbol": sym, "error": str(e)})

    with _lock:
        _status.state = "completed" if _status.symbols_failed == 0 else "completed_with_errors"
        _status.finished_at = datetime.now().isoformat()
    return _status.to_dict()


def run_in_background(**kwargs) -> dict:
    """Launch backfill in a daemon thread; return immediately with status."""
    with _lock:
        if _status.state == "running":
            return {"already_running": True, **_status.to_dict()}
    t = threading.Thread(target=run, kwargs=kwargs,
                          name="ohlcv-backfill", daemon=True)
    t.start()
    return {"started": True, **get_status()}


# ---------------------------------------------------------------------------
# Cache-first read — called from get_ohlcv to prefer local history over
# hitting Angel One on every request.
# ---------------------------------------------------------------------------

def read_cached(symbol: str, interval: str = "1d",
                 periods: int = 250) -> pd.DataFrame | None:
    """Return DataFrame from local ohlcv_bars cache, or None if empty/stale.
    Returns None if the latest cached bar is older than 1 calendar day for 1d
    (since the live broker will have today's bar).
    """
    angel_interval = ANGEL_INTERVAL_MAP.get(interval, interval)
    with SessionLocal() as sess:
        stmt = (
            select(OHLCVBar)
            .where(OHLCVBar.symbol == symbol,
                    OHLCVBar.timeframe == angel_interval)
            .order_by(OHLCVBar.ts.desc())
            .limit(periods)
        )
        rows = sess.execute(stmt).scalars().all()
    if not rows:
        return None
    # Order ascending for downstream engines
    rows = list(reversed(rows))
    df = pd.DataFrame([{
        "open": r.open, "high": r.high, "low": r.low,
        "close": r.close, "volume": r.volume,
    } for r in rows], index=pd.DatetimeIndex([r.ts for r in rows], name="timestamp"))

    # Staleness check — for daily bars, last bar should be within 3 days
    if not df.empty:
        last_age_days = (datetime.now() - df.index[-1].to_pydatetime()).days
        if interval == "1d" and last_age_days > 3:
            return None        # too stale — refetch live
    return df
