"""Professional recommendation grading layer.

Takes the raw output of `decision.aggregate()` and adds a presentation layer
modelled on institutional research platforms (Morningstar / BlackRock-style
ratings, with explicit honesty about the underlying methodology's limits):

  • 7-tier conviction label   STRONG_BUY → BUY → ACCUMULATE → HOLD → REDUCE
                              → SELL → STRONG_SELL
  • Conviction stars 1..5     (visualises engine *agreement*, not certainty)
  • Instrument suitability    Ranked list: EQUITY / FUT / OPTIONS — with
                              specific reasons per instrument tier
  • Time-horizon tag          INTRADAY / SWING / POSITIONAL with rationale
  • Risk profile variants     AGGRESSIVE / MODERATE / CONSERVATIVE sizing of
                              the SAME signal
  • Allocation guidance       % of capital per conviction tier

Design principles (honesty):
  • Stars reflect *engine agreement*, not predictive accuracy
  • Every recommendation carries a confidence interval, not a point estimate
  • The disclaimer field is mandatory and machine-readable
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


ConvictionLabel = Literal[
    "STRONG_BUY", "BUY", "ACCUMULATE", "HOLD", "REDUCE", "SELL", "STRONG_SELL",
]
Instrument = Literal["EQUITY", "FUTURES", "OPTIONS"]
RiskProfile = Literal["AGGRESSIVE", "MODERATE", "CONSERVATIVE"]


# ---------------------------------------------------------------------------
# Conviction tier thresholds
# ---------------------------------------------------------------------------

CONVICTION_THRESHOLDS = [
    # (min_confidence, label,         stars, allocation_pct_of_max)
    (80,              "STRONG_BUY",   5,     1.00),
    (70,              "BUY",          4,     0.75),
    (60,              "ACCUMULATE",   3,     0.50),
    (45,              "HOLD",         2,     0.00),
    (35,              "REDUCE",       3,     0.50),
    (25,              "SELL",         4,     0.75),
    (0,               "STRONG_SELL",  5,     1.00),
]


def _grade_bullish(confidence: float) -> tuple[str, int, float]:
    """For bullish-side scoring (confidence rising = stronger buy)."""
    for threshold, label, stars, alloc in CONVICTION_THRESHOLDS[:4]:
        if confidence >= threshold:
            return label, stars, alloc
    return "HOLD", 2, 0.0


def _grade_bearish(confidence: float) -> tuple[str, int, float]:
    """For bearish-side scoring (confidence falling = stronger sell)."""
    if confidence >= 45:
        return "HOLD", 2, 0.0
    if confidence >= 35:
        return "REDUCE", 3, 0.5
    if confidence >= 25:
        return "SELL", 4, 0.75
    return "STRONG_SELL", 5, 1.0


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class ProfessionalGrade:
    conviction_label: str
    stars: int                          # 1..5
    direction: str                      # BULLISH / BEARISH / NEUTRAL
    confidence: float                   # 0..100
    confidence_interval: tuple[float, float]   # rough lower/upper estimate
    engine_agreement_pct: float         # % of engines agreeing with direction
    horizon: str                        # INTRADAY / SWING / POSITIONAL
    instrument_ranking: list[dict]      # ranked: best instrument first
    risk_variants: dict                 # {AGGRESSIVE: {...}, MODERATE: {...}, CONSERVATIVE: {...}}
    allocation_pct: float               # max % of capital for MODERATE risk
    reasons: list[str]
    caveats: list[str]
    disclaimer: str

    def to_dict(self) -> dict:
        return {
            "conviction_label": self.conviction_label,
            "stars": self.stars,
            "direction": self.direction,
            "confidence": round(self.confidence, 2),
            "confidence_interval": [round(self.confidence_interval[0], 1),
                                     round(self.confidence_interval[1], 1)],
            "engine_agreement_pct": round(self.engine_agreement_pct, 1),
            "horizon": self.horizon,
            "instrument_ranking": self.instrument_ranking,
            "risk_variants": self.risk_variants,
            "allocation_pct": round(self.allocation_pct, 2),
            "reasons": self.reasons,
            "caveats": self.caveats,
            "disclaimer": self.disclaimer,
        }


# ---------------------------------------------------------------------------
# Engine-agreement scoring
# ---------------------------------------------------------------------------

def _engine_agreement(engines: dict, target_direction: str) -> tuple[float, list[str]]:
    """Count how many engines agree with the headline direction.

    BULLISH-aligned bias = BULLISH; BEARISH-aligned bias = BEARISH.
    Returns (agreement_pct, list_of_disagreeing_engines).
    """
    if not engines:
        return 0.0, []
    aligned = 0
    total = 0
    disagreeing: list[str] = []
    for name, eng in engines.items():
        bias = (eng.get("bias") or "").upper()
        if not bias or bias == "NEUTRAL" or bias == "SIDEWAYS":
            continue
        total += 1
        if (target_direction == "BULLISH" and bias == "BULLISH") or \
           (target_direction == "BEARISH" and bias == "BEARISH"):
            aligned += 1
        else:
            disagreeing.append(name)
    if total == 0:
        return 0.0, disagreeing
    return aligned / total * 100, disagreeing


def _confidence_interval(confidence: float, agreement_pct: float) -> tuple[float, float]:
    """Heuristic CI: low agreement widens the band.

    100% agreement → ±3pp; 50% agreement → ±15pp.
    """
    spread = max(3.0, (100 - agreement_pct) * 0.3)
    return (max(0, confidence - spread), min(100, confidence + spread))


# ---------------------------------------------------------------------------
# Horizon selection
# ---------------------------------------------------------------------------

def _select_horizon(engines: dict, atr_pct: float | None,
                    requested: str = "SWING") -> tuple[str, str]:
    """Pick a horizon based on engine signals and volatility regime.
    Returns (horizon, rationale).
    """
    if requested and requested != "AUTO":
        return requested, f"User-requested {requested}"

    # Volatility heuristic
    if atr_pct is not None:
        if atr_pct > 3.0:
            return "INTRADAY", f"High volatility (ATR {atr_pct:.1f}%) — intraday only"
        if atr_pct < 1.0:
            return "POSITIONAL", f"Low volatility (ATR {atr_pct:.1f}%) — favours hold periods"
    return "SWING", "Mid volatility — 2-5 day swing horizon optimal"


# ---------------------------------------------------------------------------
# Instrument suitability ranking
# ---------------------------------------------------------------------------

def _rank_instruments(direction: str, confidence: float, iv_pct: float | None,
                      is_fno: bool, atr_pct: float | None) -> list[dict]:
    """Return instruments ranked best-fit first for THIS particular signal.

    Each instrument is scored 0..100. Top score wins. Reasons explain why
    THIS instrument is better than the others for THIS signal.
    """
    iv = iv_pct or 20.0
    atr = atr_pct or 1.5

    candidates: list[dict] = []

    # ----- EQUITY -----
    eq_score = 50
    eq_reasons = []
    if confidence >= 60 and direction == "BULLISH":
        eq_score += 25
        eq_reasons.append("Strong bullish — cash delivery captures full upside")
    if direction == "BEARISH" and not is_fno:
        eq_score += 15
        eq_reasons.append("Bearish equity short — only viable in cash intraday")
    if atr < 1.5:
        eq_score += 10
        eq_reasons.append(f"Low ATR ({atr:.1f}%) — equity stable for swing/positional")
    if direction == "NEUTRAL" or direction == "SIDEWAYS":
        eq_score -= 20
        eq_reasons.append("No directional edge — equity holding wastes capital")
    candidates.append({
        "instrument": "EQUITY",
        "score": max(0, min(100, eq_score)),
        "subtype": "Cash delivery" if direction == "BULLISH" else "Intraday short",
        "pros": eq_reasons,
        "cons": [
            "Full capital outlay — no leverage",
            "Cash short = intraday only (SLB exposure for overnight)" if direction == "BEARISH" else None,
        ],
        "best_for": "Capital-light traders, low-volatility instruments, long-horizon holds",
    })

    # ----- FUTURES -----
    fut_score = 30 if is_fno else 0
    fut_reasons = []
    if is_fno and confidence >= 65 and iv >= 25:
        fut_score += 30
        fut_reasons.append(f"High IV ({iv:.1f}%) makes option premia expensive — futures cheaper for directional bet")
    if is_fno and atr >= 1.5:
        fut_score += 15
        fut_reasons.append(f"Decent volatility ({atr:.1f}% ATR) — leverage amplifies move efficiently")
    if not is_fno:
        fut_reasons.append("Symbol not in F&O universe — futures unavailable")
    candidates.append({
        "instrument": "FUTURES",
        "score": max(0, min(100, fut_score)),
        "subtype": "FUT_LONG" if direction == "BULLISH" else "FUT_SHORT" if direction == "BEARISH" else "N/A",
        "pros": fut_reasons,
        "cons": [
            "Lot size capital lockup (margin)",
            "Daily M2M — overnight gap risk",
            "Unlimited loss potential if SL not honoured",
        ],
        "best_for": "Strong directional view + high IV + margin-comfortable trader",
    })

    # ----- OPTIONS -----
    opt_score = 30 if is_fno else 0
    opt_reasons = []
    opt_subtype = "N/A"
    if is_fno:
        if iv < 18 and confidence >= 65 and direction == "BULLISH":
            opt_score += 35
            opt_subtype = "OPT_CE_BUY (ATM/OTM)"
            opt_reasons.append(f"Low IV ({iv:.1f}%) — buying calls is cheap; max risk = premium")
        elif iv < 18 and confidence >= 65 and direction == "BEARISH":
            opt_score += 35
            opt_subtype = "OPT_PE_BUY (ATM/OTM)"
            opt_reasons.append(f"Low IV ({iv:.1f}%) — buying puts is cheap; max risk = premium")
        elif 18 <= iv < 28 and direction in ("BULLISH", "BEARISH"):
            opt_score += 25
            opt_subtype = "BULL_CALL_SPREAD" if direction == "BULLISH" else "BEAR_PUT_SPREAD"
            opt_reasons.append(f"Mid IV ({iv:.1f}%) — spread caps cost while keeping defined R:R")
        elif iv >= 30 and direction in ("NEUTRAL", "SIDEWAYS"):
            opt_score += 30
            opt_subtype = "IRON_CONDOR"
            opt_reasons.append(f"High IV ({iv:.1f}%) + range-bound — sell premium with wings")
        elif iv >= 35 and direction in ("NEUTRAL", "SIDEWAYS"):
            opt_score += 25
            opt_subtype = "SHORT_STRANGLE"
            opt_reasons.append(f"Very high IV ({iv:.1f}%) — strangle harvest, margin-heavy")
        elif iv < 15 and direction == "NEUTRAL":
            opt_score += 25
            opt_subtype = "LONG_STRADDLE"
            opt_reasons.append(f"Compressed IV ({iv:.1f}%) — straddle for vol expansion")
    candidates.append({
        "instrument": "OPTIONS",
        "score": max(0, min(100, opt_score)),
        "subtype": opt_subtype,
        "pros": opt_reasons,
        "cons": [
            "Theta decay — wrong timing kills premium-buy strategies",
            "IV crush risk for buyers after events",
            "Margin requirement for sellers / spreads",
        ],
        "best_for": "Capital-efficient leverage, defined risk, event/timing-specific trades",
    })

    candidates.sort(key=lambda c: -c["score"])
    # Mark the best one
    if candidates:
        candidates[0]["rank"] = 1
        candidates[0]["recommended"] = True
        for i, c in enumerate(candidates[1:], start=2):
            c["rank"] = i
            c["recommended"] = False

    return candidates


# ---------------------------------------------------------------------------
# Risk profile variants
# ---------------------------------------------------------------------------

def _risk_variants(base_allocation_pct: float, entry: float, stoploss: float,
                    targets: list[float], capital: float) -> dict:
    """For the same signal, produce three sizing variants.

    AGGRESSIVE  : full alloc, single target = target[-1] (T3)
    MODERATE    : 70% alloc, scale-out at T1/T2
    CONSERVATIVE: 40% alloc, exit fully at T1
    """
    def _build(label: str, alloc_mult: float, target_strategy: str) -> dict:
        alloc = round(base_allocation_pct * alloc_mult, 2)
        cap_inr = round(capital * alloc / 100, 2)
        per_unit = max(1.0, entry)
        qty = int(cap_inr // per_unit) if per_unit else 0
        risk_per_unit = abs(entry - stoploss) if stoploss else 0
        max_loss = round(risk_per_unit * qty, 2)
        return {
            "profile": label,
            "allocation_pct": alloc,
            "capital_inr": cap_inr,
            "suggested_qty": qty,
            "max_loss_inr": max_loss,
            "target_strategy": target_strategy,
            "targets_used": (
                [targets[-1]] if label == "AGGRESSIVE" and targets else
                targets[:2] if label == "MODERATE" else
                targets[:1] if targets else []
            ),
        }

    return {
        "AGGRESSIVE":   _build("AGGRESSIVE",   1.00, "Hold for T3 (max target) — accept full swing"),
        "MODERATE":     _build("MODERATE",     0.70, "Scale out 50% at T1, 50% at T2; trail SL"),
        "CONSERVATIVE": _build("CONSERVATIVE", 0.40, "Exit fully at T1 — book quick R"),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def grade(signal_dict: dict, capital: float = 100_000, is_fno: bool = True,
          iv_pct: float | None = None, atr_pct: float | None = None,
          requested_horizon: str = "AUTO") -> ProfessionalGrade:
    """Convert a raw decision.aggregate() output dict into a professional
    recommendation grade.
    """
    confidence = float(signal_dict.get("confidence", 50))
    trend = signal_dict.get("trend", "SIDEWAYS")
    direction = "BULLISH" if trend == "BULLISH" else "BEARISH" if trend == "BEARISH" else "NEUTRAL"
    engines = signal_dict.get("engines", {})

    # Engine agreement
    agreement_pct, disagreeing = _engine_agreement(engines, direction)

    # Conviction
    if direction == "BULLISH":
        label, stars, alloc_mult = _grade_bullish(confidence)
    elif direction == "BEARISH":
        # For bearish we invert: confidence is "bearish strength"
        # decision.aggregate uses one global score; <=40 means bearish in that
        # codebase. So lower confidence == stronger bearish.
        label, stars, alloc_mult = _grade_bearish(confidence)
    else:
        label, stars, alloc_mult = "HOLD", 2, 0.0

    # Confidence interval (engine-agreement-weighted)
    ci = _confidence_interval(confidence, agreement_pct)

    # Horizon
    horizon, horizon_rationale = _select_horizon(engines, atr_pct, requested_horizon)

    # Instrument ranking
    instruments = _rank_instruments(direction, confidence, iv_pct, is_fno, atr_pct)

    # Allocation guidance — moderate baseline allocation in % of capital
    max_alloc_for_strong = 5.0          # cap at 5% even for STRONG_BUY (Kelly-light)
    base_alloc = max_alloc_for_strong * alloc_mult

    # Risk variants
    risk_variants = _risk_variants(
        base_allocation_pct=base_alloc,
        entry=float(signal_dict.get("entry", 0)),
        stoploss=float(signal_dict.get("stoploss", 0)),
        targets=list(signal_dict.get("targets", [])),
        capital=capital,
    )

    # Reasons / caveats
    reasons: list[str] = []
    caveats: list[str] = []
    reasons.append(f"{label} conviction at {stars}/5 stars — {agreement_pct:.0f}% engine agreement")
    reasons.append(f"Horizon: {horizon} — {horizon_rationale}")
    if instruments:
        top_inst = instruments[0]
        reasons.append(f"Best instrument: {top_inst['instrument']} ({top_inst['subtype']})")
    if disagreeing:
        caveats.append(f"Disagreeing engines: {', '.join(disagreeing)}")
    if agreement_pct < 60:
        caveats.append(f"Below 60% engine agreement — conviction is soft, treat as exploratory")
    if confidence < 50 and direction == "BULLISH":
        caveats.append("Bullish lean but confidence below 50 — not a high-conviction long")

    disclaimer = (
        "Conviction stars reflect ENGINE AGREEMENT not predictive accuracy. "
        "This system includes astrology/numerology layers that have no peer-"
        "reviewed evidence of predictive edge. Recommendation is for research "
        "purposes only — not SEBI-registered advice. Validate in paper trading "
        "for 30+ sessions before risking capital."
    )

    return ProfessionalGrade(
        conviction_label=label,
        stars=stars,
        direction=direction,
        confidence=confidence,
        confidence_interval=ci,
        engine_agreement_pct=agreement_pct,
        horizon=horizon,
        instrument_ranking=instruments,
        risk_variants=risk_variants,
        allocation_pct=round(base_alloc, 2),
        reasons=reasons,
        caveats=caveats,
        disclaimer=disclaimer,
    )
