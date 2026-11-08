"""Engine weights — convert attribution edge into per-engine voting weights.

Read by the confluence engine so the "how many engines agree" calculation
becomes a *weighted* sum, not a flat count. An engine with proven +8pp
edge counts more than one with proven -3pp edge.

Critical design rule: HONEST DEGRADATION.
  • If an engine has < MIN_DECIDED_VOTES evaluated signals → weight = 1.0
    (no data → equal weight, never invented).
  • If the attribution service fails or returns no engines → all weights
    fall back to 1.0 (the legacy count-based behaviour is preserved).
  • Weights are clamped to [0.1, 2.0] so no single engine can dominate
    even if it shows a freakishly high edge on small data.

The mapping from edge_pp → weight is intentionally gentle:
    weight = clamp(1 + edge_pp * 0.05, 0.1, 2.0)

  edge_pp =  0  → weight = 1.0  (no edge → no advantage)
  edge_pp = +5  → weight = 1.25 (alpha contributor: modest upweight)
  edge_pp = +10 → weight = 1.50
  edge_pp = +20 → weight = 2.00 (cap)
  edge_pp = -5  → weight = 0.75
  edge_pp = -10 → weight = 0.50
  edge_pp = -20 → weight = 0.10 (cap — strong downweight but not zero)

A 1-hour in-memory cache prevents hitting the DB for every signal — the
attribution data changes once per outcome-tracker run (daily-ish), so
1-hour TTL is plenty.
"""
from __future__ import annotations

import threading
import time
from typing import Literal

from loguru import logger


# ---- Tuning constants ----
_MIN_DECIDED_VOTES = 15        # below this, the engine gets weight=1.0
_WEIGHT_FLOOR      = 0.1       # never zero — preserve some signal
_WEIGHT_CEILING    = 2.0       # cap so no engine dominates
_EDGE_SLOPE        = 0.05      # weight = 1 + edge_pp * 0.05
_CACHE_TTL_SECONDS = 3600      # 1 hour


# ---- In-memory cache ----
_cache_lock = threading.Lock()
_cache: dict = {"weights": None, "meta": None, "ts": 0.0}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_weights(*, lookback_days: int = 90,
                 force_refresh: bool = False) -> dict[str, float]:
    """Return {engine_name: weight} for use by the confluence engine.

    Engines without sufficient attribution data are NOT in the returned dict
    — callers should fall back to weight=1.0 for any engine not listed.
    Use `get_weights_with_meta()` when you need to know which engines were
    learned vs which fell back to equal weighting.
    """
    return get_weights_with_meta(lookback_days=lookback_days,
                                  force_refresh=force_refresh)["weights"]


def get_weights_with_meta(*, lookback_days: int = 90,
                           force_refresh: bool = False) -> dict:
    """Return {weights, meta} where meta tells you whether weights are
    data-driven, equal, or mixed.

    Cached for 1 hour — set `force_refresh=True` to bypass.

    Never raises. On any error returns weights={} + meta.status="ERROR"
    so the caller can fall back to equal weighting cleanly.
    """
    with _cache_lock:
        now = time.time()
        if (not force_refresh
                and _cache["weights"] is not None
                and (now - _cache["ts"]) < _CACHE_TTL_SECONDS):
            return {"weights": _cache["weights"], "meta": _cache["meta"]}

    try:
        result = _compute_weights(lookback_days=lookback_days)
        with _cache_lock:
            _cache["weights"] = result["weights"]
            _cache["meta"]    = result["meta"]
            _cache["ts"]      = time.time()
        return result
    except Exception as e:
        logger.warning("engine_weights: failed to compute, falling back to equal: {}", e)
        return {"weights": {}, "meta": {
            "status": "ERROR", "reason": str(e),
            "data_driven_engines": [], "equal_weight_engines": [],
            "lookback_days": lookback_days,
        }}


def edge_to_weight(edge_pp: float) -> float:
    """Public so callers can do "what if" — convert an edge in percentage
    points to the voting weight that would be applied."""
    raw = 1.0 + edge_pp * _EDGE_SLOPE
    return max(_WEIGHT_FLOOR, min(_WEIGHT_CEILING, raw))


def clear_cache() -> None:
    """Manual cache invalidation — used by tests + admin refresh."""
    with _cache_lock:
        _cache["weights"] = None
        _cache["meta"]    = None
        _cache["ts"]      = 0.0


# ---------------------------------------------------------------------------
# Internal — compute fresh weights from the attribution service
# ---------------------------------------------------------------------------

def _compute_weights(*, lookback_days: int) -> dict:
    """Read engine_attribution output and convert each engine's edge to a
    voting weight. Engines with insufficient data are omitted (caller
    falls back to 1.0 for them).
    """
    from app.database import SessionLocal
    from app.services import engine_attribution

    weights: dict[str, float] = {}
    data_driven: list[str] = []
    equal_weight: list[str] = []
    skipped: list[dict] = []

    with SessionLocal() as db:
        attrib = engine_attribution.attribute_engines(
            db, days=lookback_days, min_samples=_MIN_DECIDED_VOTES,
        )

    for eng in attrib.get("engines", []):
        name = eng["engine"]
        if eng["status"] == "INSUFFICIENT_DATA":
            equal_weight.append(name)
            skipped.append({"engine": name, "reason": "insufficient_data",
                             "decided_size": eng.get("decided_size", 0)})
            continue
        edge_pp = eng.get("edge_pp")
        if edge_pp is None:
            equal_weight.append(name)
            skipped.append({"engine": name, "reason": "no_edge_computed"})
            continue
        w = edge_to_weight(edge_pp)
        weights[name] = round(w, 3)
        data_driven.append(name)

    if not weights:
        status: Literal["DATA_DRIVEN", "EQUAL_WEIGHT", "MIXED"] = "EQUAL_WEIGHT"
        reason = "No engines have ≥{} decided votes yet — using equal weighting".format(
            _MIN_DECIDED_VOTES)
    elif skipped:
        status = "MIXED"
        reason = f"{len(weights)} engines weighted from data, {len(skipped)} still equal-weighted"
    else:
        status = "DATA_DRIVEN"
        reason = f"All {len(weights)} engines weighted from journal attribution"

    return {
        "weights": weights,
        "meta": {
            "status":               status,
            "reason":               reason,
            "lookback_days":        lookback_days,
            "min_decided_votes":    _MIN_DECIDED_VOTES,
            "baseline_hit_rate":    attrib.get("baseline_hit_rate"),
            "evaluated_signals":    attrib.get("evaluated_signals"),
            "data_driven_engines":  data_driven,
            "equal_weight_engines": equal_weight,
            "skipped":              skipped,
            "computed_at":          time.time(),
        },
    }
