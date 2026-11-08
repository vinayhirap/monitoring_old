"""Background maintenance for the signals journal.

Without this, nothing scores signals when Celery is not running, so the
learning loop (engine attribution, engine weights, confidence calibration)
never receives outcomes. Call `start()` once at app startup.
"""
from __future__ import annotations

import threading
import time

from loguru import logger

_started = False
_lock = threading.Lock()


def run_once() -> dict:
    """Score matured signals, then apply retention. Never raises."""
    out: dict = {}
    try:
        from app.services.outcome_tracker import mark_due_outcomes
        out["outcomes"] = mark_due_outcomes()
    except Exception as e:
        out["outcomes_error"] = str(e)
        logger.warning("journal maintenance: outcome tracker failed: {}", e)
    try:
        from app.services.signals_logger import purge_older_than_days
        out["purge"] = purge_older_than_days()
    except Exception as e:
        out["purge_error"] = str(e)
        logger.debug("journal maintenance: purge failed: {}", e)
    logger.info("Journal maintenance run: {}", out)
    return out


def start(*, first_delay_sec: int = 300, interval_sec: int = 6 * 3600) -> bool:
    """Start the daemon thread once. Returns False if already running."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True

    def _loop():
        time.sleep(first_delay_sec)
        while True:
            run_once()
            time.sleep(interval_sec)

    threading.Thread(target=_loop, name="journal-maintenance", daemon=True).start()
    logger.info("Journal maintenance thread started (outcome scoring + retention every {}h)",
                interval_sec // 3600)
    return True
