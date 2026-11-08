"""Per-engine attribution — measure each analysis engine's actual hit rate
against the journal of evaluated signals.

This is the load-bearing answer to "which of our 17 engines is contributing
alpha, and which is noise?" Without this data, every "tune the weights"
or "add XGBoost" suggestion is guesswork.

What we compute, per engine (technical, smc, gann, fibonacci, vedic,
numerology, ml, ...):
  • bullish_votes   — number of evaluated signals where this engine voted BULLISH
  • bearish_votes   — same for BEARISH
  • bullish_wins    — count where engine said BULLISH and trade won
  • bearish_wins    — count where engine said BEARISH and trade won
  • hit_rate_bull   — bullish_wins / bullish_votes
  • hit_rate_bear   — bearish_wins / bearish_votes
  • net_hit_rate    — (bullish_wins + bearish_wins) /
                       (bullish_votes + bearish_votes)
  • edge_pp         — net_hit_rate − overall_baseline_hit_rate
  • avg_pnl_when_bullish / avg_pnl_when_bearish (signed, percentage points)

A "trade won" if outcome_target_hit > 0 OR (no stoploss hit AND outcome_5d_pnl_pct
is in the trade's favored direction). Stoploss hit = loss. Pending = excluded.

Critical design rule: NEVER report KPIs when fewer than MIN_SAMPLES_PER_ENGINE
evaluated signals back that engine's vote. The honest-measurement guardrail
applies here too — a 70% win rate on 4 signals is statistical noise.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.signals_journal import SignalJournalEntry


# Each engine needs at least this many evaluated signals before we publish
# its hit rate. Below the threshold the engine is listed but marked
# "insufficient data" — never a misleading percentage.
MIN_SAMPLES_PER_ENGINE = 15


# Bias values we treat as BULLISH / BEARISH respectively. Different engines
# emit different bias strings (SMC uses BULLISH_STRUCTURE, ML uses BUY/SELL,
# etc.) — normalise them at read time.
_BULLISH_BIASES = {"BULLISH", "BULLISH_STRUCTURE", "BUY", "STRONG_BUY"}
_BEARISH_BIASES = {"BEARISH", "BEARISH_STRUCTURE", "SELL", "STRONG_SELL"}


def _normalize_bias(raw: str | None) -> Literal["BULLISH", "BEARISH", "NEUTRAL"]:
    if not raw:
        return "NEUTRAL"
    up = raw.upper()
    if up in _BULLISH_BIASES or up.startswith("BULLISH"):
        return "BULLISH"
    if up in _BEARISH_BIASES or up.startswith("BEARISH"):
        return "BEARISH"
    return "NEUTRAL"


def _outcome_classify(row: SignalJournalEntry) -> Literal["WIN", "LOSS", "FLAT", "PENDING"]:
    """Classify a journal row's outcome from the user's perspective:
      • WIN   — target was hit, OR 5d PnL is meaningfully in favor of direction
      • LOSS  — stop loss hit, OR 5d PnL is meaningfully against direction
      • FLAT  — outcome evaluated but neither side took it (small move)
      • PENDING — outcome not yet evaluated
    """
    if row.outcome_status != "EVALUATED":
        return "PENDING"
    if row.outcome_stoploss_hit:
        return "LOSS"
    if (row.outcome_target_hit or 0) > 0:
        return "WIN"
    pnl = row.outcome_5d_pnl_pct
    if pnl is None:
        return "PENDING"
    # Signed PnL: positive when direction was BULLISH and price went up.
    # The journal stores raw price-move %, so flip sign for BEARISH trades.
    direction_up = (row.direction or "").upper() in _BULLISH_BIASES
    signed_pnl = pnl if direction_up else -pnl
    if signed_pnl > 0.5:                  # > 50 bps in favor → WIN
        return "WIN"
    if signed_pnl < -0.5:                 # > 50 bps against  → LOSS
        return "LOSS"
    return "FLAT"


def attribute_engines(db: Session, *,
                       days: int = 90,
                       horizon: str | None = None,
                       min_samples: int = MIN_SAMPLES_PER_ENGINE) -> dict:
    """Compute per-engine attribution from the signals journal.

    Args:
      days        — lookback window
      horizon     — optionally restrict to one horizon (INTRADAY/SWING/POSITIONAL)
      min_samples — minimum evaluated signals before an engine's hit rate
                    is considered statistically meaningful

    Returns:
      {
        as_of:             iso timestamp,
        lookback_days:     int,
        horizon:           string or None,
        total_signals:     int,
        evaluated_signals: int,
        baseline_hit_rate: float (overall — used as comparison floor),
        engines: [
          {
            engine, bullish_votes, bearish_votes, bullish_wins, bearish_wins,
            hit_rate_bull, hit_rate_bear, net_hit_rate, edge_pp, sample_size,
            avg_pnl_when_bullish, avg_pnl_when_bearish,
            verdict, status   ("ALPHA" / "NEUTRAL" / "NOISE" / "INSUFFICIENT_DATA"),
          },
          ...
        ],
      }

    Never raises — bad rows are silently skipped so a single corrupt row
    can't break the whole attribution.
    """
    since = datetime.utcnow() - timedelta(days=days)
    q = db.query(SignalJournalEntry).filter(SignalJournalEntry.emitted_at >= since)
    if horizon:
        q = q.filter(SignalJournalEntry.horizon == horizon)
    rows = q.all()

    total_signals = len(rows)
    evaluated_rows = [r for r in rows if r.outcome_status == "EVALUATED"]
    evaluated_signals = len(evaluated_rows)

    # ----- Overall baseline hit rate (any signal, ignoring engine breakdown) -----
    overall_wins = 0
    overall_decided = 0
    for r in evaluated_rows:
        cls = _outcome_classify(r)
        if cls in ("WIN", "LOSS"):
            overall_decided += 1
            if cls == "WIN":
                overall_wins += 1
    baseline_hit_rate = (overall_wins / overall_decided) if overall_decided else 0.0

    # ----- Per-engine aggregates -----
    # Walk every evaluated row, then every engine that voted in that row's
    # snapshot. Bucket by engine name + bias side. Skip NEUTRAL votes —
    # we're measuring directional contribution.
    stats: dict[str, dict] = {}
    for r in evaluated_rows:
        cls = _outcome_classify(r)
        if cls == "PENDING":
            continue
        snap = r.engines_snapshot or {}
        if not isinstance(snap, dict):
            continue
        pnl_pct = r.outcome_5d_pnl_pct
        direction_up = (r.direction or "").upper() in _BULLISH_BIASES
        signed_pnl = (pnl_pct if direction_up else -pnl_pct) if pnl_pct is not None else None

        for engine_name, payload in snap.items():
            if not isinstance(payload, dict):
                continue
            bias = _normalize_bias(payload.get("bias"))
            if bias == "NEUTRAL":
                continue

            s = stats.setdefault(engine_name, {
                "engine": engine_name,
                "bullish_votes": 0, "bearish_votes": 0,
                "bullish_wins":  0, "bearish_wins":  0,
                "bullish_losses": 0, "bearish_losses": 0,
                "pnl_bull_sum":  0.0, "pnl_bull_n": 0,
                "pnl_bear_sum":  0.0, "pnl_bear_n": 0,
            })

            # Did this engine's vote match the trade direction?
            engine_agreed_with_trade = (
                (bias == "BULLISH" and direction_up) or
                (bias == "BEARISH" and not direction_up)
            )

            if bias == "BULLISH":
                s["bullish_votes"] += 1
                # When engine said BULLISH:
                #   WIN if trade direction was BULLISH and trade WON,
                #     OR trade direction was BEARISH and trade LOST (engine's bullish call was right).
                if (engine_agreed_with_trade and cls == "WIN") or \
                   (not engine_agreed_with_trade and cls == "LOSS"):
                    s["bullish_wins"] += 1
                elif (engine_agreed_with_trade and cls == "LOSS") or \
                     (not engine_agreed_with_trade and cls == "WIN"):
                    s["bullish_losses"] += 1
                if signed_pnl is not None and engine_agreed_with_trade:
                    s["pnl_bull_sum"] += signed_pnl
                    s["pnl_bull_n"]   += 1
                elif signed_pnl is not None:
                    s["pnl_bull_sum"] += -signed_pnl
                    s["pnl_bull_n"]   += 1
            else:                                   # BEARISH
                s["bearish_votes"] += 1
                if (engine_agreed_with_trade and cls == "WIN") or \
                   (not engine_agreed_with_trade and cls == "LOSS"):
                    s["bearish_wins"] += 1
                elif (engine_agreed_with_trade and cls == "LOSS") or \
                     (not engine_agreed_with_trade and cls == "WIN"):
                    s["bearish_losses"] += 1
                if signed_pnl is not None and engine_agreed_with_trade:
                    s["pnl_bear_sum"] += signed_pnl
                    s["pnl_bear_n"]   += 1
                elif signed_pnl is not None:
                    s["pnl_bear_sum"] += -signed_pnl
                    s["pnl_bear_n"]   += 1

    # ----- Compute hit rates + edge + verdict -----
    engines_out: list[dict] = []
    for name, s in stats.items():
        bull_decided = s["bullish_wins"] + s["bullish_losses"]
        bear_decided = s["bearish_wins"] + s["bearish_losses"]
        total_decided = bull_decided + bear_decided
        total_wins = s["bullish_wins"] + s["bearish_wins"]

        hit_bull = (s["bullish_wins"] / bull_decided) if bull_decided else None
        hit_bear = (s["bearish_wins"] / bear_decided) if bear_decided else None
        net_hit  = (total_wins / total_decided) if total_decided else None
        edge_pp  = ((net_hit - baseline_hit_rate) * 100) if net_hit is not None else None

        avg_pnl_bull = (s["pnl_bull_sum"] / s["pnl_bull_n"]) if s["pnl_bull_n"] else None
        avg_pnl_bear = (s["pnl_bear_sum"] / s["pnl_bear_n"]) if s["pnl_bear_n"] else None

        # Status classification:
        #   INSUFFICIENT_DATA — fewer than min_samples evaluated votes
        #   ALPHA             — net hit rate > baseline + 5pp
        #   NEUTRAL           — within ±5pp of baseline
        #   NOISE             — net hit rate < baseline − 5pp (engine is *anti-predictive*)
        sample_size = s["bullish_votes"] + s["bearish_votes"]
        if total_decided < min_samples:
            status = "INSUFFICIENT_DATA"
            verdict = f"Need {min_samples - total_decided} more evaluated votes to publish hit rate"
        elif edge_pp is None:
            status = "INSUFFICIENT_DATA"
            verdict = "No decided outcomes yet"
        elif edge_pp >= 5.0:
            status = "ALPHA"
            verdict = (f"Contributing alpha — {edge_pp:+.1f}pp above baseline. "
                        f"Keep + consider upweighting.")
        elif edge_pp >= -5.0:
            status = "NEUTRAL"
            verdict = (f"Within noise band ({edge_pp:+.1f}pp vs baseline). "
                        f"Marginal contribution.")
        else:
            status = "NOISE"
            verdict = (f"Anti-predictive — {edge_pp:+.1f}pp BELOW baseline. "
                        f"Consider downweighting or removing.")

        engines_out.append({
            "engine":               name,
            "bullish_votes":        s["bullish_votes"],
            "bearish_votes":        s["bearish_votes"],
            "bullish_wins":         s["bullish_wins"],
            "bearish_wins":         s["bearish_wins"],
            "bullish_losses":       s["bullish_losses"],
            "bearish_losses":       s["bearish_losses"],
            "sample_size":          sample_size,
            "decided_size":         total_decided,
            "hit_rate_bull":        round(hit_bull, 4) if hit_bull is not None else None,
            "hit_rate_bear":        round(hit_bear, 4) if hit_bear is not None else None,
            "net_hit_rate":         round(net_hit, 4) if net_hit is not None else None,
            "edge_pp":              round(edge_pp, 2) if edge_pp is not None else None,
            "avg_pnl_when_bullish": round(avg_pnl_bull, 3) if avg_pnl_bull is not None else None,
            "avg_pnl_when_bearish": round(avg_pnl_bear, 3) if avg_pnl_bear is not None else None,
            "status":               status,
            "verdict":              verdict,
        })

    # Sort: ALPHA engines first (by edge desc), then NEUTRAL, then NOISE, then INSUFFICIENT
    status_order = {"ALPHA": 0, "NEUTRAL": 1, "NOISE": 2, "INSUFFICIENT_DATA": 3}
    engines_out.sort(key=lambda e: (status_order.get(e["status"], 99),
                                     -(e.get("edge_pp") or -999)))

    return {
        "as_of":             datetime.utcnow().isoformat() + "Z",
        "lookback_days":     days,
        "horizon":           horizon,
        "total_signals":     total_signals,
        "evaluated_signals": evaluated_signals,
        "baseline_hit_rate": round(baseline_hit_rate, 4),
        "min_samples_threshold": min_samples,
        "engines":           engines_out,
    }
