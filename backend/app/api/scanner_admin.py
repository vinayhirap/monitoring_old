"""Scanner admin endpoints — see what universe the background scanner is
sweeping, what the prefilter dropped, and trigger a manual deep scan.

All endpoints are admin-only (require_role ≥ ADMIN). The scanner runs on
a 5-minute schedule by default; admins can force an immediate pass via
the trigger endpoint.

Endpoints:
  GET  /api/admin/scanner/config       — current universe + prefilter setting
  POST /api/admin/scanner/trigger      — force one scan pass now
  GET  /api/admin/scanner/last-scan    — most recent scanner-pass summary
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_current_admin, get_db
from app.models.user import User
from app.models.live_picks import LivePicksSnapshot
from app.jobs import picks_scanner


router = APIRouter()


# ---------------------------------------------------------------------------
# Read-only: see what the scanner is configured to do
# ---------------------------------------------------------------------------

@router.get("/config",
             summary="Current scanner universe + prefilter settings (admin only)")
def scanner_config(
    _: Annotated[User, Depends(get_current_admin)],
):
    """Returns the env-driven scanner configuration so the admin can see at a
    glance what universe is being swept. Change via env vars SCANNER_UNIVERSE
    and SCANNER_PREFILTER, then restart the backend.

    Universe options (largest → smallest):
      • all_nse   ~2000 NSE equity symbols — broadest, slowest, prefilter on
      • nifty500  ~500  Nifty 500 + F&O    — broad, prefilter on by default
      • fno       ~180  F&O universe       — current default
      • fno_top50 ~50   most-liquid F&O   — fastest, narrowest
    """
    # Resolve the universe to its actual size for confirmation
    from app.services.universe import universe_for
    try:
        universe = universe_for(picks_scanner.SCANNER_UNIVERSE)
        universe_size = len(universe)
        universe_first_few = universe[:5]
    except Exception as e:
        universe_size = -1
        universe_first_few = []

    return {
        "scanner_universe":  picks_scanner.SCANNER_UNIVERSE,
        "universe_size":     universe_size,
        "universe_preview":  universe_first_few,
        "prefilter_setting": picks_scanner.SCANNER_PREFILTER or "auto",
        "prefilter_active":  picks_scanner._resolve_prefilter_flag(),
        "scan_interval_min": picks_scanner.SCAN_INTERVAL_MINUTES,
        "precomputed_combos": [
            {"horizon": h, "min_stars": m, "top_n": n}
            for h, m, n in picks_scanner.PRECOMPUTED_PARAMS
        ],
        "available_universes": ["fno_top50", "fno", "nifty500", "all_nse"],
        "how_to_change": (
            "Set env var SCANNER_UNIVERSE=nifty500 (or all_nse) and restart backend. "
            "Optionally SCANNER_PREFILTER=1/0 to force prefilter on/off."
        ),
    }


# ---------------------------------------------------------------------------
# Trigger an immediate scan pass (admin only)
# ---------------------------------------------------------------------------

@router.post("/trigger",
              summary="Force the background scanner to run NOW (admin only)")
def scanner_trigger(
    _: Annotated[User, Depends(get_current_admin)],
):
    """Synchronously runs one full scanner pass. Returns the summary the
    job-runner normally writes to logs.

    This can take 30s–5min depending on universe size. The HTTP request
    will block until done — for batch workflows prefer scheduling.
    """
    try:
        summary = picks_scanner.run_once()
        return {"ok": True, "summary": summary}
    except Exception as e:
        raise HTTPException(500, f"scanner trigger failed: {e}")


# ---------------------------------------------------------------------------
# Last-scan stats — what did the most recent pass actually do?
# ---------------------------------------------------------------------------

@router.get("/last-scan",
             summary="Most recent scanner-pass summary, per combo (admin only)")
def last_scan(
    _: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Returns the latest snapshot from each precomputed combo, with timing
    and universe-coverage data. Useful for diagnosing slow scans, empty
    picks, or prefilter behaviour.
    """
    rows = (
        db.query(LivePicksSnapshot)
          .order_by(LivePicksSnapshot.scanned_at.desc())
          .limit(20)
          .all()
    )
    out = []
    for r in rows:
        payload = r.payload or {}
        out.append({
            "horizon":       r.horizon,
            "min_stars":     r.min_stars,
            "scanned_at":    r.scanned_at.isoformat() if r.scanned_at else None,
            "duration_ms":   r.scan_duration_ms,
            "n_symbols_scanned": r.symbols_scanned,
            "top_buy_count":  len(payload.get("top_buy") or []),
            "top_sell_count": len(payload.get("top_sell") or []),
            "universe_name":  payload.get("universe_name"),
            "prefilter":      payload.get("prefilter"),
        })
    return {"snapshots": out, "count": len(out)}
