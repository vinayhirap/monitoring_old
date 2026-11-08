"""Astro Lab — experiments that isolate the astrology layer so its actual
predictive value can be measured cleanly.

Endpoints:
  GET  /api/astro-lab/only/{symbol}         — pure-astrology recommendation
  GET  /api/astro-lab/measure/{symbol}      — astro-only walk-forward hit rate
  GET  /api/astro-lab/reversal-dates/{symbol}  — Gann time-cycle reversal windows
  GET  /api/astro-lab/per-engine/{symbol}   — side-by-side hit rates per engine
  POST /api/astro-lab/boost-astro           — apply preset weights with astro=50%
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

import numpy as np
import pandas as pd
from loguru import logger

from app.engines import (
    astrology, hora as hora_eng, gann, gann_vibration, gann_master,
    numerology, weight_optimizer, nakshatra_screener, full_confluence,
)
from app.services.market_data import get_ohlcv

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. Astrology-only recommendation
# ---------------------------------------------------------------------------

@router.get("/only/{symbol}",
             summary="PURE astrology call — no technical / SMC / options")
def astro_only(symbol: str):
    """Runs ONLY the astrology layers: Vedic (nakshatra/moon/planets),
    Hora, Gann vibration, numerology. No price action used at all.
    Useful to evaluate astrology in isolation."""
    sym = symbol.upper().strip()
    try:
        astro_match = astrology.symbol_astro_match(sym)
        hora_now = hora_eng.current_hora().to_dict()
        num = numerology.analyze(sym)
        sym_vib = gann_vibration.symbol_vibration(sym).to_dict()
        market_sent = astrology.market_sentiment().to_dict()

        # Compose a pure-astrology score
        scores = []
        biases = []

        scores.append(astro_match["score"]); biases.append(astro_match["bias"])
        scores.append(num.score);             biases.append(num.bias)
        scores.append(market_sent["score"]);  biases.append(market_sent["bias"])

        # Hora is a multiplier — bullish hora amplifies bullish, bearish amplifies bearish
        hora_bias = hora_now.get("bias", "neutral")
        hora_factor = 1.10 if hora_bias == "bullish" else 0.90 if hora_bias == "bearish" else 1.0

        avg_score = (np.mean(scores) * hora_factor) if scores else 50
        avg_score = max(0, min(100, avg_score))

        bulls = sum(1 for b in biases if b == "BULLISH")
        bears = sum(1 for b in biases if b == "BEARISH")
        direction = "BULLISH" if bulls > bears else "BEARISH" if bears > bulls else "NEUTRAL"

        # Find the next benefic hora window
        try:
            buy_win  = hora_eng.next_window("BUY").to_dict()
        except Exception:
            buy_win = None
        try:
            sell_win = hora_eng.next_window("SELL").to_dict()
        except Exception:
            sell_win = None

        return {
            "symbol": sym,
            "asof": datetime.now().isoformat(),
            "pure_astrology": {
                "score": round(avg_score, 2),
                "direction": direction,
                "hora_factor": hora_factor,
            },
            "components": {
                "symbol_astro_match": astro_match,
                "hora": hora_now,
                "market_sentiment": market_sent,
                "numerology": {
                    "score": num.score, "bias": num.bias,
                    "ruler": num.planetary_ruler,
                    "reasons": num.reasons[:3],
                },
                "symbol_vibration": sym_vib,
            },
            "timing": {
                "best_buy_window":  buy_win,
                "best_sell_window": sell_win,
            },
            "disclaimer": (
                "PURE astrology mode — no price-action data used. This is "
                "deliberately isolated for measurement only. Do NOT trade on "
                "this alone. The /symbol/{sym} endpoint blends astrology with "
                "70% measurable layers — use that for actual decisions."
            ),
        }
    except Exception as e:
        raise HTTPException(500, f"astro_only failed: {e}")


# ---------------------------------------------------------------------------
# 2. Astrology-only walk-forward measurement
# ---------------------------------------------------------------------------

@router.get("/measure/{symbol}",
             summary="Measure pure-astrology hit rate on historical bars")
def measure_astro(symbol: str,
                         lookback_bars: int = Query(120, ge=30, le=400)):
    """Walk-forward measurement of astrology's STANDALONE accuracy.
    For each historical day, looks at the day's planetary climate, then
    checks what the market actually did the next day. Returns hit rate.
    """
    sym = symbol.upper().strip()
    try:
        df = get_ohlcv(sym, periods=lookback_bars + 30)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {sym}")
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        closes = df["close"].astype(float).values
        # Use the index as the date series
        dates = df.index
        n = len(df)
        start = max(30, n - lookback_bars)

        predictions = []
        for i in range(start, n - 1):
            try:
                bar_date = pd.Timestamp(dates[i]).to_pydatetime()
                # Get astro climate for that historical day
                sent = astrology.market_sentiment(bar_date)
                astro_bias = sent.bias
                if astro_bias == "NEUTRAL":
                    continue
                realized_up = closes[i + 1] > closes[i]
                predicted_up = (astro_bias == "BULLISH")
                predictions.append({
                    "date": str(bar_date.date()),
                    "astro_bias": astro_bias,
                    "astro_score": round(sent.score, 1),
                    "realized_up": realized_up,
                    "correct": predicted_up == realized_up,
                    "pnl_pct": round((closes[i + 1] - closes[i]) / closes[i] * 100, 3),
                })
            except Exception:
                continue

        if not predictions:
            return {"symbol": sym, "n_predictions": 0,
                     "error": "No directional astro predictions in window"}

        n_pred = len(predictions)
        n_corr = sum(1 for p in predictions if p["correct"])
        hit_rate = n_corr / n_pred
        # Defensive: when all predictions are correct (or all wrong), the
        # empty-list np.mean returns NaN which can't be JSON-serialised.
        # That's the bug that surfaced as a 500 in the UI.
        correct_pnls = [abs(p["pnl_pct"]) for p in predictions if p["correct"]]
        wrong_pnls   = [abs(p["pnl_pct"]) for p in predictions if not p["correct"]]
        avg_pnl_when_right = float(np.mean(correct_pnls)) if correct_pnls else 0.0
        avg_pnl_when_wrong = float(np.mean(wrong_pnls))   if wrong_pnls   else 0.0

        verdict = ("STRONG_EVIDENCE_FOR" if hit_rate > 0.58 else
                    "WEAK_EVIDENCE_FOR" if hit_rate > 0.52 else
                    "NO_EDGE" if hit_rate > 0.48 else
                    "EVIDENCE_AGAINST")

        return {
            "symbol": sym,
            "n_predictions": n_pred,
            "n_correct": n_corr,
            "hit_rate_pct": round(hit_rate * 100, 2),
            "edge_vs_random_pp": round((hit_rate - 0.5) * 100, 2),
            "avg_pnl_pct_when_right": round(avg_pnl_when_right, 3),
            "avg_pnl_pct_when_wrong": round(avg_pnl_when_wrong, 3),
            "verdict": verdict,
            "interpretation": (
                f"Astrology alone called direction correctly on {n_corr}/{n_pred} bars "
                f"({hit_rate*100:.1f}%). Random would be 50%. " +
                ("Astrology has measurable edge on this symbol."
                 if hit_rate > 0.55 else
                 "Astrology is statistically indistinguishable from random on this symbol."
                 if hit_rate > 0.48 else
                 "Astrology is WORSE than random — using it inverts your edge.")
            ),
            "sample": predictions[-20:],   # last 20 for inspection
        }
    except HTTPException:
        raise
    except Exception as e:
        # Surface the actual error class + message so the UI shows something
        # useful instead of "Internal Server Error". The traceback still goes
        # to the backend log via loguru's default handler.
        from loguru import logger
        logger.exception("astro measurement crashed for {}", sym)
        raise HTTPException(500, f"astro measurement failed: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 3. Per-engine side-by-side hit rates
# ---------------------------------------------------------------------------

@router.get("/per-engine/{symbol}",
             summary="Side-by-side measurement of each engine vs astrology")
def per_engine(symbol: str,
                      lookback_bars: int = Query(150, ge=50, le=400)):
    sym = symbol.upper().strip()
    try:
        df = get_ohlcv(sym, periods=lookback_bars + 70)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {sym}")
        report = weight_optimizer.optimize_for_symbol(df, sym, lookback_bars=lookback_bars)
        rates = report.engine_hit_rates

        # Also measure astrology separately
        astro_res = measure_astro(symbol=sym, lookback_bars=lookback_bars)
        if "hit_rate_pct" in astro_res:
            rates.append({
                "engine": "astrology",
                "hit_rate": astro_res["hit_rate_pct"] / 100,
                "edge_vs_random": (astro_res["hit_rate_pct"] - 50) / 100,
                "n_predictions": astro_res["n_predictions"],
                "confidence": "MEDIUM" if astro_res["n_predictions"] > 50 else "LOW",
            })

        rates.sort(key=lambda r: -r["hit_rate"])
        return {
            "symbol": sym,
            "lookback_bars": lookback_bars,
            "engine_hit_rates_sorted": rates,
            "verdict": (
                "Engines sorted by measured hit-rate. Anything below 50% is "
                "worse than random — keeping it in the weight blend HURTS the system."
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"per-engine failed: {e}")


# ---------------------------------------------------------------------------
# 4. Gann time-cycle reversal-date planner
# ---------------------------------------------------------------------------

@router.get("/reversal-dates/{symbol}",
             summary="Next 30 days — flagged reversal windows per Gann time cycles + vibration harmonics")
def reversal_dates(symbol: str,
                          horizon_days: int = Query(30, ge=7, le=180)):
    sym = symbol.upper().strip()
    try:
        df = get_ohlcv(sym, periods=200)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {sym}")
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        # Find the most recent significant swing point
        highs = df["high"].astype(float)
        lows = df["low"].astype(float)
        last_high_idx = highs.tail(100).idxmax()
        last_low_idx  = lows.tail(100).idxmin()
        last_high = float(highs.loc[last_high_idx])
        last_low  = float(lows.loc[last_low_idx])
        last_high_date = pd.Timestamp(last_high_idx).to_pydatetime().date()
        last_low_date  = pd.Timestamp(last_low_idx).to_pydatetime().date()

        # Gann time cycles from both anchor points
        from datetime import date as _date
        today = _date.today()
        cycles = gann.time_cycles(last_high_date)
        low_cycles = gann.time_cycles(last_low_date)

        # Filter to forward window
        all_dates: list[dict] = []
        for c in cycles:
            proj = _date.fromisoformat(c["projected_date"])
            days_ahead = (proj - today).days
            if 0 <= days_ahead <= horizon_days:
                all_dates.append({
                    "date": c["projected_date"],
                    "days_ahead": days_ahead,
                    "type": "reversal_from_high",
                    "anchor_price": last_high,
                    "anchor_date": last_high_date.isoformat(),
                    "cycle_days": c["cycle_days"],
                    "significance": c["significance"],
                    "watch_for": "Potential top fail / reversal lower",
                })
        for c in low_cycles:
            proj = _date.fromisoformat(c["projected_date"])
            days_ahead = (proj - today).days
            if 0 <= days_ahead <= horizon_days:
                all_dates.append({
                    "date": c["projected_date"],
                    "days_ahead": days_ahead,
                    "type": "reversal_from_low",
                    "anchor_price": last_low,
                    "anchor_date": last_low_date.isoformat(),
                    "cycle_days": c["cycle_days"],
                    "significance": c["significance"],
                    "watch_for": "Potential bottom hold / reversal higher",
                })

        # Also pull vibration harmonic-return dates
        vib_dates = gann_vibration.next_vibration_dates(sym, horizon_days=horizon_days)
        for v in vib_dates:
            all_dates.append({
                "date": v["date"],
                "days_ahead": (_date.fromisoformat(v["date"]) - today).days,
                "type": "vibration_harmonic",
                "anchor_price": None,
                "anchor_date": None,
                "cycle_days": None,
                "significance": f"{v['planet']} reaches {v['harmonic_deg']}° harmonic to symbol vibration",
                "watch_for": "Reversal / acceleration zone — pair with technical confirmation",
            })

        all_dates.sort(key=lambda d: d["days_ahead"])

        return {
            "symbol": sym,
            "today": today.isoformat(),
            "horizon_days": horizon_days,
            "anchors": {
                "recent_high": {"price": last_high, "date": last_high_date.isoformat()},
                "recent_low":  {"price": last_low,  "date": last_low_date.isoformat()},
            },
            "reversal_dates": all_dates,
            "note": (
                "These are STATISTICAL reversal-watch dates based on Gann time "
                "cycles + planetary harmonic returns. They do NOT predict "
                "direction — only flag a higher probability of trend change "
                "in that window. ALWAYS pair with technical confirmation "
                "(candlestick reversal, RSI divergence, BoS) before acting."
            ),
            "disclaimer": "Astrology + Gann timing is folklore-grade evidence. Use as ONE input.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"reversal_dates failed: {e}")


# ---------------------------------------------------------------------------
# 5. Nakshatra screener — find stocks aligned with today's Moon
# ---------------------------------------------------------------------------

@router.get("/nakshatra-screener",
             summary="Find F&O stocks aligned with today's Moon nakshatra + technical+Gann confluence")
def nakshatra_screen(
    direction: str = Query("BOTH", pattern="^(BULLISH|BEARISH|BOTH)$"),
    top_n: int = Query(15, ge=5, le=50),
    only_aligned: bool = Query(True,
        description="If True, only consider symbols with favourable tara distance from today's Moon nakshatra"),
):
    """Reverse-lookup: which stocks have a *symbol nakshatra* that's
    favourably positioned vs TODAY'S Moon nakshatra? Then filtered by
    technical + Gann composite. Returns top-N with full math breakdown.
    """
    try:
        return nakshatra_screener.screen_universe(
            direction=direction, top_n=top_n, only_aligned=only_aligned,
        )
    except Exception as e:
        raise HTTPException(500, f"nakshatra screen failed: {e}")


# ---------------------------------------------------------------------------
# 6. Full-confluence analysis — single symbol, every layer, explicit math
# ---------------------------------------------------------------------------

@router.get("/full-confluence/{symbol}",
             summary="One symbol, every engine, all mathematical formulas exposed")
def full_confluence_endpoint(symbol: str, periods: int = Query(150, ge=50, le=400)):
    try:
        df = get_ohlcv(symbol.upper(), periods=periods)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {symbol}")
        report = full_confluence.full_analysis(symbol.upper(), df)
        return report.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"full confluence failed: {e}")


# ---------------------------------------------------------------------------
# 7. Boost-astro preset (experiment helper)
# ---------------------------------------------------------------------------

@router.post("/boost-astro",
              summary="Apply preset: astrology weighted at 50% — for experimental purposes")
def boost_astro(astro_pct: float = Query(0.50, ge=0.0, le=0.80,
                                                  description="Astrology weight 0..0.80")):
    """Set astrology to a custom weight (default 50%). Used to test what
    happens when astrology dominates."""
    remaining = 1 - astro_pct
    new_weights = {
        "technical":  remaining * 0.40,
        "smc":        remaining * 0.25,
        "options":    remaining * 0.20,
        "astro":      astro_pct,
        "gann":       remaining * 0.10,
        "numerology": remaining * 0.05,
    }
    # normalize
    total = sum(new_weights.values())
    new_weights = {k: round(v / total, 4) for k, v in new_weights.items()}
    weight_optimizer.save_weights(new_weights, source=f"boost-astro-{int(astro_pct*100)}pct")
    return {
        "applied": True,
        "astrology_weight": astro_pct,
        "weights": new_weights,
        "next_step": (
            "Now run calibration: GET /api/calibration/quick/NIFTY — "
            "compare Brier score and hit rate vs baseline. If they get worse, "
            "astrology dominance hurts the system. If they improve, astro "
            "carries genuine signal."
        ),
    }
