"""Consistency validator — guards against internally-conflicted recommendations.

Problem this solves:
    Stage-1 esoteric_score is a weighted average. A symbol can clear the gate
    (e.g. score 60) because Gann + Fibonacci are bullish, even when the
    per-symbol astrology is bearish. If Stage-3 then suggests OPT_CE_BUY
    we've recommended a bullish-bet despite *the astrology layer* — one of the
    user's headline requirements — actively contradicting it.

What this module does:
    After Stage-3 picks a strategy, this validator re-checks the strategy's
    direction against:
       1. Per-symbol astrology bias (high severity — it's a headline gate)
       2. Current hora bias (medium severity — timing gate)
       3. Numerology bias (low severity — confluence layer)
       4. Today's overall astro market sentiment (low — context)

    Each disagreement becomes a Conflict with a severity. The validator then
    returns an *adjusted recommendation*:
       • mode='strict'  → any HIGH conflict downgrades the strategy to WAIT
                           and any MEDIUM downgrades confidence by 20
       • mode='warn'    → no downgrades, just annotations
       • mode='block'   → any HIGH or MEDIUM downgrades to WAIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Severity = Literal["LOW", "MEDIUM", "HIGH"]
Mode = Literal["strict", "warn", "block"]


# Strategies that express a bullish view
BULLISH_STRATEGIES = {
    "EQUITY_BUY", "FUT_LONG", "OPT_CE_BUY", "OPT_BULL_CALL_SPREAD",
}
# Strategies that express a bearish view
BEARISH_STRATEGIES = {
    "EQUITY_SHORT", "FUT_SHORT", "OPT_PE_BUY", "OPT_BEAR_PUT_SPREAD",
}
# Neutral / range strategies don't need direction validation
NEUTRAL_STRATEGIES = {
    "OPT_IRON_CONDOR", "OPT_LONG_STRADDLE", "OPT_SHORT_STRANGLE", "WAIT",
}


@dataclass
class Conflict:
    component: str           # 'astrology' | 'hora' | 'numerology' | 'astro_market'
    severity: Severity
    actual_bias: str
    expected_bias: str
    message: str

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class ValidationResult:
    intended_direction: str          # BULLISH / BEARISH / NEUTRAL
    is_consistent: bool
    conflicts: list[dict] = field(default_factory=list)
    severity_counts: dict = field(default_factory=lambda: {"HIGH": 0, "MEDIUM": 0, "LOW": 0})

    original_strategy: str = ""
    adjusted_strategy: str = ""
    confidence_adjustment: float = 0.0
    final_action: str = ""           # PROCEED / WARN / DOWNGRADE_TO_WAIT
    summary: str = ""
    mode: str = ""

    def to_dict(self) -> dict:
        return self.__dict__


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate(
    strategy_type: str,
    esoteric_components: dict,
    hora: dict,
    astro_market: dict | None = None,
    lunar: dict | None = None,
    mode: Mode = "strict",
) -> ValidationResult:
    """Validate a Stage-3 strategy against per-component biases.

    Args:
        strategy_type:        e.g. "OPT_CE_BUY"
        esoteric_components:  dict from Stage 1 containing keys:
                                 astrology  → { score, bias, ... }
                                 numerology → { score, bias, ... }
                                 (gann/fib are *price-anchored* — not directional
                                  in the same way and are excluded from veto)
        hora:                 dict from `engines.hora.current_hora().to_dict()`
        astro_market:         optional overall market sentiment (BULLISH/BEARISH/NEUTRAL)
        mode:                 'strict' | 'warn' | 'block'
    """
    direction = _direction_for(strategy_type)
    conflicts: list[Conflict] = []

    # Neutral strategies don't need directional validation
    if direction == "NEUTRAL":
        return ValidationResult(
            intended_direction="NEUTRAL",
            is_consistent=True,
            original_strategy=strategy_type,
            adjusted_strategy=strategy_type,
            final_action="PROCEED",
            summary="Range/neutral strategy — directional veto not applicable.",
            mode=mode,
        )

    # --- HIGH severity: per-symbol astrology disagrees ---
    astro_bias = (esoteric_components.get("astrology", {}) or {}).get("bias", "NEUTRAL").upper()
    if direction == "BULLISH" and astro_bias == "BEARISH":
        conflicts.append(Conflict(
            component="astrology", severity="HIGH",
            actual_bias=astro_bias, expected_bias="BULLISH",
            message=(f"Strategy {strategy_type} expresses a BULLISH view but per-symbol astrology is BEARISH "
                     f"(nakshatra/ruler analysis). High risk of timing mismatch."),
        ))
    elif direction == "BEARISH" and astro_bias == "BULLISH":
        conflicts.append(Conflict(
            component="astrology", severity="HIGH",
            actual_bias=astro_bias, expected_bias="BEARISH",
            message=(f"Strategy {strategy_type} expresses a BEARISH view but per-symbol astrology is BULLISH. "
                     f"Astro tailwind for the security contradicts the short setup."),
        ))

    # --- MEDIUM severity: current hora disagrees ---
    hora_bias = (hora.get("bias") or "neutral").lower()
    hora_weight = hora.get("weight", 0.5)
    if direction == "BULLISH" and hora_bias == "bearish":
        sev: Severity = "HIGH" if hora_weight >= 0.85 else "MEDIUM"  # Saturn (0.9) → HIGH
        conflicts.append(Conflict(
            component="hora", severity=sev,
            actual_bias=hora_bias.upper(), expected_bias="BULLISH",
            message=(f"Current hora is ruled by {hora.get('ruler')} (bearish, weight {hora_weight}). "
                     f"Buying CE/long in a malefic hora is classically discouraged. "
                     f"Next change in {hora.get('next_change_in_minutes')}m → {hora.get('next_ruler')}."),
        ))
    elif direction == "BEARISH" and hora_bias == "bullish":
        sev = "HIGH" if hora_weight >= 0.85 else "MEDIUM"            # Jupiter (1.0) → HIGH
        conflicts.append(Conflict(
            component="hora", severity=sev,
            actual_bias=hora_bias.upper(), expected_bias="BEARISH",
            message=(f"Current hora is ruled by {hora.get('ruler')} (bullish, weight {hora_weight}). "
                     f"Shorting in a benefic hora is classically discouraged. "
                     f"Next change in {hora.get('next_change_in_minutes')}m → {hora.get('next_ruler')}."),
        ))

    # --- LOW severity: numerology disagrees ---
    num_bias = (esoteric_components.get("numerology", {}) or {}).get("bias", "NEUTRAL").upper()
    if direction == "BULLISH" and num_bias == "BEARISH":
        conflicts.append(Conflict(
            component="numerology", severity="LOW",
            actual_bias=num_bias, expected_bias="BULLISH",
            message=f"Numerology of symbol-vs-date is bearish — minor headwind for {strategy_type}.",
        ))
    elif direction == "BEARISH" and num_bias == "BULLISH":
        conflicts.append(Conflict(
            component="numerology", severity="LOW",
            actual_bias=num_bias, expected_bias="BEARISH",
            message=f"Numerology of symbol-vs-date is bullish — minor headwind for {strategy_type}.",
        ))

    # --- HIGH severity: lunar gate says AVOID / WAIT ---
    # Full Moon / New Moon / Void-of-Course / Eclipse / Riktha tithi are
    # universal lunar trading rules — these are direction-agnostic vetoes that
    # affect EVERY trade type, not just CE/PE.
    if lunar:
        gate = (lunar.get("gate") or "PROCEED").upper()
        if gate == "AVOID":
            conflicts.append(Conflict(
                component="lunar", severity="HIGH",
                actual_bias=gate, expected_bias="PROCEED",
                message=(f"Lunar gate = AVOID: {lunar.get('summary', '')[:200]} "
                          f"Triggered rules: {', '.join(r['rule'] for r in (lunar.get('rules_triggered') or []) if r.get('severity') == 'HIGH')}."),
            ))
        elif gate == "WAIT":
            conflicts.append(Conflict(
                component="lunar", severity="MEDIUM",
                actual_bias=gate, expected_bias="PROCEED",
                message=(f"Lunar gate = WAIT: {lunar.get('summary', '')[:200]}"),
            ))
        elif gate == "CAUTION":
            conflicts.append(Conflict(
                component="lunar", severity="LOW",
                actual_bias=gate, expected_bias="PROCEED",
                message=f"Lunar climate marginal: {lunar.get('summary', '')[:200]}",
            ))

    # --- LOW severity: market-wide astro sentiment disagrees ---
    if astro_market:
        mkt_bias = (astro_market.get("bias") or "NEUTRAL").upper()
        if direction == "BULLISH" and mkt_bias == "BEARISH":
            conflicts.append(Conflict(
                component="astro_market", severity="LOW",
                actual_bias=mkt_bias, expected_bias="BULLISH",
                message="Overall market astrology climate is bearish — symbol-specific edge needs to be strong.",
            ))
        elif direction == "BEARISH" and mkt_bias == "BULLISH":
            conflicts.append(Conflict(
                component="astro_market", severity="LOW",
                actual_bias=mkt_bias, expected_bias="BEARISH",
                message="Overall market astrology climate is bullish — symbol-specific bearish edge needed.",
            ))

    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for c in conflicts:
        counts[c.severity] += 1

    # ----- Adjustment policy -----
    adjusted = strategy_type
    conf_adj = 0.0
    final_action = "PROCEED"
    summary = "All directional layers agree — proceed."

    if conflicts:
        if mode == "block":
            if counts["HIGH"] > 0 or counts["MEDIUM"] > 0:
                adjusted = "WAIT"
                final_action = "DOWNGRADE_TO_WAIT"
                summary = f"Mode=block: {counts['HIGH']} high + {counts['MEDIUM']} medium conflicts → no trade."
        elif mode == "strict":
            if counts["HIGH"] > 0:
                adjusted = "WAIT"
                final_action = "DOWNGRADE_TO_WAIT"
                summary = (
                    f"Mode=strict: {counts['HIGH']} HIGH-severity conflict(s) — "
                    f"astrology/hora actively contradicts the {direction.lower()} thesis. "
                    f"Downgraded to WAIT to avoid timing mismatch."
                )
            elif counts["MEDIUM"] > 0:
                conf_adj = -20.0 * counts["MEDIUM"]
                final_action = "WARN"
                summary = (
                    f"Mode=strict: {counts['MEDIUM']} medium conflict(s) — strategy retained but "
                    f"confidence reduced by {abs(conf_adj):.0f}; consider waiting for the next hora."
                )
            else:
                conf_adj = -5.0 * counts["LOW"]
                final_action = "WARN"
                summary = f"Mode=strict: low-severity confluence warnings only — proceed with caution."
        else:  # warn
            final_action = "WARN"
            summary = "Mode=warn: conflicts noted but no downgrade."

    return ValidationResult(
        intended_direction=direction,
        is_consistent=(len(conflicts) == 0),
        conflicts=[c.to_dict() for c in conflicts],
        severity_counts=counts,
        original_strategy=strategy_type,
        adjusted_strategy=adjusted,
        confidence_adjustment=conf_adj,
        final_action=final_action,
        summary=summary,
        mode=mode,
    )


def _direction_for(strategy_type: str) -> str:
    if strategy_type in BULLISH_STRATEGIES:
        return "BULLISH"
    if strategy_type in BEARISH_STRATEGIES:
        return "BEARISH"
    return "NEUTRAL"
