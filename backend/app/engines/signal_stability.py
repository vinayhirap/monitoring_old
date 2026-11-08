"""Signal stability / hysteresis layer.

Solves the "recommendations keep flipping" problem.

The decision engine is stateless — each call recomputes from current bars,
planetary positions, and IV. Small noise (an ATR uptick, Moon crossing into
the next pada, IV +0.5%) can flip a BUY to HOLD and back.

This layer adds *persistence*: the rendered recommendation only changes when
either (a) the new confidence differs by ≥ Δ from the displayed one, or
(b) the direction has flipped twice in the same direction, or (c) the
time-since-last-change exceeds the displayed signal's natural horizon.

Persistence is keyed by `(symbol, horizon)` in a tiny SQLite-backed store —
so it survives backend restarts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import threading

from sqlalchemy import Column, String, Float, DateTime, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


Base = declarative_base()


class StableSignal(Base):
    __tablename__ = "stable_signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, index=True, nullable=False)
    horizon = Column(String, index=True, nullable=False)
    displayed_label = Column(String, nullable=False)
    displayed_direction = Column(String, nullable=False)
    displayed_confidence = Column(Float, nullable=False)
    flip_count = Column(Integer, default=0)
    last_change_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


_engine = create_engine(settings.database_url, future=True, connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine, future=True)
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Tunables — change these to make signals stickier or twitchier
# ---------------------------------------------------------------------------

CONFIDENCE_DELTA_TO_FLIP = 8.0      # need 8pp move to overwrite displayed signal
DIRECTION_FLIP_TOLERANCE = 2        # require 2 same-direction reads before flip
MIN_HOLD_MINUTES = {
    "INTRADAY":    15,              # don't flip more often than every 15 min
    "SWING":       240,             # 4 hours
    "POSITIONAL":  1440,            # 24 hours
}


@dataclass
class StabilityDecision:
    use_new: bool                   # whether to display the new candidate
    displayed_label: str
    displayed_confidence: float
    displayed_direction: str
    stability_score: float          # 0..100 — how stable this displayed signal is
    minutes_since_last_change: float
    flip_count_window: int
    rationale: str

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def evaluate(symbol: str, horizon: str, new_label: str, new_direction: str,
             new_confidence: float, now: datetime | None = None) -> StabilityDecision:
    """Decide whether to display the NEW candidate signal or stick with the
    currently-displayed one.

    Persistence rules (any one triggers a flip to NEW):
      • new confidence differs from displayed by >= CONFIDENCE_DELTA_TO_FLIP
      • new direction has flipped same-way for DIRECTION_FLIP_TOLERANCE reads
      • time since last change exceeds horizon's MIN_HOLD_MINUTES
      • displayed signal doesn't exist yet (first observation)

    Returns the decision plus stability metrics.
    """
    now = now or datetime.utcnow()

    with _lock, _Session() as sess:
        row: Optional[StableSignal] = (
            sess.query(StableSignal)
            .filter_by(symbol=symbol, horizon=horizon)
            .one_or_none()
        )

        # First time we've seen this symbol/horizon — install the new signal
        if row is None:
            row = StableSignal(
                symbol=symbol, horizon=horizon,
                displayed_label=new_label,
                displayed_direction=new_direction,
                displayed_confidence=new_confidence,
                flip_count=0,
                last_change_at=now,
                updated_at=now,
            )
            sess.add(row)
            sess.commit()
            return StabilityDecision(
                use_new=True,
                displayed_label=new_label,
                displayed_confidence=new_confidence,
                displayed_direction=new_direction,
                stability_score=100.0,
                minutes_since_last_change=0.0,
                flip_count_window=0,
                rationale="First observation — installed as displayed signal",
            )

        # ---- Compute deltas ----
        minutes_since = (now - row.last_change_at).total_seconds() / 60
        conf_delta = abs(new_confidence - row.displayed_confidence)
        direction_flipped = new_direction != row.displayed_direction
        min_hold = MIN_HOLD_MINUTES.get(horizon, 240)

        # ---- Decide whether to flip ----
        flip_reason = None
        if minutes_since >= min_hold and (direction_flipped or conf_delta >= CONFIDENCE_DELTA_TO_FLIP):
            flip_reason = (
                f"Min hold of {min_hold}m elapsed ({minutes_since:.0f}m since last change); "
                f"{'direction flipped' if direction_flipped else f'Δconfidence={conf_delta:.1f}pp ≥ {CONFIDENCE_DELTA_TO_FLIP}'}"
            )
        elif conf_delta >= CONFIDENCE_DELTA_TO_FLIP * 2:
            flip_reason = f"Large Δconfidence={conf_delta:.1f}pp — flipping despite min-hold"
        elif direction_flipped:
            row.flip_count = (row.flip_count or 0) + 1
            if row.flip_count >= DIRECTION_FLIP_TOLERANCE:
                flip_reason = (
                    f"Direction has flipped {row.flip_count}x — committing to {new_direction}"
                )

        if flip_reason:
            # Commit the new signal
            row.displayed_label = new_label
            row.displayed_direction = new_direction
            row.displayed_confidence = new_confidence
            row.flip_count = 0
            row.last_change_at = now
            row.updated_at = now
            sess.commit()
            return StabilityDecision(
                use_new=True,
                displayed_label=new_label,
                displayed_confidence=new_confidence,
                displayed_direction=new_direction,
                stability_score=_stability_score(0, 0),
                minutes_since_last_change=0.0,
                flip_count_window=0,
                rationale=flip_reason,
            )

        # ---- Stick with displayed signal ----
        row.updated_at = now
        sess.commit()
        return StabilityDecision(
            use_new=False,
            displayed_label=row.displayed_label,
            displayed_confidence=row.displayed_confidence,
            displayed_direction=row.displayed_direction,
            stability_score=_stability_score(minutes_since, row.flip_count or 0),
            minutes_since_last_change=round(minutes_since, 1),
            flip_count_window=row.flip_count or 0,
            rationale=(
                f"Stuck with {row.displayed_label} "
                f"(Δconfidence={conf_delta:.1f}pp < {CONFIDENCE_DELTA_TO_FLIP}, "
                f"{minutes_since:.0f}m since change, min hold {min_hold}m)"
            ),
        )


def _stability_score(minutes_since_change: float, flip_count: int) -> float:
    """Higher = more stable. Decays with flip_count, grows with time held."""
    base = min(100.0, minutes_since_change / 60 * 25)    # +25 per hour stable, cap 100
    penalty = flip_count * 15
    return max(0.0, min(100.0, base - penalty + 50))     # +50 baseline


# ---------------------------------------------------------------------------
# Maintenance — clear stale rows
# ---------------------------------------------------------------------------

def cleanup_older_than(days: int = 30) -> int:
    """Remove rows not updated in N days (e.g. delisted symbols)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with _lock, _Session() as sess:
        n = sess.query(StableSignal).filter(StableSignal.updated_at < cutoff).delete()
        sess.commit()
        return n


def get_current(symbol: str, horizon: str) -> dict | None:
    with _lock, _Session() as sess:
        row = sess.query(StableSignal).filter_by(symbol=symbol, horizon=horizon).one_or_none()
        if row is None:
            return None
        return {
            "symbol": row.symbol,
            "horizon": row.horizon,
            "displayed_label": row.displayed_label,
            "displayed_direction": row.displayed_direction,
            "displayed_confidence": row.displayed_confidence,
            "last_change_at": row.last_change_at.isoformat(),
            "minutes_since_change": round(
                (datetime.utcnow() - row.last_change_at).total_seconds() / 60, 1
            ),
            "stability_score": _stability_score(
                (datetime.utcnow() - row.last_change_at).total_seconds() / 60,
                row.flip_count or 0,
            ),
        }
