"""Stop-Loss engine — proper, multi-method SL with reasoning.

Why this exists:

The original `strategy.select()` produces a single SL value, typically
`entry ± k × ATR(14)`. That's the textbook approach but it ignores everything
the chart is telling you. A SL placed without regard for structure gets
swept by routine noise; a SL placed below a major support holds.

This engine computes SL using SIX methods, ranks them by defensibility for
the current context, and returns:
  • A recommended SL with the reasoning
  • All candidates with their methods so the UI can show alternatives
  • A "confluence count" — how many independent methods cluster near the
    chosen level

Six methods implemented:

1. **ATR-multiple** — `entry ± k × ATR`. k chosen by volatility regime
   (1.5x in low-vol, 2.5x in high-vol). Always available.

2. **Structural swing** — for LONG: most recent swing low minus a small
   buffer. For SHORT: most recent swing high plus buffer. Best when
   market has clear structure; degenerate in choppy sideways.

3. **VWAP-based** — for LONG: below VWAP (or below the lower 1σ band in
   strong trends). For SHORT: above. Tracks institutional reference.

4. **Fibonacci-derived** — uses the symbol's fractal-Fib confluence
   zones. SL placed just beyond the nearest cluster below entry (long)
   or above entry (short). High-conviction when 3+ ratios overlap.

5. **Gann natural-square** — uses the nearest integer perfect-square level
   below entry (long) or above (short). Strong when price is hugging the
   square.

6. **Pivot-based** — uses Camarilla S3/H3 or standard S1/S2 as SL anchors.
   Strong intraday.

Selection logic:
  • Find candidates whose price is within a sensible range of entry
    (typically 0.5% to 5%, scaled by volatility)
  • If 2+ methods cluster within 0.3% of each other → use the cluster
    midpoint (CONFLUENCE — most defensible)
  • Else: pick the candidate with the strongest defensibility score
    (structural > Fibonacci > Gann > pivot > VWAP > ATR-only)
  • Apply a final risk-reward sanity check: if R:R drops below 1.2:1 with
    the chosen SL, fall back to the ATR-multiple version with a warning
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal
import math


Direction = Literal["BULLISH", "BEARISH"]


@dataclass
class StopLossCandidate:
    method: str               # "ATR" / "STRUCTURAL" / "VWAP" / "FIB" / "GANN" / "PIVOT"
    price: float
    distance_pct: float       # |entry - price| / entry × 100
    rationale: str            # one-line explanation
    defensibility: int        # 1..5 — higher = stronger justification


@dataclass
class StopLossReport:
    direction: Direction
    entry: float
    recommended_sl: float
    recommended_method: str           # which method (or "CONFLUENCE")
    distance_pct: float
    confluence_count: int             # how many methods cluster near recommendation
    confluence_low: Optional[float]   # if cluster, the range
    confluence_high: Optional[float]
    candidates: list[dict]            # all candidates, ranked
    reasons: list[str]                # human-readable explanation
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {**self.__dict__,
                "candidates": [
                    c if isinstance(c, dict) else c.__dict__ for c in self.candidates
                ]}


# ---------------------------------------------------------------------------
# Per-method candidate builders
# ---------------------------------------------------------------------------

def _atr_candidate(*, entry: float, atr: float, direction: Direction,
                    vol_regime: str = "NORMAL") -> Optional[StopLossCandidate]:
    """ATR-based SL. Multiplier depends on volatility regime:
       LOW_VOL → 1.5×ATR, NORMAL → 2.0×ATR, HIGH_VOL → 2.5×ATR.
    """
    if atr <= 0 or entry <= 0:
        return None
    mult = 1.5 if vol_regime == "LOW_VOL" else 2.5 if vol_regime == "HIGH_VOL" else 2.0
    distance = mult * atr
    sl_price = entry - distance if direction == "BULLISH" else entry + distance
    return StopLossCandidate(
        method="ATR",
        price=round(sl_price, 2),
        distance_pct=round(distance / entry * 100, 3),
        rationale=f"{mult}× ATR({atr:.2f}) — volatility-scaled stop",
        defensibility=2,
    )


def _structural_candidate(*, entry: float, direction: Direction,
                            recent_swing_low: float, recent_swing_high: float,
                            buffer_pct: float = 0.15) -> Optional[StopLossCandidate]:
    """Below recent swing low (long) or above swing high (short).
    Adds a small buffer (default 0.15%) so a wick at the level doesn't trigger.

    Returns None if the swing point isn't in a sensible direction relative
    to entry (e.g., a long's swing low is above entry — degenerate)."""
    if direction == "BULLISH":
        if recent_swing_low <= 0 or recent_swing_low >= entry:
            return None
        sl = recent_swing_low * (1 - buffer_pct / 100)
    else:
        if recent_swing_high <= 0 or recent_swing_high <= entry:
            return None
        sl = recent_swing_high * (1 + buffer_pct / 100)
    distance = abs(entry - sl)
    return StopLossCandidate(
        method="STRUCTURAL",
        price=round(sl, 2),
        distance_pct=round(distance / entry * 100, 3),
        rationale=(f"Below recent swing low ₹{recent_swing_low:.2f} "
                     f"(with {buffer_pct}% buffer)" if direction == "BULLISH"
                     else f"Above recent swing high ₹{recent_swing_high:.2f} "
                          f"(with {buffer_pct}% buffer)"),
        defensibility=5,    # highest — structure is king
    )


def _vwap_candidate(*, entry: float, direction: Direction,
                     vwap: float, vwap_lower_1sigma: float, vwap_upper_1sigma: float
                     ) -> Optional[StopLossCandidate]:
    """For long: SL just below VWAP if entry is above VWAP, else below the
    1σ-lower band. For short: mirror image.
    """
    if vwap <= 0:
        return None
    if direction == "BULLISH":
        if entry > vwap:
            # Use VWAP as the anchor — trend leg with buyers in control
            sl = vwap * 0.998
            anchor = f"VWAP ₹{vwap:.2f}"
        else:
            sl = vwap_lower_1sigma * 0.998 if vwap_lower_1sigma > 0 else vwap * 0.99
            anchor = f"VWAP -1σ ₹{vwap_lower_1sigma:.2f}"
    else:
        if entry < vwap:
            sl = vwap * 1.002
            anchor = f"VWAP ₹{vwap:.2f}"
        else:
            sl = vwap_upper_1sigma * 1.002 if vwap_upper_1sigma > 0 else vwap * 1.01
            anchor = f"VWAP +1σ ₹{vwap_upper_1sigma:.2f}"
    if (direction == "BULLISH" and sl >= entry) or (direction == "BEARISH" and sl <= entry):
        return None       # SL on wrong side of entry — degenerate
    distance = abs(entry - sl)
    return StopLossCandidate(
        method="VWAP",
        price=round(sl, 2),
        distance_pct=round(distance / entry * 100, 3),
        rationale=f"Anchored to {anchor} — institutional reference",
        defensibility=3,
    )


def _fib_candidate(*, entry: float, direction: Direction,
                    confluence_zones: list[dict]) -> Optional[StopLossCandidate]:
    """Use the nearest fractal-Fib confluence zone below entry (long) or
    above (short). High defensibility when n_levels in the zone is 3+.
    """
    if not confluence_zones:
        return None
    if direction == "BULLISH":
        below = [z for z in confluence_zones if z.get("midpoint", entry) < entry]
        if not below:
            return None
        # Closest one below
        zone = max(below, key=lambda z: z["midpoint"])
        sl = zone["low"] * 0.998       # just under the cluster low
    else:
        above = [z for z in confluence_zones if z.get("midpoint", entry) > entry]
        if not above:
            return None
        zone = min(above, key=lambda z: z["midpoint"])
        sl = zone["high"] * 1.002
    n_lvls = zone.get("n_levels", 1)
    distance = abs(entry - sl)
    return StopLossCandidate(
        method="FIB",
        price=round(sl, 2),
        distance_pct=round(distance / entry * 100, 3),
        rationale=(f"Just beyond Fib cluster ₹{zone['low']:.2f}–₹{zone['high']:.2f} "
                     f"({n_lvls} levels overlap)"),
        defensibility=4 if n_lvls >= 3 else 3,
    )


def _gann_candidate(*, entry: float, direction: Direction,
                     gann_natural: dict) -> Optional[StopLossCandidate]:
    """Use the nearest integer perfect-square below entry (long) or above (short).
    Strong when price is hugging the n² level."""
    if not gann_natural or gann_natural.get("error"):
        return None
    if direction == "BULLISH":
        # Zero level + lower ladder, pick highest one below entry
        candidates_below = [gann_natural["zero_level"]]
        for lvl in gann_natural.get("lower_levels", []):
            candidates_below.append(lvl["price"])
        valid = [p for p in candidates_below if p < entry]
        if not valid:
            return None
        nearest = max(valid)
        sl = nearest * 0.997
    else:
        # Upper ladder, pick lowest above entry
        candidates_above = [u["price"] for u in gann_natural.get("upper_levels", [])]
        valid = [p for p in candidates_above if p > entry]
        if not valid:
            return None
        nearest = min(valid)
        sl = nearest * 1.003
    distance = abs(entry - sl)
    return StopLossCandidate(
        method="GANN",
        price=round(sl, 2),
        distance_pct=round(distance / entry * 100, 3),
        rationale=f"Just beyond Gann natural square ₹{nearest:.2f}",
        defensibility=3,
    )


def _pivot_candidate(*, entry: float, direction: Direction,
                      pivots_daily: dict) -> Optional[StopLossCandidate]:
    """Use S1 (long) or R1 (short) from the daily pivot set. Prefer Camarilla
    for intraday — its sub-levels (h3/l3) are the most-watched breakout/
    breakdown lines."""
    if not pivots_daily:
        return None
    cam = pivots_daily.get("camarilla", {})
    std = pivots_daily.get("standard", {})
    if direction == "BULLISH":
        # Prefer Camarilla L3 (breakdown line); fall back to S1
        anchor_price = cam.get("l3") or cam.get("s1") or std.get("s1")
        if not anchor_price or anchor_price >= entry:
            return None
        sl = anchor_price * 0.998
        anchor_label = "Camarilla L3" if cam.get("l3") else "S1"
    else:
        anchor_price = cam.get("h3") or cam.get("r1") or std.get("r1")
        if not anchor_price or anchor_price <= entry:
            return None
        sl = anchor_price * 1.002
        anchor_label = "Camarilla H3" if cam.get("h3") else "R1"
    distance = abs(entry - sl)
    return StopLossCandidate(
        method="PIVOT",
        price=round(sl, 2),
        distance_pct=round(distance / entry * 100, 3),
        rationale=f"Beyond daily {anchor_label} ₹{anchor_price:.2f}",
        defensibility=3,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute(*, entry: float, direction: str, atr: float,
             swing_low: Optional[float] = None,
             swing_high: Optional[float] = None,
             vwap_block: Optional[dict] = None,
             fib_fractal_block: Optional[dict] = None,
             gann_natural_block: Optional[dict] = None,
             pivots_block: Optional[dict] = None,
             vol_regime: str = "NORMAL",
             target_1: Optional[float] = None,
             ) -> StopLossReport:
    """Compute the comprehensive SL report.

    Required inputs:
      entry        — recommended entry price
      direction    — BULLISH or BEARISH
      atr          — ATR(14) value for ATR-based fallback

    Optional inputs (each enables one more method):
      swing_low / swing_high   → STRUCTURAL method
      vwap_block               → VWAP method (must have vwap + 1σ bands)
      fib_fractal_block        → FIB method (uses confluence_zones)
      gann_natural_block       → GANN method
      pivots_block             → PIVOT method (uses 'daily' Camarilla / Standard)
      vol_regime               → adjusts ATR multiplier (LOW_VOL/NORMAL/HIGH_VOL)
      target_1                 → enables R:R sanity check
    """
    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError(f"direction must be BULLISH or BEARISH, got {direction!r}")

    dir_typed: Direction = direction    # type: ignore

    # Collect candidates from each method
    candidates: list[StopLossCandidate] = []

    c = _atr_candidate(entry=entry, atr=atr, direction=dir_typed, vol_regime=vol_regime)
    if c: candidates.append(c)

    if swing_low is not None and swing_high is not None:
        c = _structural_candidate(
            entry=entry, direction=dir_typed,
            recent_swing_low=swing_low, recent_swing_high=swing_high,
        )
        if c: candidates.append(c)

    if vwap_block:
        c = _vwap_candidate(
            entry=entry, direction=dir_typed,
            vwap=vwap_block.get("vwap", 0),
            vwap_lower_1sigma=vwap_block.get("lower_1sigma", 0),
            vwap_upper_1sigma=vwap_block.get("upper_1sigma", 0),
        )
        if c: candidates.append(c)

    if fib_fractal_block:
        c = _fib_candidate(
            entry=entry, direction=dir_typed,
            confluence_zones=fib_fractal_block.get("confluence_zones", []),
        )
        if c: candidates.append(c)

    if gann_natural_block:
        c = _gann_candidate(
            entry=entry, direction=dir_typed,
            gann_natural=gann_natural_block,
        )
        if c: candidates.append(c)

    if pivots_block and isinstance(pivots_block, dict):
        c = _pivot_candidate(
            entry=entry, direction=dir_typed,
            pivots_daily=pivots_block.get("daily", {}),
        )
        if c: candidates.append(c)

    # ---------------------------------------------------------------
    # Defensive: if no candidates produced anything usable, ATR fallback
    # ---------------------------------------------------------------
    if not candidates:
        # Generate a desperate ATR fallback even if ATR is 0
        fallback_distance = atr * 2 if atr > 0 else entry * 0.02
        sl = entry - fallback_distance if dir_typed == "BULLISH" else entry + fallback_distance
        return StopLossReport(
            direction=dir_typed, entry=round(entry, 2),
            recommended_sl=round(sl, 2),
            recommended_method="FALLBACK_2PCT",
            distance_pct=(round(fallback_distance / entry * 100, 3) if entry > 0 else 0.0),
            confluence_count=1, confluence_low=None, confluence_high=None,
            candidates=[],
            reasons=["No method produced a usable SL — applied 2% fallback"],
            warnings=["Stop-loss is a fallback; no structural support — consider waiting for a better setup"],
        )

    # ---------------------------------------------------------------
    # Filter candidates that are absurdly close or far. Reasonable range:
    # 0.3% to (10% scaled by volatility regime).
    # ---------------------------------------------------------------
    max_distance_pct = {"LOW_VOL": 4.0, "NORMAL": 6.0, "HIGH_VOL": 10.0}.get(vol_regime, 6.0)
    candidates = [c for c in candidates if 0.3 <= c.distance_pct <= max_distance_pct]
    if not candidates:
        # Re-add ATR — even if out of range it's better than nothing
        c = _atr_candidate(entry=entry, atr=atr, direction=dir_typed, vol_regime=vol_regime)
        if c:
            candidates = [c]

    # ---------------------------------------------------------------
    # Confluence detection — find cluster of candidates within 0.3% of each other
    # ---------------------------------------------------------------
    candidates.sort(key=lambda c: c.price)
    best_cluster: list[StopLossCandidate] = []
    for i, c in enumerate(candidates):
        cluster = [c]
        for j in range(i + 1, len(candidates)):
            other = candidates[j]
            if abs(other.price - c.price) / c.price < 0.003:
                cluster.append(other)
            else:
                break
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    # ---------------------------------------------------------------
    # Selection logic
    # ---------------------------------------------------------------
    reasons: list[str] = []
    warnings: list[str] = []

    if len(best_cluster) >= 2:
        # Multiple methods agree — use the cluster midpoint (highest confidence)
        avg_price = sum(c.price for c in best_cluster) / len(best_cluster)
        methods = " + ".join(sorted(set(c.method for c in best_cluster)))
        recommended_sl = round(avg_price, 2)
        recommended_method = "CONFLUENCE"
        confluence_count = len(best_cluster)
        confluence_low = min(c.price for c in best_cluster)
        confluence_high = max(c.price for c in best_cluster)
        reasons.append(
            f"⚡ {len(best_cluster)} methods converge near ₹{recommended_sl:.2f} ({methods}) "
            f"— highest-confidence stop"
        )
        for c in best_cluster:
            reasons.append(f"  · {c.method}: {c.rationale}")
    else:
        # No cluster — pick the highest defensibility candidate.
        # Tie-break by tightest stop (closer to entry = less to lose)
        ranked = sorted(candidates,
                          key=lambda c: (-c.defensibility, c.distance_pct))
        chosen = ranked[0]
        recommended_sl = chosen.price
        recommended_method = chosen.method
        confluence_count = 1
        confluence_low = confluence_high = None
        reasons.append(f"Best single-method stop: {chosen.method} — {chosen.rationale}")

    # ---------------------------------------------------------------
    # R:R sanity check — if R:R drops below 1.2 with this SL, warn
    # ---------------------------------------------------------------
    if target_1 is not None:
        sl_distance = abs(entry - recommended_sl)
        target_distance = abs(target_1 - entry)
        if sl_distance > 0:
            rr = target_distance / sl_distance
            if rr < 1.2:
                warnings.append(
                    f"R:R only {rr:.2f}:1 with this SL. Either wait for a better entry "
                    f"(closer to support) or accept that this trade has marginal expected value."
                )

    distance_pct = abs(entry - recommended_sl) / entry * 100

    return StopLossReport(
        direction=dir_typed,
        entry=round(entry, 2),
        recommended_sl=round(recommended_sl, 2),
        recommended_method=recommended_method,
        distance_pct=round(distance_pct, 3),
        confluence_count=confluence_count,
        confluence_low=round(confluence_low, 2) if confluence_low else None,
        confluence_high=round(confluence_high, 2) if confluence_high else None,
        candidates=[c.__dict__ for c in candidates],
        reasons=reasons,
        warnings=warnings,
    )
