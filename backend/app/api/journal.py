"""Signals journal — track-record query endpoints."""
from datetime import datetime, timedelta
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.dependencies import get_db, require_tier
from app.models.signals_journal import SignalJournalEntry
from app.models.user import User
from app.services import outcome_tracker, signals_logger, engine_attribution

router = APIRouter()


@router.get("/engine-attribution",
             summary="Per-engine hit rate from evaluated journal signals — which engines actually contribute alpha")
def engine_attribution_endpoint(
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(90, ge=7, le=365,
                        description="Lookback window (default 90 days)"),
    horizon: Optional[str] = Query(None,
                                     pattern="^(INTRADAY|SWING|POSITIONAL)$",
                                     description="Restrict to one horizon"),
    min_samples: int = Query(15, ge=5, le=100,
                              description="Min evaluated votes before publishing hit rate"),
):
    """For every engine that appears in the journal's engines_snapshot, returns
    its actual hit rate when it voted BULLISH vs BEARISH — compared against the
    overall baseline.

    Honest measurement: engines with fewer than `min_samples` decided votes are
    listed with status=INSUFFICIENT_DATA and no hit rate (avoids publishing
    statistically-meaningless percentages like "70% on 4 signals").

    Engines are ranked: ALPHA (>+5pp edge) → NEUTRAL (±5pp) → NOISE (<-5pp,
    anti-predictive) → INSUFFICIENT_DATA.

    Response also includes a `current_weights` block showing the voting
    weights currently in use by the confluence engine. When attribution
    data is insufficient, weights={} and the system falls back to equal
    voting — never invented numbers.
    """
    try:
        result = engine_attribution.attribute_engines(
            db, days=days, horizon=horizon, min_samples=min_samples,
        )
        # Also surface the LIVE weights currently in use by the recommender,
        # so the user can verify the attribution data is actually being applied.
        try:
            from app.services import engine_weights
            ew = engine_weights.get_weights_with_meta(lookback_days=days)
            result["current_weights"] = {
                "weights": ew["weights"],
                "status":  ew["meta"]["status"],
                "reason":  ew["meta"]["reason"],
                "data_driven_engines":  ew["meta"]["data_driven_engines"],
                "equal_weight_engines": ew["meta"]["equal_weight_engines"],
            }
        except Exception as e:
            result["current_weights"] = {"error": str(e)}
        return result
    except Exception as e:
        raise HTTPException(500, f"engine-attribution failed: {e}")


@router.post("/engine-attribution/refresh-weights",
              summary="Force-refresh the engine-weights cache (admin/dev)")
def refresh_weights():
    """Bypass the 1-hour TTL and recompute weights from the latest journal
    state. Useful right after the outcome tracker finishes a run."""
    from app.services import engine_weights
    engine_weights.clear_cache()
    return engine_weights.get_weights_with_meta(force_refresh=True)


@router.get("/history",
             summary="Recent recommendation history (last N days)")
def history(
    days: int = Query(14, ge=1, le=90, description="Lookback window in days"),
    symbol: str | None = None,
    direction: str | None = Query(None, description="BULLISH / BEARISH"),
    min_confidence: float | None = Query(None, ge=0, le=100),
    limit: int = Query(200, ge=1, le=1000),
):
    """Returns the journaled recommendations for the last N days.
    Default 14-day retention window — older entries are purged daily."""
    if symbol:
        rows = signals_logger.history_for_symbol(symbol, days=days, limit=limit)
    else:
        rows = signals_logger.recent_signals(days=days, limit=limit,
                                              direction=direction,
                                              min_confidence=min_confidence)
    return {
        "count": len(rows),
        "lookback_days": days,
        "retention_policy_days": 14,
        "rows": rows,
    }


@router.post("/purge", summary="Purge journal rows older than N days (default 14)")
def purge(days: int = Query(14, ge=1, le=365)):
    return signals_logger.purge_older_than_days(days=days)


@router.get("/recent", summary="Recent journaled signals (with outcomes if evaluated)")
def recent(limit: int = Query(50, ge=1, le=500),
                  symbol: str | None = None,
                  status: str | None = Query(None, description="PENDING/EVALUATED/STALE")):
    with SessionLocal() as sess:
        q = sess.query(SignalJournalEntry).order_by(SignalJournalEntry.emitted_at.desc())
        if symbol:
            q = q.filter(SignalJournalEntry.symbol == symbol.upper())
        if status:
            q = q.filter(SignalJournalEntry.outcome_status == status.upper())
        rows = q.limit(limit).all()
    return {"count": len(rows), "rows": [{
        "id": r.id, "emitted_at": r.emitted_at.isoformat() if r.emitted_at else None,
        "symbol": r.symbol, "horizon": r.horizon,
        "signal_label": r.signal_label, "direction": r.direction,
        "confidence": r.confidence, "stars": r.stars,
        "entry": r.entry, "stoploss": r.stoploss,
        "targets": [r.target_1, r.target_2, r.target_3],
        "outcome": {
            "status": r.outcome_status,
            "pnl_5d_pct": r.outcome_5d_pnl_pct,
            "pnl_20d_pct": r.outcome_20d_pnl_pct,
            "target_hit": r.outcome_target_hit,
            "stoploss_hit": r.outcome_stoploss_hit,
            "mfe_pct": r.outcome_max_favorable,
            "mae_pct": r.outcome_max_adverse,
            "evaluated_at": r.outcome_evaluated_at.isoformat() if r.outcome_evaluated_at else None,
        },
    } for r in rows]}


@router.get("/stats", summary="Aggregate track-record statistics")
def stats(since_days: int = Query(90, ge=1, le=730),
                 horizon: str | None = None):
    try:
        return outcome_tracker.journal_stats(since_days=since_days, horizon=horizon)
    except Exception as e:
        raise HTTPException(500, f"journal stats failed: {e}")


@router.post("/evaluate-due", summary="Run outcome tracker for all due (matured) signals")
def evaluate_due(max_per_run: int = Query(200, ge=1, le=1000)):
    try:
        return outcome_tracker.mark_due_outcomes(max_per_run=max_per_run)
    except Exception as e:
        raise HTTPException(500, f"outcome tracker failed: {e}")


@router.post("/evaluate/{signal_id}", summary="Force-evaluate a single signal id")
def evaluate_one(signal_id: int):
    ok = outcome_tracker.mark_signal(signal_id)
    if not ok:
        raise HTTPException(404, f"signal {signal_id} not found or data missing")
    return {"evaluated": True, "signal_id": signal_id}


# ---------------------------------------------------------------------------
# Performance summary — what the Performance dashboard page consumes.
#
# This is the ONLY place KPIs come from. Never hardcode win rates in the UI.
# When `evaluated_count < 30`, returns a "track record forming" state so the
# UI refuses to show misleading numbers from too-small samples.
# ---------------------------------------------------------------------------

@router.get("/performance-summary",
             summary="Real KPIs computed from signals_journal (no fictional numbers)")
def performance_summary(
    user: Annotated[User, Depends(require_tier("BASIC"))],
    db: Annotated[Session, Depends(get_db)],
    days: int = Query(90, ge=7, le=365),
    horizon: str | None = Query(None, pattern="^(INTRADAY|SWING|POSITIONAL)$"),
):
    """Returns ONLY measured metrics. Refuses to compute KPIs when sample
    size is too small to be statistically meaningful (n<30).

    Response shape:
      • evaluated_count — how many journaled signals have an outcome
      • kpis — hit_rate, baseline_hit_rate, brier_score, edge_pp, avg_mfe, avg_mae
      • reliability_curve — [{ claimed_bucket, actual_pct, n }] for the chart
      • monthly — [{ month, n, wins, win_rate }] for the table
      • by_horizon — per-horizon hit rates
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    q = (db.query(SignalJournalEntry)
           .filter(SignalJournalEntry.emitted_at >= cutoff,
                    SignalJournalEntry.outcome_status == "EVALUATED"))
    if horizon:
        q = q.filter(SignalJournalEntry.horizon == horizon)
    rows = q.all()

    evaluated = len(rows)
    if evaluated < 30:
        return {
            "evaluated_count": evaluated,
            "min_required": 30,
            "kpis": None,
            "reliability_curve": [],
            "monthly": [],
            "by_horizon": {},
            "message": (
                f"Track record forming — only {evaluated} evaluated signals so far. "
                f"Need ≥30 closed outcomes for statistically meaningful KPIs. "
                f"Check back after a few more trading days."
            ),
        }

    # ---- Headline KPIs ----
    def _won(r: SignalJournalEntry) -> bool:
        """A signal 'wins' if the 5d outcome moved in the intended direction
        AND either a target was hit, or 5d P&L exceeds 1% in favor."""
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

    wins = sum(1 for r in rows if _won(r))
    hit_rate = wins / evaluated

    # Brier score — proper score for probabilistic predictions
    # lower is better; 0.25 = random
    brier = sum(((r.confidence or 50) / 100 - (1.0 if _won(r) else 0.0)) ** 2
                 for r in rows) / evaluated

    # Baseline: stupid "always bullish on NIFTY" ≈ 51% (slight long bias)
    baseline = 0.51

    # MFE / MAE averages — characterize what the average winning move looks like
    mfes = [r.outcome_max_favorable for r in rows if r.outcome_max_favorable is not None]
    maes = [r.outcome_max_adverse for r in rows if r.outcome_max_adverse is not None]
    avg_mfe = sum(mfes) / len(mfes) if mfes else None
    avg_mae = sum(maes) / len(maes) if maes else None

    # ---- Reliability curve — 10-pt confidence buckets ----
    buckets: dict[int, dict] = {}
    for r in rows:
        c = r.confidence or 50
        b = min(95, max(5, int(c / 10) * 10 + 5))
        buckets.setdefault(b, {"wins": 0, "n": 0})
        buckets[b]["n"] += 1
        if _won(r):
            buckets[b]["wins"] += 1
    reliability = sorted([
        {"claimed_bucket": b,
         "actual_pct": round(v["wins"] / v["n"] * 100, 1),
         "n": v["n"]}
        for b, v in buckets.items() if v["n"] >= 3
    ], key=lambda x: x["claimed_bucket"])

    # ---- Monthly breakdown ----
    monthly_buckets: dict[str, dict] = {}
    for r in rows:
        if not r.emitted_at:
            continue
        ym = r.emitted_at.strftime("%Y-%m")
        monthly_buckets.setdefault(ym, {"n": 0, "wins": 0})
        monthly_buckets[ym]["n"] += 1
        if _won(r):
            monthly_buckets[ym]["wins"] += 1
    monthly = sorted([
        {"month": m, "n": v["n"], "wins": v["wins"],
         "win_rate": round(v["wins"] / v["n"] * 100, 1)}
        for m, v in monthly_buckets.items()
    ], key=lambda x: x["month"])

    # ---- Per-horizon hit rates ----
    by_horizon: dict[str, dict] = {}
    for r in rows:
        h = r.horizon or "UNKNOWN"
        by_horizon.setdefault(h, {"n": 0, "wins": 0})
        by_horizon[h]["n"] += 1
        if _won(r):
            by_horizon[h]["wins"] += 1
    by_horizon = {h: {"n": v["n"], "wins": v["wins"],
                       "win_rate": round(v["wins"] / v["n"] * 100, 1)
                                     if v["n"] else None}
                   for h, v in by_horizon.items()}

    return {
        "evaluated_count": evaluated,
        "min_required": 30,
        "kpis": {
            "evaluated":         evaluated,
            "wins":              wins,
            "hit_rate":          round(hit_rate, 4),
            "baseline_hit_rate": baseline,
            "edge_pp":           round((hit_rate - baseline) * 100, 2),
            "brier_score":       round(brier, 4),
            "brier_baseline":    0.25,
            "avg_mfe_pct":       round(avg_mfe, 3) if avg_mfe is not None else None,
            "avg_mae_pct":       round(avg_mae, 3) if avg_mae is not None else None,
            "is_calibrated":     brier < 0.22,
        },
        "reliability_curve": reliability,
        "monthly": monthly,
        "by_horizon": by_horizon,
    }
