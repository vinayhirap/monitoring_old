"""Background scanner that pre-computes `top-picks` for the portal API.

How it runs:
  • An APScheduler BackgroundScheduler is started in app.main on startup
  • It calls run_once() every SCAN_INTERVAL_MINUTES
  • Each run scans a fixed set of (horizon, min_stars) combinations
  • Results are upserted into the `live_picks_snapshots` table

How the API reads:
  • /api/portal/top-picks now calls latest_snapshot(horizon, min_stars)
  • If a fresh row exists, return it (millisecond response)
  • If no fresh row, fall back to inline scan (compatibility mode)
  • If a stale row exists, return it WITH is_stale=true flag

Manual trigger:
  • Admins can POST /api/admin/scanner/trigger to force an immediate run
    (added separately if needed)
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.live_picks import LivePicksSnapshot


import os


SCAN_INTERVAL_MINUTES = 5
FRESHNESS_THRESHOLD_SECONDS = 600     # 10 min — a 5-min interval +slack

# ----- Universe selection (env-driven) -----
# Which symbol pool the scanner sweeps. Tradeoffs:
#   fno_top50  → ~30s per combo, fastest, narrowest
#   fno        → ~60s per combo, F&O 180 universe
#   nifty500   → ~90s per combo with prefilter (DEFAULT — best breadth vs speed)
#   all_nse    → ~2-3 min per combo with prefilter on (~2000 symbols)
#
# Default changed to `nifty500` so the scanner covers F&O + mid-caps out of
# the box. The prefilter (auto-on above 250 symbols) does one batched broker
# call to narrow to ~250 high-liquidity candidates before the per-symbol
# pipeline runs, keeping scan time bounded.
#
# Set SCANNER_UNIVERSE in env to override.
SCANNER_UNIVERSE   = os.getenv("SCANNER_UNIVERSE", "nifty500").lower()
# Set "1"/"0" to force prefilter on/off, or leave unset for auto.
SCANNER_PREFILTER  = os.getenv("SCANNER_PREFILTER", "").strip()

def _resolve_prefilter_flag() -> bool | None:
    if SCANNER_PREFILTER == "1": return True
    if SCANNER_PREFILTER == "0": return False
    return None      # auto

# Fixed set of param combinations the scanner pre-computes. If a user
# requests a combo outside this set, the API falls back to inline scan.
PRECOMPUTED_PARAMS = [
    # (horizon, min_stars, top_n)
    ("INTRADAY",   3, 20),
    ("INTRADAY",   4, 20),
    ("SWING",      3, 20),
    ("SWING",      4, 20),
    ("SWING",      5, 20),
    ("POSITIONAL", 3, 20),
    ("POSITIONAL", 4, 20),
]


def _strip_pick(p: dict) -> dict:
    """Same shape `/api/portal/top-picks` returns. Kept in sync with portal.py.

    Also includes the meta-learner prediction when the model is trustworthy.
    Picks where the model disagrees with the rule-based direction get
    flagged via `ai_concur` — high-conviction picks are those where the
    AI and rules agree.
    """
    g = p.get("grade", {}) or {}
    raw = p.get("raw_signal", {}) or {}
    instrument_ranking = g.get("instrument_ranking", [{}]) or [{}]

    # ---- Meta-learner enrichment ----
    # Build a feature vector from the engines snapshot the scanner already
    # has, ask the online learner for P(win). Microsecond cost per pick.
    ai_p_win = None
    ai_trustworthy = False
    ai_concur = None
    try:
        from app.services import online_learner
        engines_snapshot = p.get("engines") or p.get("engines_snapshot") or {}
        regime = (p.get("quant") or {}).get("regime") if p.get("quant") else None
        features = online_learner.build_feature_vector(
            engines_snapshot=engines_snapshot, regime=regime,
        )
        p_win, trustworthy = online_learner.predict(features)
        ai_p_win = round(p_win * 100, 1)
        ai_trustworthy = trustworthy
        # AI agrees if its P(win) is >55 (bullish direction) or <45 (bearish)
        # and that matches the rule-based direction
        if trustworthy:
            ai_bullish = p_win > 0.55
            ai_bearish = p_win < 0.45
            rule_dir = g.get("direction") or ""
            if rule_dir.upper() in ("BULLISH", "BUY"):
                ai_concur = ai_bullish
            elif rule_dir.upper() in ("BEARISH", "SELL"):
                ai_concur = ai_bearish
    except Exception:
        # Scanner must never break because of the AI layer
        pass

    return {
        "symbol": p["symbol"],
        "sector": p.get("sector"),
        "label": g.get("conviction_label"),
        "stars": g.get("stars"),
        "direction": g.get("direction"),
        "confidence": g.get("confidence"),
        "entry": raw.get("entry"),
        "stoploss": raw.get("stoploss"),
        "targets": raw.get("targets", []),
        "best_instrument": (instrument_ranking[0] or {}).get("instrument"),
        "best_subtype":    (instrument_ranking[0] or {}).get("subtype"),
        # AI enrichment — frontend can use these to boost / demote display
        "ai_p_win":       ai_p_win,
        "ai_trustworthy": ai_trustworthy,
        "ai_concur":      ai_concur,
    }


def _scan_one(horizon: str, min_stars: int, top_n: int) -> Optional[dict]:
    """Run the scan for a single (horizon, min_stars) combo.

    Universe + prefilter behaviour driven by env:
      • SCANNER_UNIVERSE  ∈ {fno_top50, fno, nifty500, all_nse}
      • SCANNER_PREFILTER ∈ {"1" forced on, "0" forced off, "" auto}
    See module-level docstrings for the tradeoffs.
    """
    try:
        from app.engines import recommender
        res = recommender.professional_scan(
            horizon=horizon, capital=100_000, min_stars=min_stars,
            top_n=top_n, quick=(SCANNER_UNIVERSE == "fno_top50"),
            universe_name=SCANNER_UNIVERSE,
            apply_prefilter=_resolve_prefilter_flag(),
        )
        return {
            "asof":     res.get("asof"),
            "horizon":  horizon,
            "top_buy":  [_strip_pick(p) for p in res.get("top_buy", [])],
            "top_sell": [_strip_pick(p) for p in res.get("top_sell", [])],
            "scanned_universe_size": res.get("universe_size"),
            "universe_name":         res.get("universe_name"),
            "prefilter":             res.get("prefilter"),
        }
    except Exception as e:
        logger.exception("Scanner failed for ({}, {}): {}", horizon, min_stars, e)
        return None


def _publish_new_signals(prev_payload: dict | None, new_payload: dict, horizon: str):
    """Diff the new snapshot against the previous one. For each symbol that
    appears in the new top_buy / top_sell but wasn't in the previous, push
    the signal to Telegram (channels gated by star rating) and Twitter
    (public credibility track-record).

    Telegram + Twitter errors are swallowed inside their `publish_*`
    functions — this function never raises.
    """
    try:
        from app.services import telegram_bot, twitter_bot
        telegram_on = telegram_bot.is_configured()
        twitter_on  = twitter_bot.is_configured()
        if not (telegram_on or twitter_on):
            return

        prev_symbols = set()
        if prev_payload:
            for p in (prev_payload.get("top_buy") or []) + (prev_payload.get("top_sell") or []):
                prev_symbols.add(p.get("symbol"))

        for direction_key, direction in (("top_buy", "BULLISH"), ("top_sell", "BEARISH")):
            for p in (new_payload.get(direction_key) or []):
                if p.get("symbol") in prev_symbols:
                    continue    # already published in previous run
                # Floor star check — we don't post 1-2★ to any channel
                if (p.get("stars") or 0) < 3:
                    continue

                common_kwargs = dict(
                    symbol=p["symbol"], direction=direction,
                    stars=p.get("stars") or 0,
                    confidence=p.get("confidence") or 0,
                    entry=p.get("entry") or 0,
                    stoploss=p.get("stoploss") or 0,
                    targets=p.get("targets") or [],
                    horizon=horizon,
                )
                if telegram_on:
                    telegram_bot.publish_signal(**common_kwargs, sector=p.get("sector"))
                if twitter_on:
                    twitter_bot.post_signal(**common_kwargs)
    except Exception as e:
        logger.warning("Signal publish step failed (signals still saved): {}", e)


def _upsert_snapshot(db: Session, horizon: str, min_stars: int,
                      payload: dict, duration_ms: int, symbols_scanned: int):
    existing = (db.query(LivePicksSnapshot)
                  .filter_by(horizon=horizon, min_stars=min_stars)
                  .one_or_none())
    prev_payload = dict(existing.payload) if existing and existing.payload else None
    if existing:
        existing.payload = payload
        existing.scanned_at = datetime.utcnow()
        existing.scan_duration_ms = duration_ms
        existing.symbols_scanned = symbols_scanned
    else:
        db.add(LivePicksSnapshot(
            horizon=horizon, min_stars=min_stars,
            payload=payload,
            scan_duration_ms=duration_ms,
            symbols_scanned=symbols_scanned,
        ))
    db.commit()
    # AFTER the commit — push any newly-appeared signals to Telegram.
    # We only publish for the canonical (horizon, min_stars=3) combo to
    # avoid posting the same signal 3 times across min_stars variants.
    if min_stars == 3:
        _publish_new_signals(prev_payload, payload, horizon)


def run_once() -> dict:
    """Single scanner pass — runs all PRECOMPUTED_PARAMS combos in parallel.

    Concurrency: bounded by SCAN_MAX_WORKERS to avoid hammering Angel One.
    Each combo runs independently; one combo's failure doesn't affect others.
    DB upserts happen serially after all scans complete (avoids SQLite
    write-contention on the shared snapshots table).

    Returns a summary dict so callers (or admin trigger) can see what ran.
    Never raises — failures on a single combo are logged but don't abort
    other combos.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    started = datetime.utcnow()
    results = []
    scan_outputs: dict[tuple[str, int, int], tuple[dict | None, int]] = {}

    # ----- Parallel scan phase -----
    # 4 workers is the sweet spot: enough to overlap I/O wait on Angel One,
    # not so many that we trigger their rate limiter (~10 calls/sec).
    SCAN_MAX_WORKERS = 4
    with ThreadPoolExecutor(max_workers=SCAN_MAX_WORKERS,
                              thread_name_prefix="picks-scan") as pool:
        futures = {
            pool.submit(_scan_one_with_timing, horizon, min_stars, top_n):
                (horizon, min_stars, top_n)
            for horizon, min_stars, top_n in PRECOMPUTED_PARAMS
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                payload, duration_ms = fut.result()
                scan_outputs[key] = (payload, duration_ms)
            except Exception as e:
                logger.exception("Scanner combo {} crashed: {}", key, e)
                scan_outputs[key] = (None, 0)

    # ----- Serial upsert phase (avoid SQLite write contention) -----
    # Telegram publishing happens inside _upsert_snapshot for min_stars=3.
    with SessionLocal() as db:
        for horizon, min_stars, top_n in PRECOMPUTED_PARAMS:
            payload, duration_ms = scan_outputs.get((horizon, min_stars, top_n), (None, 0))
            if payload is None:
                results.append({"horizon": horizon, "min_stars": min_stars,
                                  "ok": False, "duration_ms": duration_ms})
                continue
            n_scanned = payload.get("scanned_universe_size") or (
                len(payload.get("top_buy", [])) + len(payload.get("top_sell", []))
            )
            _upsert_snapshot(db, horizon, min_stars, payload, duration_ms, n_scanned)
            results.append({"horizon": horizon, "min_stars": min_stars,
                              "ok": True, "duration_ms": duration_ms,
                              "n_picks": len(payload.get("top_buy", [])) + len(payload.get("top_sell", []))})

    finished = datetime.utcnow()
    summary = {
        "started_at":   started.isoformat(),
        "finished_at":  finished.isoformat(),
        "elapsed_sec":  round((finished - started).total_seconds(), 2),
        "combinations": results,
        "parallelism":  SCAN_MAX_WORKERS,
    }
    logger.info("Scanner pass complete: {} combinations in {}s (parallel × {})",
                  len(results), summary["elapsed_sec"], SCAN_MAX_WORKERS)
    return summary


def _scan_one_with_timing(horizon: str, min_stars: int, top_n: int
                           ) -> tuple[dict | None, int]:
    """Wrapper that also returns the scan duration in milliseconds."""
    t0 = time.time()
    payload = _scan_one(horizon, min_stars, top_n)
    duration_ms = int((time.time() - t0) * 1000)
    return payload, duration_ms


def latest_snapshot(horizon: str, min_stars: int,
                     freshness_seconds: int = FRESHNESS_THRESHOLD_SECONDS
                     ) -> tuple[Optional[dict], bool]:
    """Read the most recent snapshot for this param combo.

    Returns (payload, is_stale). When no row exists at all → (None, False).
    When row exists but older than freshness_seconds → (payload, True).
    """
    with SessionLocal() as db:
        row = (db.query(LivePicksSnapshot)
                 .filter_by(horizon=horizon, min_stars=min_stars)
                 .one_or_none())
        if row is None:
            return None, False
        age = datetime.utcnow() - row.scanned_at
        is_stale = age > timedelta(seconds=freshness_seconds)
        payload = dict(row.payload)
        payload["_scanned_at"] = row.scanned_at.isoformat()
        payload["_is_stale"] = is_stale
        return payload, is_stale


# ---------------------------------------------------------------------------
# Scheduler bootstrap — called from app.main on startup
# ---------------------------------------------------------------------------

_scheduler = None


def start_scheduler() -> None:
    """Start the background scanner on app startup. Idempotent — safe to
    call multiple times; subsequent calls are no-ops.

    Uses APScheduler's BackgroundScheduler so it lives in the same process
    as the API (no separate worker needed for now). When you scale out,
    move this to a dedicated worker container.
    """
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("apscheduler not installed — scanner will not run automatically. "
                         "pip install apscheduler to enable. "
                         "API will fall back to inline scan on every request.")
        return

    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(run_once, "interval", minutes=SCAN_INTERVAL_MINUTES,
                   id="picks_scanner", max_instances=1,
                   coalesce=True, misfire_grace_time=60)
    sched.start()
    _scheduler = sched
    logger.info("Picks scanner scheduler started — interval {}min",
                  SCAN_INTERVAL_MINUTES)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
