"""Engine-disagreement confidence band.

A single confidence number like "63%" hides whether the 7 engines all agreed
or fought each other. This module turns the engine bias votes into:

  • A symmetric uncertainty band around the point estimate
  • A vote tally showing how many engines voted each direction
  • Shannon entropy of the vote distribution (0 = unanimous, 1 = max disagreement)
  • A "conviction quality" rating: UNANIMOUS / STRONG / MIXED / CONFLICTED

The wider the band, the less you should trust the headline number.
A 63% call with a [60-66] band means the engines agree.
A 63% call with a [45-75] band means it's basically a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass
class ConfidenceBand:
    point_estimate: float                # 0..100 headline confidence
    lower_bound: float                   # 0..100
    upper_bound: float                   # 0..100
    band_width: float                    # upper - lower
    vote_breakdown: dict                 # {BULLISH: n, BEARISH: n, NEUTRAL: n}
    engine_directions: dict              # {technical: "BULLISH", smc: "NEUTRAL", ...}
    agreement_pct: float                 # % of non-neutral engines voting same way
    disagreement_entropy: float          # 0..1
    conviction_quality: str              # UNANIMOUS / STRONG / MIXED / CONFLICTED / NO_SIGNAL
    sizing_multiplier: float             # 0..1 — scale position size by this
    interpretation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _shannon_entropy(votes: dict[str, int]) -> float:
    """Normalized 0..1 — 0 = unanimous, 1 = max disagreement (uniform)."""
    total = sum(votes.values())
    if total == 0:
        return 0.0
    probs = [v / total for v in votes.values() if v > 0]
    if len(probs) <= 1:
        return 0.0
    h = -sum(p * math.log2(p) for p in probs)
    h_max = math.log2(len(probs))           # max entropy with this many non-zero classes
    return h / h_max if h_max > 0 else 0.0


def compute(engine_biases: dict[str, str],
            point_confidence: float) -> ConfidenceBand:
    """
    engine_biases    : {"technical": "BULLISH", "smc": "BEARISH", ...}
    point_confidence : the headline aggregated confidence (0..100)
    """
    # Normalize directions — bucket SIDEWAYS into NEUTRAL
    norm = {k: ("NEUTRAL" if v in ("SIDEWAYS", "RANGE", "?") else v)
            for k, v in engine_biases.items() if v}

    bull = sum(1 for v in norm.values() if v == "BULLISH")
    bear = sum(1 for v in norm.values() if v == "BEARISH")
    neut = sum(1 for v in norm.values() if v == "NEUTRAL")
    total = bull + bear + neut

    votes = {"BULLISH": bull, "BEARISH": bear, "NEUTRAL": neut}
    directional = bull + bear

    # Agreement % among engines that took a side
    if directional > 0:
        majority = max(bull, bear)
        agreement = majority / directional * 100
    else:
        agreement = 0.0

    # Entropy across the three classes
    entropy = _shannon_entropy(votes)

    # ---- Band width ----
    # Base width scales with entropy. At 0 entropy (unanimous), width = ±3pp.
    # At max entropy (perfect 3-way split), width = ±18pp.
    base_half_width = 3.0 + entropy * 15.0

    # Also penalise when there's strong opposition (bull > 0 AND bear > 0)
    if bull > 0 and bear > 0:
        opposition_factor = 1 + (min(bull, bear) / max(bull, bear)) * 0.5
        base_half_width *= opposition_factor

    # And inflate band if there are many neutrals — indicates engines couldn't decide
    if neut > directional and total > 0:
        base_half_width *= 1.3

    lower = max(0, point_confidence - base_half_width)
    upper = min(100, point_confidence + base_half_width)

    # ---- Conviction quality ----
    if total == 0:
        quality = "NO_SIGNAL"
    elif agreement >= 100 and neut == 0:
        quality = "UNANIMOUS"
    elif agreement >= 80:
        quality = "STRONG"
    elif agreement >= 60:
        quality = "MIXED"
    else:
        quality = "CONFLICTED"

    # ---- Sizing multiplier ----
    # Maps quality + band width → a 0..1 multiplier for position sizing.
    # If you'd size 5% at "UNANIMOUS conviction", scale to 5% * multiplier.
    if quality == "UNANIMOUS":
        sizing = 1.0
    elif quality == "STRONG":
        sizing = 0.75
    elif quality == "MIXED":
        sizing = 0.5
    elif quality == "CONFLICTED":
        sizing = 0.25
    else:
        sizing = 0.0

    # ---- Interpretation ----
    interp = []
    if directional == 0:
        interp.append("Every engine returned NEUTRAL — no actionable directional signal.")
    else:
        winner = "BULLISH" if bull >= bear else "BEARISH"
        interp.append(
            f"{winner} consensus: {majority}/{directional} non-neutral engines ({agreement:.0f}% agreement)"
        )
    interp.append(
        f"Headline confidence {point_confidence:.1f}% → realistic band "
        f"[{lower:.1f}%, {upper:.1f}%] (width {upper - lower:.1f}pp)"
    )
    interp.append(f"Conviction quality: {quality.replace('_', ' ')}")
    if quality == "CONFLICTED":
        interp.append(
            "→ Engines disagree heavily. Treat headline confidence as ~50% — "
            "consider WAIT or use the lower band as effective confidence."
        )
    elif quality == "MIXED":
        interp.append("→ Reduce position size to ~50% of normal sizing")
    elif quality == "STRONG":
        interp.append("→ Acceptable conviction; normal sizing (× 0.75) OK")
    elif quality == "UNANIMOUS":
        interp.append("→ Maximum conviction — sizing can use the full risk budget")

    # Per-engine breakdown (sorted)
    engine_list = ", ".join(
        f"{name}:{bias[0]}" for name, bias in norm.items()
    )
    interp.append(f"Engines: {engine_list}")

    return ConfidenceBand(
        point_estimate=round(point_confidence, 2),
        lower_bound=round(lower, 2),
        upper_bound=round(upper, 2),
        band_width=round(upper - lower, 2),
        vote_breakdown=votes,
        engine_directions=norm,
        agreement_pct=round(agreement, 2),
        disagreement_entropy=round(entropy, 4),
        conviction_quality=quality,
        sizing_multiplier=round(sizing, 3),
        interpretation=interp,
    )
