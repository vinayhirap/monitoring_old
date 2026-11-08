"""Cache table for the background scanner's output.

Why this exists:

Today `/api/portal/top-picks` runs `recommender.professional_scan()` inline
on every request. Under load this:
  • Hammers Angel One (each scan = N symbols × multiple historical calls)
  • Blocks the request for 5-30 seconds depending on universe size
  • Makes throughput dependent on scan latency, not API capacity

The fix: a background job runs the scan every N minutes and writes results
to this table. The API endpoint reads the freshest row instead of running
the scan. Request latency drops from seconds → milliseconds, and Angel One
calls per minute become bounded regardless of user traffic.

If the table is stale (no row newer than freshness_seconds) the API can
either:
  • Fall back to inline scan (compatibility mode)
  • Return the stale row with `is_stale=true` flag for the UI

We default to the stale-row strategy — better than blocking requests.
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, Index
from sqlalchemy.sql import func

from app.database import Base


class LivePicksSnapshot(Base):
    """One row per (horizon, min_stars) parameter combination.
    The scanner overwrites the row for the same key on each run."""
    __tablename__ = "live_picks_snapshots"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    horizon      = Column(String(16), nullable=False, index=True)
    min_stars    = Column(Integer,   nullable=False, index=True)

    # JSON payload — same shape the API returned before (top_buy + top_sell arrays)
    payload      = Column(JSON, nullable=False)

    # Freshness tracking
    scanned_at   = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    scan_duration_ms = Column(Integer)
    symbols_scanned  = Column(Integer)

    __table_args__ = (
        # Unique per (horizon, min_stars) — one snapshot per param combo
        Index("ix_live_picks_unique_key", "horizon", "min_stars", unique=True),
    )
