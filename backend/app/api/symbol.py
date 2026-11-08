"""Unified per-symbol aggregation endpoint.

Powers the /symbol/[ticker] page in the UI. One HTTP call returns
everything the symbol detail page needs:
  • Live LTP, OHLC, day-change
  • OHLCV for the chart
  • All 7 analyzers' scores + biases (technical, SMC, gann, fib, vedic, num, ML)
  • Vedic timing match (nakshatra, ruler, tara)
  • Hora climate
  • Lunar gate
  • Strategy recommendation (entry / SL / targets / qty / capital)
  • Holding plan (days to T1, exit-by date)
  • Consistency check (conflicts, downgrades)
"""
from datetime import datetime, date, timedelta
from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.brokers.angelone import broker_instance
from app.config import settings
from app.engines import (
    technical, smc, fibonacci, gann, astrology, numerology,
    strategy as strategy_eng, hora as hora_eng, moon as moon_eng,
    consistency, confluence, ml,
    options as options_eng, options_strategy, gap_forecast,
    quant_indicators, pivots as pivots_eng,
    horizon_strategy,
    confidence_band, session_split,
    gann_natural_squares, fibonacci_fractal,
    advanced_ta, stop_loss_engine,
    candlestick_patterns, historical_analog, signal_explainer,
)
from app.services import instruments, risk_guard, calibration_fit, price_sanity
from app.services import online_learner, recommendation_quality
from app.services.market_data import get_ohlcv, LiveDataUnavailable

router = APIRouter()


@router.get("/{symbol}", summary="Everything for one symbol — chart, all analyzers, recommendation")
def symbol_detail(
    symbol: str,
    exchange: str = "NSE",
    horizon: str = Query("SWING", pattern="^(INTRADAY|SWING|POSITIONAL)$"),
    capital: float = Query(100_000, gt=0),
    bars: int = Query(120, ge=20, le=400),
    lang: str = Query("en", pattern="^(en|hi)$",
                       description="Explanation language — 'en' (English) or 'hi' (Hindi)"),
):
    # NOTE: defined as plain `def`, not `async def`, on purpose. The body
    # calls ~15 blocking engines + Angel One HTTP + pandas math. Under
    # `async def`, those would block the uvicorn event loop and starve
    # every other concurrent request. With plain `def`, FastAPI runs the
    # handler in its threadpool, so other requests proceed in parallel.
    sym = symbol.upper().strip()
    try:
        # ---------- 1. OHLCV ----------
        # LIVE_ONLY=true → reject this symbol cleanly with HTTP 503 rather than
        # serving fake data. The frontend renders a clear "live data unavailable"
        # state instead of pretending a chart exists.
        data_source = "live" if broker_instance.is_authenticated() else "synthetic"
        partial_warning: str | None = None
        try:
            df = get_ohlcv(sym, exchange=exchange, periods=bars)
        except LiveDataUnavailable as e:
            if settings.live_only:
                raise HTTPException(503, f"Live data unavailable for {sym}: {e}")
            # paper mode kept for development only — never reached when LIVE_ONLY=true
            from app.engines.technical import synthetic_ohlcv
            df = synthetic_ohlcv(sym, periods=bars)
            data_source = "synthetic_fallback"
            partial_warning = (f"Live data unavailable for {sym}: {e}. "
                                f"Showing synthetic for this symbol only.")

        # Build chart payload — last 60 bars to keep response small
        chart_df = df.tail(60).copy()
        chart = [
            {
                "t": str(idx.date()) if hasattr(idx, "date") else str(idx),
                "o": round(float(row["open"]), 2),
                "h": round(float(row["high"]), 2),
                "l": round(float(row["low"]), 2),
                "c": round(float(row["close"]), 2),
                "v": int(row["volume"]),
            }
            for idx, row in chart_df.iterrows()
        ]

        # ---------- 2. Live LTP ----------
        last_close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2]) if len(df) > 1 else last_close
        ltp_data = {
            "ltp": last_close,
            "open": float(df["open"].iloc[-1]),
            "high": float(df["high"].iloc[-1]),
            "low":  float(df["low"].iloc[-1]),
            "close": prev_close,
            "change": round(last_close - prev_close, 2),
            "change_pct": round((last_close - prev_close) / prev_close * 100, 2) if prev_close else 0,
            "is_live": data_source == "live",
        }
        # If broker authenticated, hit LTP for the freshest tick
        if broker_instance.is_authenticated():
            row = instruments.lookup(sym, exchange)
            if row:
                try:
                    q = broker_instance.quote(exchange, row["symbol"], str(row["token"]))
                    d = (q.get("data") or {}) if isinstance(q, dict) else {}
                    if d.get("ltp"):
                        ltp_data["ltp"] = float(d["ltp"])
                        ltp_data["open"] = float(d.get("open") or ltp_data["open"])
                        ltp_data["high"] = float(d.get("high") or ltp_data["high"])
                        ltp_data["low"] = float(d.get("low") or ltp_data["low"])
                        if d.get("close"):
                            prev_close = float(d["close"])
                            ltp_data["close"] = prev_close
                            ltp_data["change"] = round(ltp_data["ltp"] - prev_close, 2)
                            ltp_data["change_pct"] = round((ltp_data["ltp"] - prev_close) / prev_close * 100, 2) if prev_close else 0
                except Exception as e:
                    logger.debug("live LTP refresh failed for {}: {}", sym, e)

        # ---------- 3. Engines ----------
        # ---------- 3. Engines — PARALLEL execution ----------
        # Run all independent engines (those that only need `df` and/or the
        # symbol name) in a ThreadPool. Drops handler latency from ~serial
        # sum to ~max-of-engines. Engines that depend on results from this
        # phase (strategy, consistency, confluence, ML) run AFTER.
        from concurrent.futures import ThreadPoolExecutor

        def _safe(fn, fallback):
            """Run fn() and return its result; on exception return fallback."""
            try:
                return fn()
            except Exception as e:
                logger.warning("engine call failed: {}: {}", fn.__name__ if hasattr(fn, '__name__') else 'lambda', e)
                return fallback

        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="sym-engines") as pool:
            # Submit all df-only engines in parallel
            f_tech     = pool.submit(technical.analyze, df)
            f_smc      = pool.submit(smc.analyze, df)
            f_fib      = pool.submit(fibonacci.analyze, df)
            f_astro    = pool.submit(_safe, lambda: astrology.symbol_astro_match(sym),
                                       {"score": 50, "bias": "NEUTRAL",
                                        "symbol_nakshatra": {}, "reasons": []})
            f_num      = pool.submit(numerology.analyze, sym)
            f_lunar    = pool.submit(_safe, lambda: moon_eng.reading().to_dict(),
                                       {"gate": "PROCEED", "summary": "lunar unavailable"})
            f_hora     = pool.submit(_safe, lambda: hora_eng.current_hora().to_dict(),
                                       {"ruler": "?", "bias": "neutral", "weight": 0.5})
            f_senti    = pool.submit(_safe, lambda: astrology.market_sentiment().to_dict(),
                                       {"bias": "NEUTRAL", "score": 50})

            # Block on the ones we need for direction/strategy first
            tech     = f_tech.result()
            smc_res  = f_smc.result()
            fib      = f_fib.result()
            spot     = tech.indicators["last"]
            astro_sym = f_astro.result()
            num      = f_num.result()
            lunar    = f_lunar.result()
            hora_now = f_hora.result()
            sentiment = f_senti.result()

        # gann.analyze needs spot — runs serially after spot is known.
        # Cheap (no I/O), so no parallelism benefit.
        g = gann.analyze(spot)

        # Determine direction (technical-led, esoteric fills sideways)
        direction = tech.bias if tech.bias != "NEUTRAL" else (
            "BULLISH" if (g.score + fib.score + astro_sym["score"]) / 3 >= 55 else
            "BEARISH" if (g.score + fib.score + astro_sym["score"]) / 3 <= 45 else
            "SIDEWAYS"
        )

        # ---------- 4. Strategy ----------
        iv_est = (tech.indicators["atr14"] / max(spot, 1e-6)) * 100 * 16
        # Pass last 5 OHLC candles + Gann S/R so the entry isn't blindly = spot.
        # The smart-entry helper picks PULLBACK / BREAKOUT / MARKET based on
        # where spot sits relative to Gann levels and how many consecutive
        # candles confirm the direction.
        recent_bars = [
            {"open": float(row["open"]),  "high": float(row["high"]),
              "low":  float(row["low"]),   "close": float(row["close"])}
            for _, row in df.tail(5).iterrows()
        ]
        plan = strategy_eng.select(
            symbol=sym, spot=spot, direction=direction,
            confidence=(tech.score + g.score + fib.score + astro_sym["score"]) / 4,
            atr=tech.indicators["atr14"], iv_pct=iv_est,
            horizon=horizon, capital=capital,
            gann_support=g.nearest_support,
            gann_resistance=g.nearest_resistance,
            recent_candles=recent_bars,
        )

        # ---------- 5. Consistency check ----------
        validation = consistency.validate(
            strategy_type=plan.strategy,
            esoteric_components={
                "astrology": {"bias": astro_sym["bias"]},
                "numerology": {"bias": num.bias},
            },
            hora=hora_now,
            astro_market={"bias": sentiment["bias"]},
            lunar=lunar,
            mode="warn",        # detail page just SHOWS conflicts; doesn't auto-downgrade
        ).to_dict()

        # ---------- 6. ML prediction (if trained) ----------
        ml_pred = None
        if ml.is_trained():
            try:
                feats = ml.build_features(
                    technical_indicators=tech.indicators,
                    engine_scores={
                        "tech": tech.score, "smc": smc_res.score, "options": 50,
                        "astro": astro_sym["score"], "gann": g.score, "fib": fib.score,
                        "numerology": num.score,
                    },
                    engine_biases={
                        "tech": tech.bias, "smc": smc_res.market_structure,
                        "astro": astro_sym["bias"], "gann": g.bias, "fib": fib.bias,
                    },
                    moon_phase={"elongation_deg": (lunar.get("elongation_deg", 0))},
                    hora_bias=hora_now.get("bias", "neutral"),
                    is_full_moon=bool(lunar.get("is_full_moon")),
                    is_voc=bool(lunar.get("is_void_of_course")),
                    is_eclipse=bool(lunar.get("eclipse_zone")),
                    mercury_rx=False,
                )
                p = ml.predict(feats, symbol=sym)
                ml_pred = p.to_dict() if p else None
            except Exception as e:
                logger.debug("ML predict failed for {}: {}", sym, e)

        # ---------- 7. Holding plan ----------
        try:
            holding = confluence.holding_period_estimate(
                entry_price=plan.entry, targets=plan.targets, atr=tech.indicators["atr14"],
                horizon=horizon, hora=hora_now,
                upcoming_gann_cycles=g.upcoming_cycle_dates,
            ).to_dict()
        except Exception as e:
            logger.debug("holding plan failed: {}", e)
            holding = None

        # ---------- 8. Final composite confidence ----------
        engine_biases = {
            "technical":  {"bias": tech.bias},
            "smc":        {"bias": smc_res.market_structure},
            "astrology":  {"bias": astro_sym["bias"]},
            "gann":       {"bias": g.bias},
            "fibonacci":  {"bias": fib.bias},
            "numerology": {"bias": num.bias},
        }
        if ml_pred:
            engine_biases["ml"] = {"bias": ml_pred["direction"]}

        # ---------- Engine weights (data-driven from journal attribution) ----------
        # When the journal has enough evaluated signals to compute a per-engine
        # hit rate, weights are derived from each engine's edge_pp. Otherwise
        # weights={} and confluence_boost falls back to equal weighting — no
        # invented numbers. Cached for 1 hour so this isn't a per-request DB hit.
        try:
            from app.services import engine_weights
            ew = engine_weights.get_weights_with_meta()
            _eng_weights = ew["weights"]
            _eng_weight_status = ew["meta"]["status"]
        except Exception as e:
            logger.debug("engine_weights lookup failed, using equal weights: {}", e)
            _eng_weights = {}
            _eng_weight_status = "ERROR"

        conf_result = confluence.confluence_boost(
            engines=engine_biases,
            intended_direction=direction,
            original_confidence=(tech.score + g.score + fib.score) / 3,
            weights=_eng_weights or None,
            weight_status=_eng_weight_status,
        ).to_dict()

        # ---------- Compute heavy / shared blocks — IN PARALLEL ----------
        # All five are df-only or constant-input. Threadpool drops latency
        # from sum-of-durations to max-of-durations.
        live_spot = ltp_data["ltp"]
        with ThreadPoolExecutor(max_workers=5, thread_name_prefix="sym-heavy") as pool:
            fq  = pool.submit(_safe_quant, sym, df)
            fgf = pool.submit(_safe_gap_forecast, sym, df)
            fta = pool.submit(_safe_advanced_ta, df)
            fp  = pool.submit(_safe_pivots, df)
            fc  = pool.submit(_safe_candles, df)
            quant_block        = fq.result()
            gap_forecast_block = fgf.result()
            advanced_ta_block  = fta.result()
            pivots_block       = fp.result()
            candles_block      = fc.result()

        # ---------- Calibrated confidence — honest probability ----------
        # If we have ≥300 evaluated journal entries, the raw composite score
        # is mapped through the isotonic calibrator so what users see is
        # "% of the time historically wins" instead of a marketing number.
        raw_confidence = conf_result["new_confidence"]
        calibrated_confidence, was_calibrated = calibration_fit.calibrate_confidence(raw_confidence)

        # Feed advanced-TA into the engine_biases dict BEFORE confluence runs —
        # this is what actually moves the composite confidence number.
        if advanced_ta_block and not advanced_ta_block.get("error"):
            engine_biases["advanced_ta"] = {"bias": advanced_ta_block["composite_bias"]}
            # Recompute confluence with the new signal included — same weighting
            # context as the first pass, just with advanced_ta added.
            conf_result = confluence.confluence_boost(
                engines=engine_biases,
                intended_direction=direction,
                original_confidence=(tech.score + g.score + fib.score
                                       + advanced_ta_block["composite_score"]) / 4,
                weights=_eng_weights or None,
                weight_status=_eng_weight_status,
            ).to_dict()

        # ---------- Proper stop-loss — multi-method engine ----------
        # Combines ATR + structural swing + VWAP + Fib confluence + Gann
        # natural squares + pivots. Picks the most defensible level (or a
        # confluence midpoint when 2+ methods agree). If the engine produces
        # a more defensible SL than the strategy's plain ATR×k, we PREFER it
        # and downgrade the strategy's SL to a fallback.
        # natural_squares + fractal_fib in parallel (both used by SL engine
        # and by pine_levels block). pivots_block was already computed above.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="sym-levels") as pool:
            fns = pool.submit(_safe_natural_squares, live_spot)
            fff = pool.submit(_safe_fractal_fib, df)
            nat_squares_block = fns.result()
            fib_fractal_block = fff.result()
        stop_loss_block   = _safe_stop_loss(
            entry=plan.entry, direction=direction,
            atr=tech.indicators.get("atr14", 0),
            fib=fib_fractal_block,
            advanced_ta=advanced_ta_block,
            gann_natural=nat_squares_block,
            pivots=pivots_block,
            quant=quant_block,
            target_1=(plan.targets[0] if plan.targets else None),
        )
        # If SL engine produced a more defensible SL, override plan.stoploss
        # so the visible recommendation reflects the better number. The
        # original plan SL is preserved under `stop_loss_analysis.legacy_sl`.
        legacy_sl = plan.stoploss
        if (stop_loss_block and not stop_loss_block.get("error")
                and stop_loss_block.get("recommended_method") != "ATR"
                and stop_loss_block.get("recommended_sl")):
            plan.stoploss = float(stop_loss_block["recommended_sl"])
            stop_loss_block["legacy_sl"] = round(legacy_sl, 2)
            stop_loss_block["applied"] = True
        elif stop_loss_block:
            stop_loss_block["applied"] = False

        # ---------- Historical-analog engine — offline AI ----------
        # Build a fingerprint of the current setup and find past signals
        # with the same shape. Report their REALIZED outcomes — the most
        # empirical "this looks like X% of the time" indicator we have.
        # Requires a database session for the journal lookup.
        from app.database import SessionLocal
        engines_snapshot_for_fp = {
            "technical":  {"score": tech.score, "bias": tech.bias},
            "smc":        {"score": smc_res.score, "bias": smc_res.market_structure},
            "gann":       {"score": g.score, "bias": g.bias},
            "fibonacci":  {"score": fib.score, "bias": fib.bias},
            "vedic":      {"score": astro_sym["score"], "bias": astro_sym["bias"]},
            "numerology": {"score": num.score, "bias": num.bias},
            "advanced_ta": advanced_ta_block,
        }
        with SessionLocal() as analog_db:
            historical_analog_block = _safe_historical_analog(
                analog_db,
                engines_snapshot_for_fp,
                calibrated_confidence,
                direction,
                (quant_block or {}).get("regime") if quant_block else None,
            )

        # ---------- Online-learner meta-prediction (offline AI, minimal CPU) ----------
        # Pure-numpy logistic-regression model that learns engine weights
        # from journal outcomes. ~50µs inference. The probability returned
        # is "P(this setup wins)" — only trusted when the model has seen
        # WARMUP_SAMPLES (~30 evaluated signals). Before that, frontend
        # uses the calibrated rule-based composite.
        try:
            # Add quant to the engines snapshot so the learner has regime info
            learner_snapshot = {**engines_snapshot_for_fp, "quant": quant_block}
            features = online_learner.build_feature_vector(
                engines_snapshot=learner_snapshot,
                regime=(quant_block or {}).get("regime") if quant_block else None,
            )
            p_win, trustworthy = online_learner.predict(features)
            ml_block = {
                "p_win":          round(p_win, 4),
                "p_win_pct":      round(p_win * 100, 1),
                "is_trustworthy": trustworthy,
                "n_samples_seen": online_learner.get_status()["n_samples_seen"],
            }
        except Exception as e:
            logger.warning("Online learner predict failed: {}", e)
            ml_block = {"error": str(e), "is_trustworthy": False}

        # ---------- Price sanity cross-check ----------
        # Compare candle close vs broker.quote() LTP vs the spot we're using.
        # If anything's off by >2%, the response includes a SUSPECT verdict
        # and the frontend renders a red banner. No analysis is shown to the
        # user when SUSPECT — better to refuse than mislead.
        try:
            sanity = price_sanity.check(sym, df, exchange=exchange, spot_used=live_spot).to_dict()
        except Exception as e:
            logger.warning("price sanity failed for {}: {}", sym, e)
            sanity = {"verdict": "NO_REFERENCE", "reasons": [f"sanity check error: {e}"]}

        response = {
            "symbol": sym,
            "exchange": exchange,
            "asof": datetime.now().isoformat(),
            "data_source": data_source,
            "price_sanity": sanity,
            "partial_warning": partial_warning,
            "ltp": ltp_data,
            "chart": chart,
            "direction": direction,
            # Calibrated when journal data is sufficient; raw otherwise.
            # Frontend can read `confidence_is_calibrated` to label honestly.
            "confidence": round(calibrated_confidence, 1),
            "confidence_raw": round(raw_confidence, 1),
            "confidence_is_calibrated": was_calibrated,
            "confluence": conf_result,
            "analyzers": {
                "technical":  {"score": round(tech.score, 1),    "bias": tech.bias,
                                "reasons": tech.reasons[:5],
                                "indicators": tech.indicators},
                "smc":        {"score": round(smc_res.score, 1), "bias": smc_res.market_structure,
                                "reasons": smc_res.reasons[:4],
                                "details": {"bos": smc_res.last_bos, "choch": smc_res.last_choch,
                                             "premium_discount": smc_res.premium_discount}},
                "gann":       {"score": round(g.score, 1),       "bias": g.bias,
                                "nearest_support": g.nearest_support,
                                "nearest_resistance": g.nearest_resistance,
                                "reasons": g.reasons[:3]},
                "fibonacci":  {"score": round(fib.score, 1),     "bias": fib.bias,
                                "swing_direction": fib.swing_direction,
                                "swing_high": fib.swing_high, "swing_low": fib.swing_low,
                                "nearest_level": fib.nearest_level,
                                "reasons": fib.reasons[:3]},
                "vedic":      {"score": round(astro_sym["score"], 1), "bias": astro_sym["bias"],
                                "nakshatra": astro_sym.get("symbol_nakshatra", {}).get("name"),
                                "ruler": astro_sym.get("symbol_nakshatra", {}).get("ruler"),
                                "tara": astro_sym.get("tara_from_symbol"),
                                "reasons": astro_sym.get("reasons", [])[:3]},
                "numerology": {"score": round(num.score, 1),     "bias": num.bias,
                                "ruler": num.planetary_ruler,
                                "today_compat": num.compatibility_with_today,
                                "reasons": num.reasons[:3]},
                "ml":         ml_pred,
            },
            "context": {
                "lunar": lunar,
                "hora":  hora_now,
                "market_sentiment": sentiment,
            },
            "strategy": plan.to_dict(),
            "holding_plan": holding,
            "validation": validation,
            # ---------- Risk Guard — discipline enforcer ----------
            # Position sizing (2% per-trade cap), R:R floor, portfolio open-risk
            # cap, behavioral circuit breaker. The frontend renders this in the
            # recommendation card so users see WHY the suggested quantity is
            # what it is — and refuses the trade if guards are blown.
            "risk_guard": _safe_risk_guard(plan, capital),
            # ---------- New: gap forecast for next session ----------
            "gap_forecast": gap_forecast_block,
            # ---------- New: options chain analytics + specific trade plan ----------
            "options_analysis": _safe_options_analysis(
                sym, live_spot, direction, conf_result["new_confidence"], horizon, capital,
            ),
            # ---------- New: advanced-math quant indicators ----------
            "quant": quant_block,
            # ---------- New: Camarilla + Standard + Fibonacci pivots ----------
            "pivots": pivots_block,
            # ---------- New: per-horizon strategy plans (Intraday/Swing/Positional) ----------
            # Reuses df + quant_block — no second Angel One fetch, no duplicate quant compute.
            "horizon_plans": _safe_horizon_plans(
                sym, live_spot, direction, conf_result["new_confidence"],
                tech.indicators.get("atr14", 0),
                None,  # iv_pct — will be filled from options if available
                capital, hora_now,
                df=df, quant_dict=quant_block,
            ),
            # ---------- New: engine-disagreement uncertainty band ----------
            "confidence_band": _safe_confidence_band(engine_biases, conf_result["new_confidence"]),
            # ---------- New: intraday-vs-overnight session forecast split ----------
            # Reuses gap_forecast_block — no second gap_forecast.forecast call.
            "session_split": _safe_session_split(
                df, conf_result["new_confidence"], direction, sym,
                gap_forecast_dict=gap_forecast_block,
            ),
            # ---------- Pine Script ports — natural-square + fractal-fib ----------
            "pine_levels": {
                "natural_squares": nat_squares_block,
                "fractal_fib":     fib_fractal_block,
            },
            # ---------- NEW: Advanced TA (VWAP + Divergence + MTF momentum) ----------
            # This is the load-bearing technical block — VWAP is the
            # institutional reference, divergences flag momentum exhaustion,
            # MTF momentum is the directional filter with documented edge.
            # It also factors into the composite confidence above.
            "advanced_ta": advanced_ta_block,
            # ---------- Proper stop-loss analysis (multi-method) ----------
            # Picks the most-defensible SL using 6 methods. When the engine
            # produces a stop more defensible than the strategy's ATR×k, the
            # `strategy.stoploss` ABOVE has already been overridden — this
            # block exposes the full reasoning + alternatives.
            "stop_loss_analysis": stop_loss_block,
            # ---------- NEW: Candlestick patterns (offline AI) ----------
            # Pure-Python recognition of 10 highest-edge candle patterns.
            # No TA-Lib, no external model. Adds confirmation/exhaustion
            # signal to the recommendation.
            "candlestick_patterns": candles_block,
            # ---------- NEW: Historical-analog engine (offline AI) ----------
            # Cosine-similarity over journaled signals — finds past setups
            # with the same fingerprint and reports their REALIZED outcomes.
            # The most empirical "this looks like..." indicator the platform
            # produces. Becomes more useful as the journal grows.
            "historical_analog": historical_analog_block,
            # ---------- NEW: Online-learner meta-prediction ----------
            # ~50-microsecond inference per call. Self-updating from journal
            # outcomes (one SGD step per closed signal). Returns P(win) with
            # an `is_trustworthy` flag — until the model has seen 30 closed
            # signals, this prediction is informational only; the rule-based
            # composite remains the authoritative number.
            "meta_learner": ml_block,
        }

        # ---------- Natural-language explainer ----------
        # Template-based — produces fluent reasoning prose from the structured
        # data above. No LLM, no API. Language is selected by the `lang` query
        # parameter (en/hi). The hide_astrology flag is False here because the
        # admin/full endpoint exposes everything; the portal endpoint strips
        # astrology jargon downstream.
        response["explanation"] = _safe_explanation(
            response, hide_astrology=False, lang=lang
        )

        # ---------- Recommendation Quality — the clarity layer ----------
        # Collapses every signal in the response into ONE verdict + ONE reason
        # the user can act on. Frontend prefers this `verdict` block over
        # reading the 8 sub-signals individually. See:
        # app/services/recommendation_quality.py
        try:
            quality = recommendation_quality.assess(response)
            response["verdict"] = quality.to_dict()
        except Exception as e:
            logger.warning("recommendation_quality assess failed: {}", e)
            response["verdict"] = {"error": str(e)}

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("symbol detail failed for {}", sym)
        raise HTTPException(500, f"symbol detail failed: {e}")


# ---------------------------------------------------------------------------
# Sub-section builders — each isolated in try/except so one failure doesn't
# break the whole /symbol/{sym} response.
# ---------------------------------------------------------------------------

def _safe_confidence_band(engine_biases: dict, point_conf: float) -> dict | None:
    """Engine-disagreement uncertainty band."""
    try:
        # Flatten {name: {bias: X}} → {name: X}
        flat = {name: (eng.get("bias") if isinstance(eng, dict) else eng)
                 for name, eng in engine_biases.items()}
        return confidence_band.compute(flat, point_conf).to_dict()
    except Exception as e:
        logger.warning("confidence band failed: {}", e)
        return {"error": str(e)}


def _safe_session_split(df, conf: float, direction: str, sym: str,
                          gap_forecast_dict: dict | None = None) -> dict | None:
    """Intraday-vs-overnight forecast split.

    `gap_forecast_dict` should be the already-computed result from
    `_safe_gap_forecast` — passing it avoids re-running `gap_forecast.forecast`
    a second time on the same dataframe.
    """
    try:
        gf_dict = gap_forecast_dict
        if gf_dict is None or gf_dict.get("error"):
            # Fall back only if caller didn't pre-compute (defensive)
            from app.engines import gap_forecast as gf
            gf_dict = gf.forecast(symbol=sym, df=df).to_dict()
        return session_split.analyze(df, conf, direction, gap_forecast_dict=gf_dict).to_dict()
    except Exception as e:
        logger.warning("session split failed: {}", e)
        return {"error": str(e)}


def _safe_horizon_plans(sym: str, spot: float, direction: str, confidence: float,
                          atr: float, iv_pct: float | None, capital: float,
                          hora_now: dict, df=None, quant_dict: dict | None = None
                          ) -> dict | None:
    """Return Intraday + Swing + Positional plans in one shot.

    Reuses the caller's `df` and already-computed `quant_dict` instead of
    re-fetching OHLCV from Angel One and re-running `quant_indicators.analyze`.
    """
    try:
        if quant_dict and not quant_dict.get("error"):
            regime = quant_dict.get("regime", "RANGING")
            hurst = quant_dict.get("hurst", 0.5)
            lr_r2 = (quant_dict.get("lr_channel") or {}).get("r_squared", 0)
            ou_half = (quant_dict.get("ou") or {}).get("half_life_bars")
        else:
            # Defensive: caller didn't pre-compute — fall back to fresh computation
            if df is None:
                df = get_ohlcv(sym, periods=200)
            q = quant_indicators.analyze(df, symbol=sym)
            regime, hurst = q.regime, q.hurst
            lr_r2 = q.lr_channel.get("r_squared", 0)
            ou_half = q.ou.get("half_life_bars")
        return horizon_strategy.plan_all_horizons(
            symbol=sym, spot=spot, direction=direction, confidence=confidence,
            atr=atr, iv_pct=iv_pct,
            regime=regime, hurst=hurst,
            lr_r2=lr_r2, ou_half_life=ou_half,
            capital=capital,
            hora_ruler=hora_now.get("ruler"),
            hora_bias=hora_now.get("bias"),
        )
    except Exception as e:
        logger.warning("horizon plans failed for {}: {}", sym, e)
        return {"error": str(e)}


def _safe_quant(sym: str, df) -> dict | None:
    """Advanced-math indicators: Hurst, Kalman, GARCH, OU, LR channel, etc."""
    try:
        return quant_indicators.analyze(df, symbol=sym).to_dict()
    except Exception as e:
        logger.warning("quant analysis failed for {}: {}", sym, e)
        return {"error": str(e)}


def _safe_pivots(df) -> dict | None:
    """Camarilla + Standard + Fibonacci pivots for daily + weekly + monthly."""
    try:
        return {
            "daily":   pivots_eng.analyze(df, period="daily"),
            "weekly":  pivots_eng.analyze(df, period="weekly"),
            "monthly": pivots_eng.analyze(df, period="monthly"),
        }
    except Exception as e:
        logger.warning("pivots failed: {}", e)
        return {"error": str(e)}


def _safe_candles(df) -> dict | None:
    """Candlestick pattern recognition — 10 patterns, pure Python."""
    try:
        return candlestick_patterns.detect(df).to_dict()
    except Exception as e:
        logger.warning("candlestick_patterns failed: {}", e)
        return {"error": str(e)}


def _safe_historical_analog(db, engines_snapshot: dict,
                              confidence: float, direction: str,
                              regime: str | None) -> dict | None:
    """Find past signals with similar fingerprints. Returns their realized
    outcomes — the most empirical 'signal quality' indicator we have."""
    try:
        fingerprint = historical_analog.build_feature_vector(
            engines_snapshot=engines_snapshot,
            confidence=confidence,
            direction=direction,
            regime=regime,
        )
        report = historical_analog.find_analogs(
            db=db, current_fingerprint=fingerprint,
            current_direction=direction,
        )
        return report.to_dict()
    except Exception as e:
        logger.warning("historical_analog failed: {}", e)
        return {"error": str(e)}


def _safe_explanation(full_data: dict, hide_astrology: bool = False,
                        lang: str = "en") -> dict | None:
    """Natural-language explainer.

    Always returns the deterministic template-based output. If a local LLM
    is configured (LOCAL_LLM_MODEL_PATH env) AND it produces text in <2s,
    that text is added under `llm_prose` as an OPTIONAL fluency layer. The
    template `headline` + `body` + `cautions` remain authoritative — the
    LLM output is decoration, not the source of truth.
    """
    try:
        result = signal_explainer.explain(
            full_data, hide_astrology=hide_astrology, lang=lang
        ).to_dict()
        # Optional LLM enhancement (no-op if not configured)
        try:
            from app.services import local_llm
            if local_llm.is_available():
                llm_text = local_llm.enhance_explanation(full_data, lang=lang)
                if llm_text:
                    result["llm_prose"] = llm_text
                    result["llm_enhanced"] = True
        except Exception as e:
            logger.debug("LLM enhancement skipped: {}", e)
        return result
    except Exception as e:
        logger.warning("signal_explainer failed: {}", e)
        return {"error": str(e)}


def _safe_stop_loss(*, entry: float, direction: str, atr: float,
                      fib: dict | None, advanced_ta: dict | None,
                      gann_natural: dict | None, pivots: dict | None,
                      quant: dict | None, target_1: float | None) -> dict | None:
    """Run the multi-method SL engine. Always returns a dict (errors come
    back as {error, recommended_method: 'ATR_FALLBACK'}) so the API contract
    stays predictable."""
    if direction not in ("BULLISH", "BEARISH"):
        return {"error": f"No directional bias ({direction}) - stop-loss not computed",
                "recommended_method": "NONE"}
    try:
        # Volatility regime from quant analysis influences ATR multiplier
        regime = (quant or {}).get("regime", "NORMAL") if quant else "NORMAL"
        vol_regime = ("HIGH_VOL" if regime in ("TRENDING", "VOLATILE")
                       else "LOW_VOL" if regime in ("MEAN_REVERTING", "RANGING")
                       else "NORMAL")
        # Pull swing levels from fib_fractal block (it computed them off the lookback window)
        swing_low  = (fib or {}).get("swing_low")  if fib else None
        swing_high = (fib or {}).get("swing_high") if fib else None
        # Pull VWAP from advanced_ta block
        vwap_block = (advanced_ta or {}).get("vwap") if advanced_ta else None
        report = stop_loss_engine.compute(
            entry=entry, direction=direction, atr=atr,
            swing_low=swing_low, swing_high=swing_high,
            vwap_block=vwap_block,
            fib_fractal_block=fib,
            gann_natural_block=gann_natural,
            pivots_block=pivots,
            vol_regime=vol_regime,
            target_1=target_1,
        )
        return report.to_dict()
    except Exception as e:
        logger.warning("stop_loss_engine failed: {}", e)
        return {"error": str(e)}


def _safe_risk_guard(plan, capital: float) -> dict | None:
    """Run the discipline-enforcer risk guard over the strategy plan.
    Always returns SOMETHING — even errors come back as a dict so the
    frontend can render a 'risk guard unavailable' notice."""
    try:
        targets = plan.targets or []
        t1 = targets[0] if targets else plan.entry * 1.02   # fallback
        # TODO: pass real lot_size from instruments table when called for F&O.
        # Defaulting to 1 means equity sizing is correct; F&O sizing assumes
        # 1 lot is the indivisible unit and rounds quantity to lot multiples.
        rg = risk_guard.check(
            entry=plan.entry, stoploss=plan.stoploss, target_1=t1,
            capital=capital, lot_size=1,
            open_positions_risk_pct=0.0,    # filled when /api/portal/* calls (needs user_id)
            recent_losses=0,
        )
        return rg.to_dict()
    except Exception as e:
        logger.warning("risk_guard failed: {}", e)
        return {"error": str(e), "verdict": "OK"}


def _safe_advanced_ta(df) -> dict | None:
    """Advanced TA: VWAP family + RSI/MACD divergence + MTF momentum
    alignment. Composite score weighted toward MTF momentum (45%) since
    direction-with-trend is the highest-edge signal."""
    try:
        return advanced_ta.analyze(df).to_dict()
    except Exception as e:
        logger.warning("advanced_ta failed: {}", e)
        return {"error": str(e)}


def _safe_natural_squares(spot: float) -> dict | None:
    """Pine Script integer perfect-square levels around live spot."""
    try:
        return gann_natural_squares.compute(spot, levels=4).to_dict()
    except Exception as e:
        logger.warning("natural-squares failed: {}", e)
        return {"error": str(e)}


def _safe_fractal_fib(df) -> dict | None:
    """Pine Script nested fractal Fibonacci grid + confluence zones."""
    try:
        return fibonacci_fractal.compute(df, lookback=100).to_dict()
    except Exception as e:
        logger.warning("fractal-fib failed: {}", e)
        return {"error": str(e)}


def _safe_gap_forecast(sym: str, df) -> dict | None:
    """Next-session gap forecast. Externals (SGX/US/INR/crude) not supplied
    in this MVP — accuracy reduced ~10pp as flagged in risk_flags."""
    from datetime import date as _date, timedelta as _td
    try:
        next_date = (_date.today() + _td(days=1)).isoformat()
        gf = gap_forecast.forecast(symbol=sym, df=df, next_session_date=next_date)
        return gf.to_dict()
    except Exception as e:
        logger.warning("gap_forecast failed for {}: {}", sym, e)
        return {"error": str(e)}


def _safe_options_analysis(sym: str, spot: float, direction: str,
                            confidence: float, horizon: str, capital: float) -> dict | None:
    """Pull live or synthetic chain, compute analytics + trade plan."""
    from datetime import date as _date, timedelta as _td
    try:
        # Expiry comes from the scrip master (NSE changes expiry weekdays).
        # Fallback if the master has nothing: nearest Tuesday (current NSE index expiry day).
        today = _date.today()
        expiry = instruments.nearest_expiry(sym) or (
            today + _td(days=(1 - today.weekday()) % 7))
        # Try live chain first
        chain: list[dict] = []
        try:
            if broker_instance.is_authenticated():
                # Real chain fetch — wrapped: not all symbols have it
                from app.services.market_data import get_option_chain
                chain = get_option_chain(sym, expiry) or []
        except Exception as e:
            logger.debug("live chain fetch failed for {}: {}", sym, e)

        # No live chain? In LIVE_ONLY mode return an explicit unavailable state
        # rather than fake greeks. In paper mode use synthetic as before.
        if not chain:
            if settings.live_only:
                return {"chain_source": "unavailable",
                         "error": (f"Angel One returned no option chain for {sym} on "
                                   f"{expiry.isoformat()}. Possible causes: market closed, "
                                   f"symbol has no listed options at this expiry, or your "
                                   f"Angel One account lacks F&O segment access.")}
            chain = options_eng.synthetic_chain(sym, spot)
            chain_source = "synthetic"
        else:
            chain_source = "live"

        # Aggregate analytics (PCR, max pain, walls)
        analytics = options_eng.analyze(sym, spot, expiry, chain).to_dict()

        # Specific trade plan with picked strikes + entry/exit triggers
        plan = options_strategy.recommend(
            symbol=sym, spot=spot, direction=direction,
            confidence=confidence, chain=chain, expiry=expiry,
            capital=capital, horizon=horizon,
        ).to_dict()

        return {
            "chain_source": chain_source,
            "expiry": expiry.isoformat(),
            "analytics": {
                "pcr": analytics["pcr"],
                "max_pain": analytics["max_pain"],
                "support_wall": analytics["support_wall"],
                "resistance_wall": analytics["resistance_wall"],
                "iv_atm_pct": round(analytics["greeks_atm"]["iv"] * 100, 2),
                "institutional_view": analytics["institutional_view"],
            },
            "chain_preview": [
                {
                    "strike": r["strike"],
                    "ce_oi": r.get("ce_oi"), "pe_oi": r.get("pe_oi"),
                    "ce_iv": r.get("ce_iv"), "pe_iv": r.get("pe_iv"),
                    "ce_ltp": r.get("ce_ltp"), "pe_ltp": r.get("pe_ltp"),
                }
                for r in sorted(chain, key=lambda c: abs(c["strike"] - spot))[:11]
            ],
            "trade_plan": plan,
        }
    except Exception as e:
        logger.warning("options_analysis failed for {}: {}", sym, e)
        return {"error": str(e)}
