"""Historical-analog engine — find past signals that look like the current one.

This is the most useful kind of "AI" for trading: rather than predicting from
features in the abstract, we find ACTUAL historical signals with similar
engine fingerprints and report their REALIZED outcomes.

Why this matters:
  • The user sees "this setup looks like 14 past signals; 9 hit T1, average
    MFE +3.2%, max drawdown -1.4%" — a far more meaningful number than a raw
    confidence percentage from a black-box composite.
  • It's empirical. The claim is verifiable against `signals_journal`.
  • It generalizes: when a new engine is added, it joins the feature vector
    automatically — no retraining.

How it works:
  1. Build a numeric fingerprint vector for the current signal from its
     engine scores + biases + market regime.
  2. Pull the last N (default 500) EVALUATED journal entries.
  3. Compute cosine similarity between current and each historical.
  4. Take the top K (default 20) by similarity above a floor (default 0.85).
  5. Aggregate their outcomes — hit rate, average MFE/MAE, max-drawdown band.

No external API. No model file. No GPU. Pure numpy + cosine math.
This is "AI" in the pragmatic sense: data-driven inference, fully local.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
from loguru import logger

from app.models.signals_journal import SignalJournalEntry


# ----------------------------------------------------------------------------
# Feature vector schema
# ----------------------------------------------------------------------------
#
# Order matters here — every signal (current + historical) must produce a
# vector in exactly this order. New features can be appended at the end without
# invalidating prior journal entries (cosine similarity is order-sensitive
# only across vectors of the same length).

FEATURE_KEYS = [
    # Engine scores (0-100 normalized to 0-1)
    "score_technical", "score_smc", "score_gann", "score_fibonacci",
    "score_vedic", "score_numerology",
    "score_advanced_ta",       # composite from VWAP+divergence+MTF
    # Engine biases — encoded as {-1, 0, +1}
    "bias_technical", "bias_smc", "bias_gann", "bias_fibonacci",
    "bias_vedic", "bias_advanced_ta",
    # Confidence + composite direction
    "confidence_norm",         # 0-1
    "direction_sign",          # +1 BULLISH, -1 BEARISH, 0 NEUTRAL
    # Regime context
    "regime_trending",         # 1 if regime in (TRENDING, VOLATILE) else 0
    "regime_meanrev",          # 1 if regime in (MEAN_REVERTING, RANGING) else 0
]


def _bias_to_num(bias: str | None) -> float:
    if bias == "BULLISH": return 1.0
    if bias == "BEARISH": return -1.0
    return 0.0


def _direction_sign(d: str | None) -> float:
    if d == "BULLISH": return 1.0
    if d == "BEARISH": return -1.0
    return 0.0


def build_feature_vector(*, engines_snapshot: dict, confidence: float,
                          direction: str, regime: str | None = None
                          ) -> np.ndarray:
    """Build a fingerprint vector from a signal's engine outputs.

    `engines_snapshot` should be the dict already journaled for past signals
    OR the live dict from /api/symbol for a current signal. The function
    handles missing fields by defaulting them to 0.5 (neutral score) or 0 (bias),
    so partial snapshots don't break similarity math.
    """
    # Defensive accessor — engines may not all be present
    def _score(name: str) -> float:
        v = engines_snapshot.get(name, {}).get("score") if isinstance(engines_snapshot.get(name), dict) else None
        return float(v) / 100.0 if v is not None else 0.5

    def _bias(name: str) -> float:
        v = engines_snapshot.get(name, {}).get("bias") if isinstance(engines_snapshot.get(name), dict) else None
        return _bias_to_num(v) if v else 0.0

    # Advanced TA composite score lives under a different path
    ata_block = engines_snapshot.get("advanced_ta", {})
    if isinstance(ata_block, dict):
        ata_score = float(ata_block.get("composite_score", 50)) / 100.0
        ata_bias = _bias_to_num(ata_block.get("composite_bias"))
    else:
        ata_score = 0.5
        ata_bias = 0.0

    regime = (regime or "").upper()
    return np.array([
        _score("technical"), _score("smc"), _score("gann"), _score("fibonacci"),
        _score("vedic"), _score("numerology"),
        ata_score,
        _bias("technical"), _bias("smc"), _bias("gann"), _bias("fibonacci"),
        _bias("vedic"), ata_bias,
        max(0.0, min(1.0, float(confidence) / 100.0)),
        _direction_sign(direction),
        1.0 if regime in ("TRENDING", "VOLATILE") else 0.0,
        1.0 if regime in ("MEAN_REVERTING", "RANGING") else 0.0,
    ], dtype=np.float32)


# ----------------------------------------------------------------------------
# Cosine similarity (numpy-only — no sklearn dep)
# ----------------------------------------------------------------------------

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]. Returns 0 if either vector is zero."""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ----------------------------------------------------------------------------
# Outcome aggregation
# ----------------------------------------------------------------------------

def _outcome_summary(rows: list[SignalJournalEntry]) -> dict:
    """Summarize outcomes across a set of historical analogs."""
    if not rows:
        return {"n": 0}

    def _won(r: SignalJournalEntry) -> int:
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

    n = len(rows)
    wins = sum(_won(r) for r in rows)
    target_hits_t1 = sum(1 for r in rows if (r.outcome_target_hit or 0) >= 1)
    target_hits_t2 = sum(1 for r in rows if (r.outcome_target_hit or 0) >= 2)
    target_hits_t3 = sum(1 for r in rows if (r.outcome_target_hit or 0) >= 3)
    sl_hits        = sum(1 for r in rows if r.outcome_stoploss_hit)

    mfes = [r.outcome_max_favorable for r in rows if r.outcome_max_favorable is not None]
    maes = [r.outcome_max_adverse   for r in rows if r.outcome_max_adverse   is not None]

    return {
        "n":           n,
        "wins":        wins,
        "win_rate":    round(wins / n, 4),
        "t1_hit_rate": round(target_hits_t1 / n, 4),
        "t2_hit_rate": round(target_hits_t2 / n, 4),
        "t3_hit_rate": round(target_hits_t3 / n, 4),
        "sl_hit_rate": round(sl_hits / n, 4),
        "avg_mfe":     round(float(np.mean(mfes)), 3) if mfes else None,
        "avg_mae":     round(float(np.mean(maes)), 3) if maes else None,
        "max_mae":     round(float(np.min(maes)), 3) if maes else None,
    }


# ----------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------

@dataclass
class AnalogReport:
    n_analogs: int                       # how many historical analogs found above floor
    similarity_floor: float              # the cosine threshold applied
    avg_similarity: float                # average cos-sim of selected analogs
    outcomes: dict                       # aggregated outcomes (see _outcome_summary)
    top_analogs: list[dict] = field(default_factory=list)   # top-5 by similarity
    has_enough_data: bool = False        # True if n_analogs >= meaningful threshold
    interpretation: str = ""             # human-readable headline

    def to_dict(self) -> dict:
        return self.__dict__


def find_analogs(*, db, current_fingerprint: np.ndarray,
                   current_direction: str,
                   max_history: int = 500,
                   top_k: int = 20,
                   similarity_floor: float = 0.85
                   ) -> AnalogReport:
    """Find historical analogs of the current signal.

    Pulls the last `max_history` EVALUATED signals, computes cosine similarity
    against the current fingerprint, takes those above `similarity_floor`,
    aggregates their outcomes.

    `current_direction` is used as a hard filter — we only look at past
    signals with the same direction (BULLISH analogs for a current BULLISH
    signal). Mixing directions would conflate the outcome interpretation.

    Returns AnalogReport with outcomes + top-K most-similar analogs.
    """
    try:
        rows = (db.query(SignalJournalEntry)
                  .filter(SignalJournalEntry.outcome_status == "EVALUATED",
                           SignalJournalEntry.direction == current_direction,
                           SignalJournalEntry.engines_snapshot.isnot(None))
                  .order_by(SignalJournalEntry.emitted_at.desc())
                  .limit(max_history)
                  .all())
    except Exception as e:
        logger.warning("Historical analog query failed: {}", e)
        return AnalogReport(
            n_analogs=0, similarity_floor=similarity_floor,
            avg_similarity=0.0, outcomes={"n": 0},
            interpretation="Historical lookup unavailable",
        )

    if not rows:
        return AnalogReport(
            n_analogs=0, similarity_floor=similarity_floor,
            avg_similarity=0.0, outcomes={"n": 0},
            has_enough_data=False,
            interpretation="No evaluated historical signals yet — analog engine builds up over time",
        )

    # Compute similarity for each row
    scored: list[tuple[float, SignalJournalEntry]] = []
    for r in rows:
        try:
            past_fingerprint = build_feature_vector(
                engines_snapshot=r.engines_snapshot or {},
                confidence=r.confidence or 50,
                direction=r.direction,
                regime=None,    # legacy rows may not have regime field
            )
            sim = _cosine(current_fingerprint, past_fingerprint)
            if sim >= similarity_floor:
                scored.append((sim, r))
        except Exception as e:
            logger.debug("Fingerprint build failed for journal row {}: {}", r.id, e)
            continue

    if not scored:
        # No analogs above the floor — relax to top-K by raw similarity
        all_scored = []
        for r in rows:
            try:
                pf = build_feature_vector(engines_snapshot=r.engines_snapshot or {},
                                            confidence=r.confidence or 50,
                                            direction=r.direction)
                all_scored.append((_cosine(current_fingerprint, pf), r))
            except Exception:
                continue
        all_scored.sort(key=lambda t: t[0], reverse=True)
        scored = all_scored[:5] if all_scored else []
        used_relaxed = True
    else:
        scored.sort(key=lambda t: t[0], reverse=True)
        scored = scored[:top_k]
        used_relaxed = False

    if not scored:
        return AnalogReport(
            n_analogs=0, similarity_floor=similarity_floor,
            avg_similarity=0.0, outcomes={"n": 0},
            interpretation="No analogs above similarity floor",
        )

    rows_subset = [r for _, r in scored]
    outcomes = _outcome_summary(rows_subset)
    avg_sim = round(float(np.mean([s for s, _ in scored])), 3)

    top_5 = [{
        "similarity": round(s, 3),
        "symbol":     r.symbol,
        "emitted_at": r.emitted_at.isoformat() if r.emitted_at else None,
        "confidence": round(r.confidence, 1) if r.confidence else None,
        "outcome_target_hit": r.outcome_target_hit,
        "outcome_stoploss_hit": r.outcome_stoploss_hit,
        "outcome_5d_pnl_pct": r.outcome_5d_pnl_pct,
    } for s, r in scored[:5]]

    has_enough = outcomes.get("n", 0) >= 8
    if not has_enough:
        headline = f"Only {outcomes.get('n', 0)} similar past setups — not enough for a confident analog read"
    else:
        wr = outcomes.get("win_rate", 0)
        wr_pct = int(wr * 100)
        t1_pct = int(outcomes.get("t1_hit_rate", 0) * 100)
        headline = (f"{outcomes['n']} similar past setups · "
                      f"{wr_pct}% won · T1 hit {t1_pct}% of the time"
                      + (f" · avg MFE +{outcomes['avg_mfe']:.2f}%" if outcomes.get("avg_mfe") else ""))
        if used_relaxed:
            headline += " (relaxed similarity)"

    return AnalogReport(
        n_analogs=len(scored),
        similarity_floor=similarity_floor if not used_relaxed else round(avg_sim, 3),
        avg_similarity=avg_sim,
        outcomes=outcomes,
        top_analogs=top_5,
        has_enough_data=has_enough,
        interpretation=headline,
    )
