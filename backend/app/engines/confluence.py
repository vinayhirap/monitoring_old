"""Confluence + holding-period estimators.

confluence_boost():
    Counts how many engines (Technical / SMC / Options / Astrology / Gann /
    Numerology / Fibonacci) lean the same direction. The more that agree,
    the higher the confidence boost we apply on top of the weighted average.

    Engineering intuition: a 70% confidence based on ONE strong engine is
    fragile; a 70% confidence based on SIX agreeing engines is concrete.
    Apply a non-linear boost so 5/6 alignment ≫ 3/6 alignment.

holding_period_estimate():
    Given entry, targets, ATR, horizon, and upcoming Gann/astro reversal
    windows, predicts:
       • optimal_entry_window  — best time to actually click BUY
       • estimated_days_to_t1  — based on ATR realization rate
       • exit_by_date          — hard timeout (capital better deployed elsewhere)
       • partial_book_dates    — anchor dates for booking 30/50/70% of qty
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal


# ============================================================================
# Confluence boost
# ============================================================================

@dataclass
class ConfluenceResult:
    intended_direction: str
    aligned_engines: list[str]
    contrarian_engines: list[str]
    neutral_engines: list[str]
    aligned_count: int
    total_count: int
    alignment_pct: float
    boost: float                     # additive delta to apply to confidence
    new_confidence: float            # original_confidence + boost (clamped 0..100)
    grade: str                       # WEAK / MODERATE / STRONG / VERY_STRONG / UNANIMOUS
    summary: str
    # ---- Weighted-voting fields (added in #4) ----
    # When per-engine weights are supplied (from engine_weights service), the
    # boost is computed from the WEIGHTED sum of aligned-engine weights rather
    # than the raw count. weights_used is the dict actually applied; status
    # records whether the weights came from data, are equal, or a mix.
    weighted_alignment:  float = 0.0    # sum_of_aligned_weights / sum_of_all_weights, 0..1
    weights_used:        dict = field(default_factory=dict)
    weight_status:       str  = "EQUAL_WEIGHT"  # DATA_DRIVEN / EQUAL_WEIGHT / MIXED / ERROR
    weighted_aligned_sum: float = 0.0           # sum of weights of aligned engines
    total_weight_sum:    float = 0.0            # sum of weights across all voting engines

    def to_dict(self) -> dict:
        return self.__dict__


def confluence_boost(
    engines: dict,                   # {technical: {bias,...}, smc: {...}, ...}
    intended_direction: str,         # BULLISH / BEARISH / NEUTRAL
    original_confidence: float,
    weights: dict[str, float] | None = None,    # NEW: {engine_name: weight}; missing engines default to 1.0
    weight_status: str = "EQUAL_WEIGHT",         # NEW: surfaced in result for UI debugging
) -> ConfluenceResult:
    """Apply non-linear confidence boost based on how many engines agree.

    Now WEIGHTED: when `weights` is provided (from engine_weights service),
    aligned engines are summed by their voting weight, not raw count. An
    engine with proven +8pp edge in the journal counts more than one with
    no track record. Missing engines default to weight=1.0, so the behaviour
    degrades gracefully when no attribution data exists yet.

    Boost table (still anchored on a 6-engine reference; scales by weighted
    alignment pct so 4/6 equal-weight ≈ 4 weighted out of 6 total weight):
       <33%  → -5   (only minority agreement)
       33-49%→  0
       50-66%→ +6
       67-83%→ +12
       ≥83%  → +18  (near-unanimous)
    """
    aligned, contrarian, neutral = [], [], []
    for name, e in (engines or {}).items():
        bias = (e or {}).get("bias", "NEUTRAL").upper()
        if bias == intended_direction:
            aligned.append(name)
        elif bias in ("BULLISH", "BEARISH"):
            contrarian.append(name)
        else:
            neutral.append(name)

    total = len(aligned) + len(contrarian) + len(neutral)
    if total == 0:
        return ConfluenceResult(
            intended_direction=intended_direction,
            aligned_engines=[], contrarian_engines=[], neutral_engines=[],
            aligned_count=0, total_count=0, alignment_pct=0.0,
            boost=0.0, new_confidence=original_confidence,
            grade="WEAK", summary="No engine inputs to evaluate.",
        )

    aligned_count = len(aligned)
    alignment_pct = aligned_count / total * 100

    # ---- Weighted alignment ----
    # Look up each engine's weight; default to 1.0 when not in the dict.
    # Sum weights for aligned + contrarian + neutral engines separately so the
    # ratio is honest (neutral engines DON'T support either side but still
    # count toward the denominator).
    w = weights or {}
    weighted_aligned_sum = sum(w.get(name, 1.0) for name in aligned)
    weighted_contrarian  = sum(w.get(name, 1.0) for name in contrarian)
    weighted_neutral     = sum(w.get(name, 1.0) for name in neutral)
    total_weight_sum     = weighted_aligned_sum + weighted_contrarian + weighted_neutral
    weighted_alignment   = (weighted_aligned_sum / total_weight_sum) if total_weight_sum else 0.0

    # ---- Non-linear boost — driven by weighted_alignment when weights are supplied,
    #      else by raw count (back-compat path) ----
    if weights:
        # Percentage of total voting weight that aligned with the direction
        wpct = weighted_alignment * 100
        if wpct < 33:
            boost = -5.0; grade = "WEAK"
        elif wpct < 50:
            boost = 0.0;  grade = "MODERATE"
        elif wpct < 67:
            boost = 6.0;  grade = "STRONG"
        elif wpct < 83:
            boost = 12.0; grade = "VERY_STRONG"
        else:
            boost = 18.0; grade = "UNANIMOUS"
    else:
        # Legacy count-based path — keeps existing behaviour for any caller
        # that hasn't switched to passing weights yet.
        if aligned_count <= 2:
            boost = -5.0; grade = "WEAK"
        elif aligned_count == 3:
            boost = 0.0;  grade = "MODERATE"
        elif aligned_count == 4:
            boost = 6.0;  grade = "STRONG"
        elif aligned_count == 5:
            boost = 12.0; grade = "VERY_STRONG"
        else:
            boost = 18.0; grade = "UNANIMOUS"

    # Extra penalty if a key engine actively disagrees — only apply if no
    # weights given (otherwise the weight itself already de-rates it).
    if not weights and ("astrology" in contrarian or "technical" in contrarian):
        boost -= 5.0
    # With weights: penalise extra ONLY when the contrarian engine has weight
    # > 1.0 (i.e. it's a proven alpha contributor that's now dissenting — that
    # actually matters). A noise-engine dissenting is already factored in.
    elif weights:
        strong_contrarians = [n for n in contrarian if w.get(n, 1.0) > 1.0]
        if strong_contrarians:
            boost -= 3.0

    new_conf = max(0.0, min(100.0, original_confidence + boost))

    summary = (
        f"{aligned_count}/{total} engines agree ({alignment_pct:.0f}%) "
        + (f"[weighted {weighted_alignment*100:.0f}%] " if weights else "")
        + f"— {grade}. "
        + f"Aligned: {', '.join(aligned) or 'none'}. "
        + (f"Contrarian: {', '.join(contrarian)}. " if contrarian else "")
        + f"Confidence {original_confidence:.1f} → {new_conf:.1f} ({boost:+.1f})."
    )

    return ConfluenceResult(
        intended_direction=intended_direction,
        aligned_engines=aligned,
        contrarian_engines=contrarian,
        neutral_engines=neutral,
        aligned_count=aligned_count,
        total_count=total,
        alignment_pct=round(alignment_pct, 2),
        boost=round(boost, 2),
        new_confidence=round(new_conf, 2),
        grade=grade,
        summary=summary,
        weighted_alignment=round(weighted_alignment, 4),
        weights_used={name: w.get(name, 1.0) for name in (aligned + contrarian + neutral)} if weights else {},
        weight_status=weight_status if weights else "EQUAL_WEIGHT",
        weighted_aligned_sum=round(weighted_aligned_sum, 3),
        total_weight_sum=round(total_weight_sum, 3),
    )


# ============================================================================
# Holding period estimator
# ============================================================================

# Realization rates: % of daily ATR a trend typically extends per holding day.
# Calibrated against typical NSE F&O daily candle behaviour.
_REALIZATION_RATE = {
    "INTRADAY":   1.20,    # intraday moves 1.2× ATR in best case (within hours)
    "SWING":      0.55,    # swings burn ~55% of ATR per day in trend
    "POSITIONAL": 0.35,
}

# Hard caps on holding period — capital better deployed if no movement
_MAX_HOLD_DAYS = {"INTRADAY": 1, "SWING": 15, "POSITIONAL": 45}


@dataclass
class HoldingPlan:
    horizon: str
    entry_price: float
    targets: list[float]
    atr: float

    optimal_entry_window: dict           # {when, hora_change, notes}
    estimated_days_to_t1: float
    estimated_days_to_t_final: float
    exit_by_date: str                    # ISO date — hard timeout
    partial_book_schedule: list[dict]    # [{at_target_n, book_pct, est_date}, ...]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def holding_period_estimate(
    entry_price: float,
    targets: list[float],
    atr: float,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    hora: dict | None = None,
    upcoming_gann_cycles: list[dict] | None = None,
    asof: date | None = None,
) -> HoldingPlan:
    asof = asof or date.today()
    rate = _REALIZATION_RATE.get(horizon, 0.55)
    daily_move = max(atr * rate, 1e-6)
    max_hold = _MAX_HOLD_DAYS.get(horizon, 15)

    # Days to each target
    days_to = []
    for t in targets:
        dist = abs(t - entry_price)
        days = max(1.0, round(dist / daily_move, 1))
        days_to.append(min(days, max_hold))
    if not days_to:
        days_to = [1.0]

    # ----- Optimal entry window -----
    entry_window = _optimal_entry(hora, horizon)

    # ----- Partial-book schedule -----
    # Conservative booking: 30% at T1, 40% at T2, 30% at T3 (or as targets allow)
    book_pcts = [30, 40, 30][:len(days_to)]
    schedule = []
    for i, (d, pct) in enumerate(zip(days_to, book_pcts)):
        target_date = asof + timedelta(days=int(d))
        schedule.append({
            "at_target": f"T{i+1}",
            "book_pct": pct,
            "est_date": target_date.isoformat(),
            "est_days": d,
        })

    # ----- Exit-by date (latest plausible holding deadline) -----
    exit_by = asof + timedelta(days=int(min(days_to[-1] * 1.5, max_hold)))

    notes = []
    if horizon == "INTRADAY":
        notes.append("Intraday — square off before 15:15 IST regardless of target hit.")
    if hora and hora.get("bias") == "bearish" and any(
        s["book_pct"] >= 30 for s in schedule
    ):
        notes.append(f"Current hora is {hora.get('ruler')} (bearish) — consider waiting "
                     f"{hora.get('next_change_in_minutes', 0)}m for next ({hora.get('next_ruler')}) hora.")

    # If a major Gann cycle hits before T1, flag it as a potential reversal risk
    if upcoming_gann_cycles:
        for c in upcoming_gann_cycles[:3]:
            try:
                proj = date.fromisoformat(c["projected_date"])
                days_until = (proj - asof).days
                if 0 < days_until < days_to[0]:
                    notes.append(
                        f"⚠ Gann {c['cycle_days']}d cycle hits on {proj.isoformat()} "
                        f"(before T1) — tighten stops as the date approaches."
                    )
            except Exception:
                pass

    return HoldingPlan(
        horizon=horizon,
        entry_price=round(entry_price, 2),
        targets=targets,
        atr=round(atr, 4),
        optimal_entry_window=entry_window,
        estimated_days_to_t1=days_to[0],
        estimated_days_to_t_final=days_to[-1],
        exit_by_date=exit_by.isoformat(),
        partial_book_schedule=schedule,
        notes=notes,
    )


def _optimal_entry(hora: dict | None, horizon: str) -> dict:
    """Decide whether to enter now or wait for a better hora."""
    if not hora:
        return {"when": "ANY", "wait_minutes": 0,
                "notes": "Hora data unavailable — enter now if technicals support."}

    bias = (hora.get("bias") or "neutral").lower()
    weight = hora.get("weight", 0.5)
    ruler = hora.get("ruler", "Unknown")
    next_ruler = hora.get("next_ruler", "Unknown")
    wait = hora.get("next_change_in_minutes", 0)

    # For intraday: wait only if hora is strongly bearish AND market still open >wait minutes
    if horizon == "INTRADAY":
        if bias == "bearish" and weight >= 0.7 and wait < 90:
            return {
                "when": "WAIT_FOR_NEXT_HORA",
                "wait_minutes": wait,
                "next_ruler": next_ruler,
                "notes": f"Hold off ~{wait}m — current {ruler} hora is bearish for entries. "
                         f"Next hora ({next_ruler}) starts then.",
            }
        return {"when": "NOW", "wait_minutes": 0,
                "notes": f"Current {ruler} hora bias is {bias} — acceptable for {horizon} entry."}

    # Swing/positional: hora matters less day-to-day; enter now unless extremely malefic
    if bias == "bearish" and weight >= 0.85:
        return {
            "when": "WAIT_FOR_NEXT_HORA",
            "wait_minutes": wait,
            "next_ruler": next_ruler,
            "notes": f"Strong malefic {ruler} hora — consider waiting {wait}m for {next_ruler}.",
        }
    return {"when": "NOW", "wait_minutes": 0,
            "notes": f"{ruler} hora ({bias}) — fine for {horizon} swing/positional entry."}
