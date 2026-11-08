"""Sequential gated pipeline.

Stage 1 — Esoteric Pre-Filter (gating)
    For every symbol in the universe, compute:
      • Astro/Nakshatra symbol match
      • Numerology compatibility with today's date
      • Gann key-level proximity
      • Fibonacci golden-ratio proximity
    Combine into an esoteric_score. SURVIVOR if score ≥ esoteric_min.

Stage 2 — Technical Confirmation (gating)
    For survivors only:
      • Technical (RSI/MACD/EMA/BB/ATR/ADX/VWAP)
      • SMC (BoS, CHoCH, OB, FVG, premium/discount)
      • Multi-timeframe trend agreement
    Combine into a technical_score. CONFIRMED if score agrees with esoteric
    direction AND ≥ technical_min.

Stage 3 — Strategy Selection
    For each confirmed symbol:
      • Pick the best playbook (intraday/swing/positional/options CE/PE/spread/condor)
      • Compute entry/SL/targets/size/capital allocation

Stage 4 — Accuracy Attachment
    For each finalist:
      • Run a mini walk-forward backtest (faster, smaller lookback)
      • Attach historical hit-rate, expectancy, profit factor
    Final confidence = blend(esoteric, technical, historical_accuracy)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

from app.engines import (
    astrology, numerology, gann, fibonacci, technical, smc,
    strategy as strategy_eng, backtest, hora as hora_eng, consistency,
    confluence as confluence_eng, moon as moon_eng, ml as ml_eng,
)
from app.services.market_data import get_ohlcv
from app.services.universe import all_symbols, sector_of, top_liquid
from app.services import alerts as alerts_svc


# ============================================================================
# Stage 1 — Esoteric pre-filter
# ============================================================================

@dataclass
class EsotericReading:
    symbol: str
    sector: str
    score: float                      # 0..100 (>50 bullish lean)
    direction: str                    # BULLISH / BEARISH / NEUTRAL
    components: dict                  # per-engine subscores
    reasons: list[str]


def esoteric_evaluate(symbol: str, spot: float | None = None) -> EsotericReading:
    """Stage 1 — astro + nakshatra + numerology + gann + fibonacci, no technicals."""
    # Need a price for Gann/Fib. If broker not authed, fetch synthetic OHLCV last close.
    df = None
    if spot is None:
        df = get_ohlcv(symbol, periods=80)
        spot = float(df["close"].iloc[-1])

    # 1. Astrology — symbol vs sky
    astro_sym = astrology.symbol_astro_match(symbol)

    # 2. Numerology
    num = numerology.analyze(symbol)

    # 3. Gann — proximity to key Square-of-9 levels
    g = gann.analyze(spot)

    # 4. Fibonacci — requires OHLCV
    if df is None:
        df = get_ohlcv(symbol, periods=80)
    fib = fibonacci.analyze(df)

    # Aggregate (weights favour Gann + Fib as they're price-anchored)
    score = (
        0.18 * astro_sym["score"] +
        0.12 * num.score +
        0.35 * g.score +
        0.35 * fib.score
    )

    direction = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"
    reasons = (
        astro_sym["reasons"][:2]
        + num.reasons[:1]
        + g.reasons[:2]
        + fib.reasons[:2]
    )

    return EsotericReading(
        symbol=symbol,
        sector=sector_of(symbol),
        score=round(score, 2),
        direction=direction,
        components={
            "astrology": {"score": astro_sym["score"], "bias": astro_sym["bias"],
                           "nakshatra": astro_sym["symbol_nakshatra"]["name"],
                           "ruler": astro_sym["symbol_nakshatra"]["ruler"]},
            "numerology": {"score": num.score, "bias": num.bias, "ruler": num.planetary_ruler},
            "gann":      {"score": g.score, "bias": g.bias,
                           "nearest_support": g.nearest_support,
                           "nearest_resistance": g.nearest_resistance,
                           "upcoming_cycles": g.upcoming_cycle_dates},
            "fibonacci": {"score": fib.score, "bias": fib.bias,
                           "nearest_level": fib.nearest_level,
                           "at_golden": fib.at_golden_ratio,
                           "swing_direction": fib.swing_direction},
        },
        reasons=reasons,
    )


# ============================================================================
# Stage 2 — Technical confirmation
# ============================================================================

@dataclass
class TechnicalConfirmation:
    symbol: str
    score: float                      # 0..100
    direction: str                    # BULLISH / BEARISH / SIDEWAYS
    agrees_with_esoteric: bool
    technical_indicators: dict
    smc_structure: str
    reasons: list[str]
    atr: float
    spot: float


def technical_evaluate(symbol: str, esoteric_dir: str, df=None) -> TechnicalConfirmation:
    if df is None:
        df = get_ohlcv(symbol, periods=250)
    tech = technical.analyze(df)
    smc_res = smc.analyze(df)
    combined = 0.6 * tech.score + 0.4 * smc_res.score
    direction = "BULLISH" if combined >= 60 else "BEARISH" if combined <= 40 else "SIDEWAYS"
    agrees = (direction == esoteric_dir) or (direction == "SIDEWAYS")
    reasons = tech.reasons[:3] + smc_res.reasons[:2]
    return TechnicalConfirmation(
        symbol=symbol,
        score=round(combined, 2),
        direction=direction,
        agrees_with_esoteric=agrees,
        technical_indicators=tech.indicators,
        smc_structure=smc_res.market_structure,
        reasons=reasons,
        atr=tech.indicators["atr14"],
        spot=tech.indicators["last"],
    )


# ============================================================================
# Stage 4 — Quick accuracy mini-backtest
# ============================================================================

def quick_backtest_accuracy(symbol: str, df, threshold: float = 60.0) -> dict:
    try:
        report = backtest.run(
            symbol=symbol, df=df,
            lookback_bars=120, warmup_bars=60,
            confidence_threshold=threshold,
            atr_sl_mult=1.5, atr_target_mult=3.0, max_bars_held=12,
        )
        return {
            "trades": report.total_trades,
            "hit_rate": report.hit_rate,
            "profit_factor": report.profit_factor if report.profit_factor != float("inf") else 999.0,
            "expectancy_pct": report.expectancy_pct,
            "max_drawdown_pct": report.max_drawdown_pct,
            "sample_size_warning": report.total_trades < 8,
        }
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# Full pipeline
# ============================================================================

@dataclass
class PipelineFinalist:
    symbol: str
    sector: str
    esoteric: dict
    technical: dict
    strategy: dict
    accuracy: dict
    final_confidence: float           # blended 0..100
    final_signal: str                 # STRONG_BUY / BUY / SELL / STRONG_SELL / NEUTRAL
    composite_reasons: dict[str, str]

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class PipelineRun:
    asof: str
    horizon: str
    capital: float
    universe_size: int
    stage1_passed: int
    stage2_passed: int
    finalists: list[dict] = field(default_factory=list)
    rejected_stage1: list[dict] = field(default_factory=list)
    rejected_stage2: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


def _signal_label(score: float) -> str:
    if score >= 75:   return "STRONG_BUY"
    if score >= 60:   return "BUY"
    if score <= 25:   return "STRONG_SELL"
    if score <= 40:   return "SELL"
    return "NEUTRAL"


def run_pipeline(
    universe: list[str] | None = None,
    horizon: Literal["INTRADAY", "SWING", "POSITIONAL"] = "SWING",
    capital: float = 100_000,
    esoteric_min: float = 55.0,
    technical_min: float = 55.0,
    require_agreement: bool = True,
    max_finalists: int = 15,
    parallel: int = 6,
    attach_accuracy: bool = True,
    consistency_mode: Literal["strict", "warn", "block"] = "strict",
    quick: bool = True,
    diamond_only: bool = False,
    min_backtest_hit_rate: float = 0.0,
) -> PipelineRun:
    universe = universe or (top_liquid(50) if quick else all_symbols(include_indices=True))
    asof = datetime.now().isoformat()
    errors: list[str] = []
    rejected_s1: list[dict] = []
    rejected_s2: list[dict] = []
    s1_passed: list[EsotericReading] = []

    # Compute hora ONCE — it's the same for every symbol at this instant
    try:
        hora_now = hora_eng.current_hora().to_dict()
    except Exception as e:
        errors.append(f"hora init failed: {e}")
        hora_now = {"ruler": "Unknown", "bias": "neutral", "weight": 0.0,
                     "notes": "hora unavailable", "next_change_in_minutes": 0,
                     "next_ruler": "Unknown"}
    # And the overall astro market sentiment ONCE — used as low-severity context
    try:
        astro_market_now = astrology.market_sentiment(datetime.now()).to_dict()
    except Exception as e:
        errors.append(f"astro market init failed: {e}")
        astro_market_now = {"bias": "NEUTRAL"}
    # Lunar reading ONCE per run — Moon's state is universal across symbols
    try:
        lunar_now = moon_eng.reading().to_dict()
    except Exception as e:
        errors.append(f"lunar init failed: {e}")
        lunar_now = {"gate": "PROCEED", "summary": "lunar reading unavailable",
                      "rules_triggered": []}

    # ---------- Stage 1 (parallel, fast) ----------
    def _s1(sym):
        try:
            return esoteric_evaluate(sym)
        except Exception as e:
            errors.append(f"{sym} S1: {e}")
            return None

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_s1, s): s for s in universe}
        for fut in as_completed(futures):
            r = fut.result()
            if r is None:
                continue
            # Apply esoteric direction filter:
            #   • BULLISH lean must have score ≥ esoteric_min
            #   • BEARISH lean must have score ≤ (100 − esoteric_min)
            #   • Both extremes are interesting; NEUTRAL is dropped
            passes = (
                (r.direction == "BULLISH" and r.score >= esoteric_min) or
                (r.direction == "BEARISH" and r.score <= (100 - esoteric_min))
            )
            if passes:
                s1_passed.append(r)
            else:
                rejected_s1.append({"symbol": r.symbol, "esoteric_score": r.score, "direction": r.direction})

    s1_passed.sort(key=lambda r: -abs(r.score - 50))   # most decisive first

    # ---------- Stage 2 (parallel, with OHLCV) ----------
    s2_passed: list[tuple[EsotericReading, TechnicalConfirmation, "object"]] = []

    def _s2(r: EsotericReading):
        try:
            df = get_ohlcv(r.symbol, periods=250)
            t = technical_evaluate(r.symbol, r.direction, df=df)
            return r, t, df
        except Exception as e:
            errors.append(f"{r.symbol} S2: {e}")
            return None

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_s2, r): r.symbol for r in s1_passed}
        for fut in as_completed(futures):
            res = fut.result()
            if res is None:
                continue
            r, t, df = res
            agrees = (not require_agreement) or t.agrees_with_esoteric
            min_ok = t.score >= technical_min or t.score <= (100 - technical_min)
            if agrees and min_ok:
                s2_passed.append((r, t, df))
            else:
                rejected_s2.append({
                    "symbol": r.symbol,
                    "esoteric_dir": r.direction, "esoteric_score": r.score,
                    "technical_dir": t.direction, "technical_score": t.score,
                    "agreement": agrees,
                })

    # Rank survivors by combined edge
    s2_passed.sort(key=lambda x: -(x[0].score + x[1].score) / 2)
    survivors = s2_passed[:max_finalists]

    # ---------- Stage 3 + 4 + Consistency check ----------
    finalists: list[PipelineFinalist] = []
    for r, t, df in survivors:
        # Direction prefers technical when both agree; otherwise esoteric (esoteric is the gate)
        direction = t.direction if t.direction != "SIDEWAYS" else r.direction
        # Synthetic IV estimate: ATR / spot ratio → percent IV ~ ATR%/spot × 16 (annualization rough)
        iv_est = (t.atr / max(t.spot, 1e-6)) * 100 * 16
        # Pull Gann S/R for smart-entry (pullback/breakout triggers, not just spot=entry).
        # If the engine isn't available or symbol lacks data, fall back to None → ATR-based pullback.
        gann_sup, gann_res = None, None
        try:
            from app.engines import gann as gann_eng
            g_res = gann_eng.analyze(t.spot)
            gann_sup = g_res.nearest_support
            gann_res = g_res.nearest_resistance
        except Exception:
            pass
        recent_bars = [
            {"open": float(row["open"]),  "high": float(row["high"]),
              "low":  float(row["low"]),   "close": float(row["close"])}
            for _, row in df.tail(5).iterrows()
        ]
        plan = strategy_eng.select(
            symbol=r.symbol,
            spot=t.spot,
            direction=direction,
            confidence=(r.score + t.score) / 2,
            atr=t.atr,
            iv_pct=iv_est,
            options_bias=direction,
            horizon=horizon,
            capital=capital,
            gann_support=gann_sup,
            gann_resistance=gann_res,
            recent_candles=recent_bars,
        )

        # ---- Stage 3.5: consistency validation ----
        # Re-check astrology + hora + numerology vs the PICKED strategy direction.
        # This catches cases like "OPT_CE_BUY recommended but per-symbol astrology
        # is bearish" or "OPT_PE_BUY in a Jupiter hora" — bugs the aggregate score hides.
        validation = consistency.validate(
            strategy_type=plan.strategy,
            esoteric_components=r.components,
            hora=hora_now,
            astro_market=astro_market_now,
            lunar=lunar_now,
            mode=consistency_mode,
        )

        # Apply the validator's adjustment to the strategy
        original_strategy = plan.strategy
        if validation.adjusted_strategy != plan.strategy:
            # Strategy was downgraded — rebuild a WAIT plan to zero out sizing
            if validation.adjusted_strategy == "WAIT":
                plan = strategy_eng.select(
                    symbol=r.symbol,
                    spot=t.spot,
                    direction="SIDEWAYS",   # forces WAIT path
                    confidence=0,
                    atr=t.atr,
                    iv_pct=iv_est,
                    horizon=horizon,
                    capital=capital,
                )
                # Overwrite the rationale with the validator's reason
                plan.strategy = "WAIT"
                plan.rationale = (
                    f"DOWNGRADED from {original_strategy}. {validation.summary} "
                    f"({validation.severity_counts['HIGH']} HIGH, "
                    f"{validation.severity_counts['MEDIUM']} MEDIUM conflicts)"
                )
                plan.suggested_qty = 0
                plan.capital_allocation_pct = 0.0
                plan.capital_required_inr = 0.0
                plan.expected_max_profit_inr = 0.0
                plan.expected_max_loss_inr = 0.0
                plan.instrument_legs = []

        if attach_accuracy:
            acc = quick_backtest_accuracy(r.symbol, df, threshold=min(60.0, technical_min))
        else:
            acc = {"skipped": True}

        # Final confidence blend:
        #   esoteric 30%, technical 50%, historical accuracy 20%
        hist_factor = 50.0
        if "hit_rate" in acc and acc.get("trades", 0) >= 5:
            hist_factor = acc["hit_rate"]
        final_conf = round(0.30 * r.score + 0.50 * t.score + 0.20 * hist_factor, 2)
        if direction == "BEARISH":
            # bearish direction means low score is the "signal" — convert
            final_conf = round(0.30 * (100 - r.score) + 0.50 * (100 - t.score) + 0.20 * hist_factor, 2)

        # Apply validator's confidence adjustment (negative for warnings)
        final_conf = max(0.0, min(100.0, final_conf + validation.confidence_adjustment))

        # ---- ML ensemble prediction (computed below; blended after) ----
        # Only fires when the user has trained the model via /api/ml/train.
        # If untrained, ml_pred is None and pipeline ignores it (graceful).
        ml_pred = None
        try:
            if ml_eng.is_trained():
                feats = ml_eng.build_features(
                    technical_indicators=t.technical_indicators,
                    engine_scores={
                        "tech": t.score, "smc": 50, "options": 50,
                        "astro": r.components["astrology"]["score"],
                        "gann": r.components["gann"]["score"],
                        "fib": r.components["fibonacci"]["score"],
                        "numerology": r.components["numerology"]["score"],
                    },
                    engine_biases={
                        "tech": t.direction, "smc": t.smc_structure,
                        "astro": r.components["astrology"]["bias"],
                        "gann": r.components["gann"]["bias"],
                        "fib": r.components["fibonacci"]["bias"],
                    },
                    moon_phase=(lunar_now.get("raw") or {}).get("moon_phase") or {"elongation_deg": 0},
                    hora_bias=hora_now.get("bias", "neutral"),
                    is_full_moon=bool(lunar_now.get("is_full_moon")),
                    is_voc=bool(lunar_now.get("is_void_of_course")),
                    is_eclipse=bool(lunar_now.get("eclipse_zone")),
                    mercury_rx=(astro_market_now.get("raw") or {}).get("mercury_retrograde", False),
                )
                ml_pred = ml_eng.predict(feats, symbol=r.symbol)
        except Exception as e:
            logger.debug("ML predict failed for {}: {}", r.symbol, e)

        # ---- Confluence boost ----
        # Build a unified engine dict for the confluence counter (uses bias
        # from each sub-engine, including Stage-1 components).
        engine_biases = {
            "technical":   {"bias": t.direction},
            "smc":         {"bias": t.smc_structure},   # BULLISH/BEARISH/RANGING
            "astrology":   {"bias": r.components["astrology"]["bias"]},
            "gann":        {"bias": r.components["gann"]["bias"]},
            "fibonacci":   {"bias": r.components["fibonacci"]["bias"]},
            "numerology":  {"bias": r.components["numerology"]["bias"]},
        }
        if ml_pred is not None:
            engine_biases["ml"] = {"bias": ml_pred.direction}

        # Weighted-voting weights from journal attribution (cached). Falls back
        # to equal weighting when no engine has enough decided votes yet.
        try:
            from app.services import engine_weights
            _ew = engine_weights.get_weights_with_meta()
            _w, _ws = _ew["weights"], _ew["meta"]["status"]
        except Exception:
            _w, _ws = {}, "ERROR"

        conf_result = confluence_eng.confluence_boost(
            engines=engine_biases,
            intended_direction=direction,
            original_confidence=final_conf,
            weights=_w or None,
            weight_status=_ws,
        )
        final_conf = conf_result.new_confidence

        # ---- ML blend (only if model is trained) ----
        # Final = 0.7 * current + 0.3 * ML calibrated probability (when ML agrees)
        # When ML disagrees with direction → −10 confidence penalty
        if ml_pred is not None:
            if ml_pred.direction == direction:
                final_conf = round(0.7 * final_conf + 0.3 * ml_pred.confidence_pct, 2)
            else:
                final_conf = max(0.0, round(final_conf - 10, 2))

        # ---- Holding-period estimator ----
        holding = confluence_eng.holding_period_estimate(
            entry_price=plan.entry,
            targets=plan.targets,
            atr=t.atr,
            horizon=horizon,
            hora=hora_now,
            upcoming_gann_cycles=r.components["gann"].get("upcoming_cycles"),
        )

        # If downgraded to WAIT, force NEUTRAL signal
        if plan.strategy == "WAIT":
            final_signal = "NEUTRAL"
        else:
            final_signal = _signal_label(final_conf) if direction == "BULLISH" \
                            else (_signal_label(100 - final_conf) if direction == "BEARISH" else "NEUTRAL")

        finalists.append(PipelineFinalist(
            symbol=r.symbol,
            sector=r.sector,
            esoteric={
                "score": r.score,
                "direction": r.direction,
                "components": r.components,
                "reasons": r.reasons,
            },
            technical={
                "score": t.score,
                "direction": t.direction,
                "smc_structure": t.smc_structure,
                "indicators": t.technical_indicators,
                "reasons": t.reasons,
                "agrees_with_esoteric": t.agrees_with_esoteric,
            },
            strategy=plan.to_dict(),
            accuracy=acc,
            final_confidence=final_conf,
            final_signal=final_signal,
            composite_reasons={
                "esoteric": " | ".join(r.reasons[:3]),
                "technical": " | ".join(t.reasons[:3]),
                "strategy": plan.rationale,
                "accuracy": (f"Historical hit-rate {acc.get('hit_rate', 'n/a')}% over {acc.get('trades', 0)} trades"
                              if "hit_rate" in acc else "accuracy skipped"),
                "consistency": validation.summary,
            },
        ))
        # ---- Quality grade (4 tiers) — used by DIAMOND filter and UI ----
        # DIAMOND  : 6/6 confluence + lunar PROCEED + 0 HIGH conflicts + hist hit-rate ≥ 70%
        # GOLD     : 5/6 confluence + lunar PROCEED + 0 HIGH conflicts
        # SILVER   : 4/6 confluence + lunar in (PROCEED, CAUTION) + 0 HIGH conflicts
        # STANDARD : everything else (still surfaced unless diamond_only=true)
        hi_conflicts = validation.severity_counts.get("HIGH", 0)
        aligned = conf_result.aligned_count
        lunar_gate = (lunar_now or {}).get("gate", "PROCEED")
        hist_ok = ("hit_rate" in acc and acc.get("trades", 0) >= 5
                    and acc["hit_rate"] >= 70)

        if aligned >= 6 and hi_conflicts == 0 and lunar_gate == "PROCEED" and hist_ok and plan.strategy != "WAIT":
            quality_grade = "DIAMOND"
        elif aligned >= 5 and hi_conflicts == 0 and lunar_gate == "PROCEED" and plan.strategy != "WAIT":
            quality_grade = "GOLD"
        elif aligned >= 4 and hi_conflicts == 0 and lunar_gate in ("PROCEED", "CAUTION") and plan.strategy != "WAIT":
            quality_grade = "SILVER"
        else:
            quality_grade = "STANDARD"

        # Attach validation to the last appended finalist via dict mutation
        finalists[-1].__dict__["validation"] = validation.to_dict()
        finalists[-1].__dict__["hora"] = hora_now
        finalists[-1].__dict__["lunar"] = lunar_now
        finalists[-1].__dict__["original_strategy"] = original_strategy
        finalists[-1].__dict__["confluence"] = conf_result.to_dict()
        finalists[-1].__dict__["holding_plan"] = holding.to_dict()
        finalists[-1].__dict__["quality_grade"] = quality_grade
        finalists[-1].__dict__["ml"] = ml_pred.to_dict() if ml_pred is not None else None

    # ---- DIAMOND-only filter (post-construction) ----
    # When set, only show the rare top-tier picks. Result: often 0-3 finalists
    # per run, but those that survive have historically high realized hit-rates.
    if diamond_only:
        finalists = [f for f in finalists if f.__dict__.get("quality_grade") == "DIAMOND"]
    if min_backtest_hit_rate > 0:
        finalists = [f for f in finalists
                      if f.accuracy.get("hit_rate", 0) >= min_backtest_hit_rate]

    # Fire alerts (skips silently if ALERTS_ENABLED=false in env)
    finalist_dicts = [f.to_dict() for f in finalists]
    try:
        alert_count = alerts_svc.send_pipeline_finalists(finalist_dicts, horizon=horizon)
        if alert_count:
            logger.info("Dispatched {} Telegram alerts", alert_count)
    except Exception as e:
        logger.warning("alert dispatch failed: {}", e)

    return PipelineRun(
        asof=asof,
        horizon=horizon,
        capital=capital,
        universe_size=len(universe),
        stage1_passed=len(s1_passed),
        stage2_passed=len(s2_passed),
        finalists=finalist_dicts,
        rejected_stage1=rejected_s1[:20],
        rejected_stage2=rejected_s2[:20],
        errors=errors[:10],
        params={
            "esoteric_min": esoteric_min,
            "technical_min": technical_min,
            "require_agreement": require_agreement,
            "max_finalists": max_finalists,
            "parallel": parallel,
            "attach_accuracy": attach_accuracy,
            "consistency_mode": consistency_mode,
            "hora": hora_now,
            "lunar": lunar_now,
            "astro_market_bias": astro_market_now.get("bias", "NEUTRAL"),
        },
    )
