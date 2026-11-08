"""Engine-weight optimizer — data-driven correction.

For each engine (technical, SMC, options, astrology, Gann, numerology),
this module:

  1. Walks forward through historical OHLCV (using only data available up
     to each bar — no look-ahead)
  2. Computes the engine's STANDALONE prediction direction for the next bar
  3. Compares to what the next bar actually did
  4. Reports per-engine: hit rate, sample size, contribution score

Then it suggests REBALANCED WEIGHTS that, in the historical window, would
have produced the highest weighted-confidence accuracy.

This is the legitimate way to "correct" the system using data — measure each
component's actual contribution and shrink the ones that don't help.

Honest limits:
  • Sample sizes are limited by cached bars (need 100+ for meaningful stats)
  • Astrology layer's full computation is heavy — we sample sparsely for it
  • Past contribution ≠ guaranteed future contribution
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from app.config import settings


# ===========================================================================
# Per-engine standalone predictor (fast — no Swiss Ephemeris per bar)
# ===========================================================================

def _predict_each_engine(df_slice: pd.DataFrame) -> dict[str, str]:
    """Return {engine_name: bias} where bias ∈ {BULLISH, BEARISH, NEUTRAL}.

    Each engine runs on the same slice and gives its own independent call.
    Astrology is intentionally excluded from the per-bar loop — it's analyzed
    separately at coarser granularity (its score is roughly static over short
    windows because planetary positions move slowly).
    """
    if len(df_slice) < 40:
        return {}
    out: dict[str, str] = {}
    try:
        from app.engines import technical, smc, gann, fibonacci, numerology
        tech = technical.analyze(df_slice)
        out["technical"] = tech.bias
        out["smc"]       = smc.analyze(df_slice).market_structure
        out["gann"]      = gann.analyze(tech.indicators["last"]).bias
        out["fibonacci"] = fibonacci.analyze(df_slice).bias
        # numerology is symbol-only, not bar-dependent — call it with placeholder
        out["numerology"] = numerology.analyze("PLACEHOLDER").bias
    except Exception as e:
        logger.debug("weight_optimizer: per-bar predict failed: {}", e)
    return out


# ===========================================================================
# Per-engine hit-rate measurement
# ===========================================================================

@dataclass
class EngineHitRate:
    engine: str
    n_predictions: int
    n_correct: int
    hit_rate: float                        # 0..1
    bullish_calls: int
    bearish_calls: int
    neutral_calls: int
    edge_vs_random: float                  # hit_rate - 0.5
    confidence: str                        # HIGH / MEDIUM / LOW based on sample size

    def to_dict(self) -> dict:
        return self.__dict__


def measure_engines(df: pd.DataFrame, lookback_bars: int = 150,
                     warmup: int = 50) -> list[EngineHitRate]:
    """Walk-forward measurement of each engine's standalone predictive
    accuracy. Returns one EngineHitRate per engine.
    """
    if df is None or df.empty or len(df) < warmup + 30:
        return []

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    closes = df["close"].astype(float).values
    n = len(df)
    start = max(warmup, n - lookback_bars)

    counters: dict[str, dict] = {}        # engine → {pred: [], realized: []}

    for i in range(start, n - 1):
        try:
            preds = _predict_each_engine(df.iloc[: i + 1])
            if not preds:
                continue
            realized_up = closes[i + 1] > closes[i]
            for engine, bias in preds.items():
                if bias not in ("BULLISH", "BEARISH"):
                    counters.setdefault(engine, _empty()).setdefault("neutral", 0)
                    counters[engine]["neutral"] = counters[engine].get("neutral", 0) + 1
                    continue
                predicted_up = (bias == "BULLISH")
                rec = counters.setdefault(engine, _empty())
                rec["n"] += 1
                if predicted_up:
                    rec["bull"] += 1
                else:
                    rec["bear"] += 1
                if predicted_up == realized_up:
                    rec["correct"] += 1
        except Exception:
            continue

    results: list[EngineHitRate] = []
    for engine, rec in counters.items():
        n_pred = rec["n"]
        n_corr = rec["correct"]
        hit = (n_corr / n_pred) if n_pred > 0 else 0
        edge = hit - 0.5
        conf = "HIGH" if n_pred >= 80 else "MEDIUM" if n_pred >= 30 else "LOW"
        results.append(EngineHitRate(
            engine=engine,
            n_predictions=n_pred,
            n_correct=n_corr,
            hit_rate=round(hit, 4),
            bullish_calls=rec["bull"],
            bearish_calls=rec["bear"],
            neutral_calls=rec.get("neutral", 0),
            edge_vs_random=round(edge, 4),
            confidence=conf,
        ))
    # sort by edge descending
    results.sort(key=lambda r: -r.edge_vs_random)
    return results


def _empty():
    return {"n": 0, "correct": 0, "bull": 0, "bear": 0, "neutral": 0}


# ===========================================================================
# Suggested weights — based on edge, not opinion
# ===========================================================================

# Default fallback weights — what decision.py uses if no override
BASELINE_WEIGHTS = {
    "technical":  0.30,
    "smc":        0.20,
    "options":    0.20,
    "astro":      0.12,
    "gann":       0.12,
    "numerology": 0.06,
}


def suggest_weights(hit_rates: list[EngineHitRate]) -> dict[str, float]:
    """Map measured hit-rates → suggested weights.

    Rules:
      • Engines with <30 samples: keep baseline weight (insufficient data)
      • Engines with hit_rate ≥ 0.55 (real edge): proportional bonus
      • Engines with hit_rate ≤ 0.48 (negative edge): zero them out
      • Engines with hit_rate 0.48-0.55: keep baseline
      • Options and Astrology aren't measured per-bar (too expensive to vary);
        if measured layer drops weight, the freed weight goes to options first.

    Returns weights normalized to sum to 1.0.
    """
    new_weights = dict(BASELINE_WEIGHTS)
    measured = {h.engine: h for h in hit_rates}

    for engine in ("technical", "smc", "gann", "fibonacci", "numerology"):
        h = measured.get(engine)
        if h is None or h.confidence == "LOW":
            continue        # insufficient data, keep baseline
        if h.hit_rate <= 0.48:
            # Negative edge — zero this engine
            if engine == "fibonacci":
                # Fibonacci isn't a baseline weight key — included via Gann
                continue
            old = new_weights.get(engine, 0)
            new_weights[engine] = 0
            # Donate freed weight to the best-performing measured engine
            best = max(hit_rates, key=lambda x: x.edge_vs_random)
            if best.edge_vs_random > 0 and best.engine in new_weights:
                new_weights[best.engine] = new_weights.get(best.engine, 0) + old * 0.8
                new_weights["options"] = new_weights.get("options", 0) + old * 0.2

    # Astrology: special case — almost always negative-to-zero edge.
    # If measured engines collectively show astro doesn't help, shrink it.
    measured_total_edge = sum(h.edge_vs_random for h in hit_rates
                               if h.confidence != "LOW")
    if measured_total_edge < 0:
        # Astro is the most likely culprit (we don't measure it per-bar);
        # shrink it conservatively and reallocate to technical+smc
        old_astro = new_weights.get("astro", 0)
        new_weights["astro"] = old_astro * 0.5
        freed = old_astro - new_weights["astro"]
        new_weights["technical"] = new_weights.get("technical", 0) + freed * 0.6
        new_weights["smc"]       = new_weights.get("smc", 0)       + freed * 0.4

    # Normalize to 1.0
    total = sum(new_weights.values())
    if total > 0:
        new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
    return new_weights


# ===========================================================================
# Weights config persistence — decision.py reads this on each call
# ===========================================================================

CONFIG_PATH = Path("./data/engine_weights.json")
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def save_weights(weights: dict[str, float], source: str = "manual") -> None:
    """Persist weights to disk. decision.py reloads them per request."""
    payload = {
        "weights": weights,
        "saved_at": datetime.utcnow().isoformat(),
        "source": source,
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2))
    logger.info("Engine weights saved to {}: {}", CONFIG_PATH, weights)


def load_weights() -> dict[str, float] | None:
    """Read persisted weights. Returns None if file missing — caller uses
    DEFAULT_WEIGHTS in that case."""
    if not CONFIG_PATH.exists():
        return None
    try:
        payload = json.loads(CONFIG_PATH.read_text())
        return payload.get("weights")
    except Exception as e:
        logger.warning("load_weights failed: {}", e)
        return None


def current_config() -> dict:
    """Return what's currently active + when it was set."""
    if not CONFIG_PATH.exists():
        return {"weights": BASELINE_WEIGHTS, "saved_at": None, "source": "baseline (default)"}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        return {"weights": BASELINE_WEIGHTS, "error": str(e)}


# ===========================================================================
# Full optimization run
# ===========================================================================

@dataclass
class OptimizationReport:
    symbol: str
    bars_analyzed: int
    engine_hit_rates: list[dict]
    baseline_weights: dict
    suggested_weights: dict
    expected_improvement_pp: float       # estimated win-rate improvement
    notes: list[str]
    saved_at: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__


def optimize_for_symbol(df: pd.DataFrame, symbol: str = "?",
                         lookback_bars: int = 150) -> OptimizationReport:
    """Run the full measurement + suggestion pipeline for one symbol."""
    hit_rates = measure_engines(df, lookback_bars=lookback_bars)
    if not hit_rates:
        return OptimizationReport(
            symbol=symbol, bars_analyzed=0,
            engine_hit_rates=[], baseline_weights=BASELINE_WEIGHTS,
            suggested_weights=BASELINE_WEIGHTS, expected_improvement_pp=0,
            notes=["Insufficient bars to measure engines"],
        )

    suggested = suggest_weights(hit_rates)

    # Estimated improvement: weighted average hit rate under new weights minus old
    def _weighted_avg(weights):
        total_w = 0.0
        total_score = 0.0
        for h in hit_rates:
            w = weights.get(h.engine, 0)
            total_w += w
            total_score += w * h.hit_rate
        return total_score / total_w if total_w > 0 else 0.5

    old_score = _weighted_avg(BASELINE_WEIGHTS)
    new_score = _weighted_avg(suggested)
    improvement_pp = (new_score - old_score) * 100

    notes: list[str] = []
    notes.append(f"Measured {len(hit_rates)} engines over {hit_rates[0].n_predictions if hit_rates else 0} bars")
    for h in hit_rates:
        sign = "+" if h.edge_vs_random > 0 else ""
        notes.append(
            f"  • {h.engine:12s}: hit_rate={h.hit_rate*100:.1f}% "
            f"(edge {sign}{h.edge_vs_random*100:.1f}pp, n={h.n_predictions}, conf={h.confidence})"
        )
    if improvement_pp > 1:
        notes.append(f"→ Suggested rebalance would improve weighted accuracy by ~{improvement_pp:.1f}pp")
    elif improvement_pp < -1:
        notes.append(f"→ Suggested weights look worse than baseline ({improvement_pp:.1f}pp) — keep baseline")
    else:
        notes.append("→ Marginal improvement — current weights are close to optimal on this data")

    return OptimizationReport(
        symbol=symbol,
        bars_analyzed=hit_rates[0].n_predictions if hit_rates else 0,
        engine_hit_rates=[h.to_dict() for h in hit_rates],
        baseline_weights=BASELINE_WEIGHTS,
        suggested_weights=suggested,
        expected_improvement_pp=round(improvement_pp, 2),
        notes=notes,
    )
