"""Outcome tracker — evaluates emitted signals against actual market data.

Runs as a background cron (call `mark_due_outcomes()` periodically). For each
PENDING signal where N days have elapsed, fetches the OHLCV bars since
emission, computes:
  • close-to-close P&L at 1d / 5d / 20d
  • whether T1/T2/T3 was hit before SL
  • max favourable excursion (MFE) and max adverse excursion (MAE)

Writes results back to the signals_journal row.

This is the table you should query monthly to know if your system has edge.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable
from loguru import logger

from app.database import SessionLocal
from app.models.signals_journal import SignalJournalEntry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mark_due_outcomes(now: datetime | None = None,
                       window_days: int = 25,
                       max_per_run: int = 200) -> dict:
    """Evaluate up to `max_per_run` signals whose 20d window has matured.

    Returns summary dict: {evaluated, skipped_missing_data, errors}.
    """
    now = now or datetime.utcnow()
    cutoff_emitted = now - timedelta(days=window_days)
    evaluated = 0
    skipped = 0
    errors = 0

    with SessionLocal() as sess:
        rows = (
            sess.query(SignalJournalEntry)
            .filter(
                SignalJournalEntry.outcome_status == "PENDING",
                SignalJournalEntry.emitted_at <= cutoff_emitted,
            )
            .order_by(SignalJournalEntry.emitted_at.asc())
            .limit(max_per_run)
            .all()
        )

        for row in rows:
            try:
                ok = _evaluate_row(row)
                if ok:
                    evaluated += 1
                else:
                    skipped += 1
            except Exception as e:
                errors += 1
                logger.warning("outcome_tracker: failed on signal #{}: {}", row.id, e)
        sess.commit()

    logger.info("outcome_tracker: evaluated={} skipped={} errors={}",
                evaluated, skipped, errors)
    return {"evaluated": evaluated, "skipped_missing_data": skipped, "errors": errors}


def mark_signal(signal_id: int) -> bool:
    """Force-evaluate a single signal id (for /api/journal/evaluate endpoint)."""
    with SessionLocal() as sess:
        row = sess.query(SignalJournalEntry).filter_by(id=signal_id).one_or_none()
        if row is None:
            return False
        ok = _evaluate_row(row)
        sess.commit()
        return ok


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _fetch_post_emission_bars(symbol: str, since: datetime,
                              until: datetime) -> "pandas.DataFrame | None":
    """Pull daily OHLCV bars between `since` and `until` from the market-data
    layer. Returns None if data unavailable.
    """
    try:
        from app.services.market_data import get_ohlcv
        # Pull enough periods to cover the window — daily bars, ~30 days.
        df = get_ohlcv(symbol, periods=40)
        if df is None or df.empty:
            return None
        # Filter to post-emission
        if "ts" in df.columns:
            df = df[df["ts"] >= since]
        df = df[df.index >= since] if hasattr(df.index, "to_pydatetime") else df
        return df.head(25)  # cap at 25 bars (~ 1 month of trading)
    except Exception as e:
        logger.debug("outcome_tracker: bars fetch failed for {}: {}", symbol, e)
        return None


def _evaluate_row(row: SignalJournalEntry) -> bool:
    """Compute outcome metrics for one journal row. Returns True if evaluated,
    False if market data was unavailable (row left PENDING).
    """
    df = _fetch_post_emission_bars(
        row.symbol,
        since=row.emitted_at,
        until=row.emitted_at + timedelta(days=25),
    )
    if df is None or df.empty:
        # Don't mark — leave for retry next run. Mark STALE if very old.
        age_days = (datetime.utcnow() - row.emitted_at).days
        if age_days > 60:
            row.outcome_status = "STALE"
        return False

    entry = float(row.entry or 0)
    if entry <= 0:
        row.outcome_status = "STALE"
        return False

    direction_long = (row.direction or "").upper() == "BULLISH"

    closes = df["close"].astype(float).tolist()
    highs  = df["high"].astype(float).tolist()
    lows   = df["low"].astype(float).tolist()

    # Close-to-close P&L at horizons
    def _pnl_at(n: int) -> float | None:
        if len(closes) < n:
            return None
        px = closes[n - 1]
        diff = (px - entry) / entry * 100
        return round(diff if direction_long else -diff, 4)

    row.outcome_1d_pnl_pct  = _pnl_at(1)
    row.outcome_5d_pnl_pct  = _pnl_at(5)
    row.outcome_20d_pnl_pct = _pnl_at(20)

    # MFE / MAE in % from entry, direction-adjusted
    if direction_long:
        peak  = max(highs)
        trough = min(lows)
        row.outcome_max_favorable = round((peak - entry) / entry * 100, 4)
        row.outcome_max_adverse   = round((trough - entry) / entry * 100, 4)
    else:
        peak  = min(lows)
        trough = max(highs)
        row.outcome_max_favorable = round((entry - peak) / entry * 100, 4)
        row.outcome_max_adverse   = round((entry - trough) / entry * 100, 4)

    # Target / SL hit detection (which came first chronologically)
    targets = [row.target_1, row.target_2, row.target_3]
    sl = row.stoploss
    hit_target = 0
    stop_hit = False
    for h, l in zip(highs, lows):
        if direction_long:
            if sl is not None and l <= sl:
                stop_hit = True
                break
            for i, t in enumerate(targets):
                if t is not None and h >= t:
                    hit_target = max(hit_target, i + 1)
        else:
            if sl is not None and h >= sl:
                stop_hit = True
                break
            for i, t in enumerate(targets):
                if t is not None and l <= t:
                    hit_target = max(hit_target, i + 1)
        if hit_target >= 3:
            break

    row.outcome_target_hit   = hit_target
    row.outcome_stoploss_hit = stop_hit
    row.outcome_evaluated_at = datetime.utcnow()
    row.outcome_status       = "EVALUATED"

    # ----- Online-learner update — extreme-minimal-CPU "AI" layer -----
    # One SGD step per evaluated signal. ~10 microseconds. The model
    # progressively learns which engines actually predict outcomes for
    # THIS user's strategy + this market. Persisted to disk every 10
    # updates. See app/services/online_learner.py for the math.
    try:
        from app.services import online_learner
        snapshot = row.engines_snapshot or {}
        regime = None
        if isinstance(snapshot.get("quant"), dict):
            regime = snapshot["quant"].get("regime")
        features = online_learner.build_feature_vector(
            engines_snapshot=snapshot, regime=regime,
        )
        won = _is_win(row)
        online_learner.update(features, won=won)
    except Exception as e:
        # Failures must never block outcome tracking
        from loguru import logger as _lg
        _lg.debug("Online learner update skipped: {}", e)

    return True


def _is_win(r) -> bool:
    """Same win definition used in performance_summary and calibration_fit.
    A signal wins iff a target hit OR 5d P&L moved in the intended direction
    by >1%. Loses iff SL hit OR 5d P&L moved against intent by >1%.
    Anything else is treated as a wash (neither win nor loss — but we still
    update the learner with the actual outcome bit so it learns over time)."""
    if r.outcome_target_hit and r.outcome_target_hit > 0:
        return True
    if r.outcome_stoploss_hit:
        return False
    pnl = r.outcome_5d_pnl_pct or 0
    if r.direction == "BULLISH" and pnl > 1.0:
        return True
    if r.direction == "BEARISH" and pnl < -1.0:
        return True
    return False


# ---------------------------------------------------------------------------
# Summary stats over the journal — call from /api/journal/stats
# ---------------------------------------------------------------------------

def journal_stats(since_days: int = 90, horizon: str | None = None) -> dict:
    """Aggregate stats over evaluated signals — the closest thing to a
    track-record this system has.
    """
    cutoff = datetime.utcnow() - timedelta(days=since_days)
    with SessionLocal() as sess:
        q = sess.query(SignalJournalEntry).filter(
            SignalJournalEntry.outcome_status == "EVALUATED",
            SignalJournalEntry.emitted_at >= cutoff,
        )
        if horizon:
            q = q.filter(SignalJournalEntry.horizon == horizon)
        rows = q.all()

    if not rows:
        return {"count": 0, "message": "No evaluated signals in window"}

    def _avg(seq):
        seq = [x for x in seq if x is not None]
        return round(sum(seq) / len(seq), 4) if seq else None

    pnl_5d  = [r.outcome_5d_pnl_pct  for r in rows]
    pnl_20d = [r.outcome_20d_pnl_pct for r in rows]
    win_5d  = [1 if (p or 0) > 0 else 0 for p in pnl_5d if p is not None]
    win_20d = [1 if (p or 0) > 0 else 0 for p in pnl_20d if p is not None]

    target_hits = sum(1 for r in rows if (r.outcome_target_hit or 0) >= 1)
    stop_hits   = sum(1 for r in rows if r.outcome_stoploss_hit)

    # By conviction label
    by_label: dict[str, dict] = {}
    for r in rows:
        lbl = r.signal_label or "?"
        d = by_label.setdefault(lbl, {"count": 0, "pnl_5d": [], "pnl_20d": []})
        d["count"] += 1
        if r.outcome_5d_pnl_pct  is not None: d["pnl_5d"].append(r.outcome_5d_pnl_pct)
        if r.outcome_20d_pnl_pct is not None: d["pnl_20d"].append(r.outcome_20d_pnl_pct)
    for d in by_label.values():
        d["avg_pnl_5d"]  = _avg(d["pnl_5d"])
        d["avg_pnl_20d"] = _avg(d["pnl_20d"])
        d.pop("pnl_5d");  d.pop("pnl_20d")

    return {
        "count": len(rows),
        "window_days": since_days,
        "horizon": horizon or "ALL",
        "win_rate_5d_pct":  round(sum(win_5d) / max(1, len(win_5d)) * 100, 2),
        "win_rate_20d_pct": round(sum(win_20d) / max(1, len(win_20d)) * 100, 2),
        "avg_pnl_5d_pct":   _avg(pnl_5d),
        "avg_pnl_20d_pct":  _avg(pnl_20d),
        "target_hit_rate_pct":   round(target_hits / len(rows) * 100, 2),
        "stoploss_hit_rate_pct": round(stop_hits / len(rows) * 100, 2),
        "by_conviction": by_label,
    }
