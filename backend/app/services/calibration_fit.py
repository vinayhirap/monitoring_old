"""Calibrated confidence — turn raw composite scores into honest probabilities.

Why this exists:

The unified `/api/symbol/{ticker}` endpoint returns a `confidence` value that
is a weighted sum of ~17 engine scores. Nothing about that math guarantees
that "70" actually corresponds to 70% historical win rate. If the system
over-confidently says 80 but actually wins 55% of the time at that bucket,
users see misleading numbers — the exact regulatory + ethical problem we've
been trying to avoid.

Isotonic regression solves this:
  • Takes (raw_score, won_or_not) pairs from `signals_journal`
  • Fits a monotonically-non-decreasing step function that maps raw → calibrated
  • Returns a calibrator that the recommendation engine can apply at runtime

Usage:
    cal = fit_from_journal(db, min_samples=300)
    if cal:
        displayed_confidence = cal.calibrate(raw_score)  # 0..100
    else:
        displayed_confidence = raw_score    # not enough data yet — use raw

The fitted calibrator is cached in memory (refit on a schedule, not per
request). When journal data <300 rows, returns None and the API falls back
to raw scores — better than a bad calibrator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Optional

from loguru import logger

from app.models.signals_journal import SignalJournalEntry


# ---------------------------------------------------------------------------
# Pool Adjacent Violators (PAV) — minimal isotonic regression implementation.
# Avoids a hard scikit-learn dependency. Same output as sklearn's
# IsotonicRegression(out_of_bounds='clip') for our use case.
# ---------------------------------------------------------------------------

def _pav_isotonic(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Pool-Adjacent-Violators algorithm. Returns (x_knots, y_knots) where
    y_knots is monotonically non-decreasing.

    xs must be pre-sorted ascending. ys are 0/1 indicators (won or not).
    Standard PAV: merge adjacent groups whose means violate monotonicity.
    """
    # Each group is (sum_of_y, count, sum_of_x_for_centroid)
    groups: list[list[float]] = [[y, 1, x] for x, y in zip(xs, ys)]
    i = 0
    while i < len(groups) - 1:
        cur_mean  = groups[i][0]     / groups[i][1]
        next_mean = groups[i + 1][0] / groups[i + 1][1]
        if cur_mean > next_mean:
            # Merge
            groups[i][0] += groups[i + 1][0]
            groups[i][1] += groups[i + 1][1]
            groups[i][2] += groups[i + 1][2]
            del groups[i + 1]
            # Step back to re-check the prior group
            i = max(i - 1, 0)
        else:
            i += 1
    x_knots = [g[2] / g[1] for g in groups]
    y_knots = [g[0] / g[1] for g in groups]
    return x_knots, y_knots


# ---------------------------------------------------------------------------
# Calibrator
# ---------------------------------------------------------------------------

@dataclass
class Calibrator:
    """Maps raw confidence 0..100 → calibrated probability 0..100.

    Internal representation is the PAV step function (x_knots, y_knots).
    `calibrate()` does linear interpolation between knots; outside the
    fitted range we clamp to the endpoint y values.
    """
    x_knots: list[float]
    y_knots: list[float]
    n_samples: int
    fitted_at: datetime
    brier_before: float           # raw-score Brier — calibration target to beat
    brier_after: float            # post-calibration Brier on training data

    def calibrate(self, raw_score: float) -> float:
        if not self.x_knots:
            return raw_score
        x = max(0.0, min(100.0, raw_score))
        # Clamp to fitted range
        if x <= self.x_knots[0]:
            return self.y_knots[0] * 100.0
        if x >= self.x_knots[-1]:
            return self.y_knots[-1] * 100.0
        # Linear interpolation between adjacent knots
        for i in range(len(self.x_knots) - 1):
            if self.x_knots[i] <= x <= self.x_knots[i + 1]:
                x0, x1 = self.x_knots[i], self.x_knots[i + 1]
                y0, y1 = self.y_knots[i], self.y_knots[i + 1]
                if x1 == x0:
                    return y0 * 100.0
                t = (x - x0) / (x1 - x0)
                return (y0 + t * (y1 - y0)) * 100.0
        return self.y_knots[-1] * 100.0

    def to_dict(self) -> dict:
        return {
            "n_samples": self.n_samples,
            "fitted_at": self.fitted_at.isoformat(),
            "brier_before": round(self.brier_before, 4),
            "brier_after":  round(self.brier_after, 4),
            "improvement_pp": round((self.brier_before - self.brier_after) * 100, 2),
            "knots": [
                {"raw": round(x, 2), "calibrated_pct": round(y * 100, 2)}
                for x, y in zip(self.x_knots, self.y_knots)
            ],
        }


# ---------------------------------------------------------------------------
# In-memory cache (thread-safe). Refit on a schedule, not per request.
# ---------------------------------------------------------------------------

_calibrator_cache: Optional[Calibrator] = None
_cache_lock = Lock()
_REFIT_INTERVAL_HOURS = 6


def get_active_calibrator() -> Optional[Calibrator]:
    """Returns the cached calibrator if it's still fresh, else None.
    Callers can decide to refit by calling refit_calibrator()."""
    with _cache_lock:
        if _calibrator_cache is None:
            return None
        age = datetime.utcnow() - _calibrator_cache.fitted_at
        if age > timedelta(hours=_REFIT_INTERVAL_HOURS):
            return None     # stale — caller should refit
        return _calibrator_cache


def _won(r: SignalJournalEntry) -> int:
    """Same win definition used in performance_summary endpoint."""
    if r.outcome_target_hit and r.outcome_target_hit > 0:
        return 1
    if r.outcome_stoploss_hit:
        return 0
    pnl = r.outcome_5d_pnl_pct or 0
    if r.direction == "BULLISH" and pnl > 1.0:
        return 1
    if r.direction == "BEARISH" and pnl < -1.0:
        return 1
    return 0


def fit_from_journal(db, min_samples: int = 300, lookback_days: int = 180
                      ) -> Optional[Calibrator]:
    """Fit isotonic calibrator from evaluated journal entries.

    Returns None if the journal doesn't have enough samples — caller should
    fall back to raw scores. Below min_samples, a fitted calibrator is more
    misleading than useful.
    """
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    rows = (db.query(SignalJournalEntry)
              .filter(SignalJournalEntry.emitted_at >= cutoff,
                       SignalJournalEntry.outcome_status == "EVALUATED",
                       SignalJournalEntry.confidence.isnot(None))
              .all())
    if len(rows) < min_samples:
        logger.info("Calibration skipped — only {} evaluated rows (need {})",
                     len(rows), min_samples)
        return None

    # Sort by raw confidence ascending (required by PAV)
    pairs = sorted([(r.confidence, _won(r)) for r in rows], key=lambda t: t[0])
    xs = [p[0] for p in pairs]
    ys = [float(p[1]) for p in pairs]

    # Pre-cal Brier on training data
    brier_before = sum((x / 100 - y) ** 2 for x, y in zip(xs, ys)) / len(xs)

    x_knots, y_knots = _pav_isotonic(xs, ys)

    cal = Calibrator(
        x_knots=x_knots, y_knots=y_knots,
        n_samples=len(rows),
        fitted_at=datetime.utcnow(),
        brier_before=brier_before,
        brier_after=0.0,   # filled below
    )

    # Post-cal Brier on training data (lower-bound — real test is held-out)
    brier_after = sum(
        ((cal.calibrate(x) / 100) - y) ** 2 for x, y in zip(xs, ys)
    ) / len(xs)
    cal.brier_after = brier_after

    logger.info("Calibrator fitted: n={}, Brier {:.4f} → {:.4f} (Δ {:.2f}pp)",
                  cal.n_samples, brier_before, brier_after,
                  (brier_before - brier_after) * 100)

    with _cache_lock:
        global _calibrator_cache
        _calibrator_cache = cal
    return cal


def refit_calibrator(db, force: bool = False) -> Optional[Calibrator]:
    """Refit if cache is stale OR force=True. Safe to call frequently —
    only does work when the cache age exceeds the refit interval."""
    if not force:
        existing = get_active_calibrator()
        if existing is not None:
            return existing
    return fit_from_journal(db)


def calibrate_confidence(raw_score: float, db=None) -> tuple[float, bool]:
    """Convenience: returns (calibrated_value, was_calibrated).

    When no fitted calibrator is available (too few samples), returns the
    raw score unchanged with was_calibrated=False so the caller can decide
    how to display it (e.g. label the number "raw" vs "calibrated").
    """
    cal = get_active_calibrator()
    if cal is None:
        return raw_score, False
    return cal.calibrate(raw_score), True
