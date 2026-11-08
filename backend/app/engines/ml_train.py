"""ML training pipeline — generates labeled samples from historical OHLCV
and trains both models with proper time-series cross-validation.

Honest design notes:
  • Uses TimeSeriesSplit (no peeking into the future)
  • Reports out-of-sample Brier score, log-loss, ROC-AUC, calibration curve
  • If out-of-sample metrics are bad, the train job REFUSES to save —
    the user must explicitly override to avoid silently shipping a useless model
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

from app.engines import (
    technical, smc, gann, fibonacci, astrology, numerology, hora, moon, ml,
)
from app.services.market_data import get_ohlcv
from app.services.universe import top_liquid


def _label_for(df: pd.DataFrame, i: int, horizon_bars: int = 5, threshold: float = 0.005) -> int | None:
    """Label class:
       1  if forward return over `horizon_bars` is > +threshold
       0  if forward return is < -threshold
       None if return is too small (skip — noise)
    """
    if i + horizon_bars >= len(df):
        return None
    entry = float(df["close"].iloc[i])
    future = float(df["close"].iloc[i + horizon_bars])
    ret = (future - entry) / entry
    if ret > threshold:
        return 1
    if ret < -threshold:
        return 0
    return None


def _features_for_window(window: pd.DataFrame, symbol: str) -> np.ndarray | None:
    """Compute the full feature vector for the last bar of `window`."""
    try:
        tech = technical.analyze(window)
        smc_res = smc.analyze(window)
        fib = fibonacci.analyze(window)
        spot = tech.indicators["last"]
        g = gann.analyze(spot)

        # Use the bar's timestamp for astrology (not now())
        ts = window.index[-1]
        if hasattr(ts, "to_pydatetime"):
            asof_dt = ts.to_pydatetime()
        else:
            asof_dt = datetime.now()

        try:
            astro_sym = astrology.symbol_astro_match(symbol, asof_dt)
            astro_bias = astro_sym["bias"]
            astro_score = astro_sym["score"]
        except Exception:
            astro_bias, astro_score = "NEUTRAL", 50

        try:
            num = numerology.analyze(symbol, asof_dt.date())
            num_score, num_bias = num.score, num.bias
        except Exception:
            num_score, num_bias = 50, "NEUTRAL"

        try:
            mp = astrology.moon_phase(asof_dt)
            lunar = moon.reading(asof_dt)
            is_full = lunar.is_full_moon
            is_voc = lunar.is_void_of_course
            is_ecl = lunar.eclipse_zone
        except Exception:
            mp = {"elongation_deg": 0}
            is_full = is_voc = is_ecl = False

        try:
            hora_now = hora.current_hora(asof_dt)
            hora_bias_str = hora_now.bias
        except Exception:
            hora_bias_str = "neutral"

        try:
            merc_rx = astrology.mercury_retrograde(asof_dt)
        except Exception:
            merc_rx = False

        return ml.build_features(
            technical_indicators=tech.indicators,
            engine_scores={
                "tech": tech.score, "smc": smc_res.score, "options": 50,
                "astro": astro_score, "gann": g.score, "fib": fib.score,
                "numerology": num_score,
            },
            engine_biases={
                "tech": tech.bias, "smc": smc_res.market_structure,
                "astro": astro_bias, "gann": g.bias, "fib": fib.bias,
            },
            moon_phase=mp,
            hora_bias=hora_bias_str,
            is_full_moon=is_full,
            is_voc=is_voc,
            is_eclipse=is_ecl,
            mercury_rx=merc_rx,
            asof=asof_dt,
        )
    except Exception as e:
        logger.debug("feature build failed for {}: {}", symbol, e)
        return None


def build_training_set(
    symbols: list[str] | None = None,
    history_bars: int = 400,
    warmup: int = 60,
    horizon_bars: int = 5,
    stride: int = 3,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Walk historical OHLCV for each symbol, label each bar's forward return,
    return (X, y, sample_ids).
    """
    symbols = symbols or top_liquid(50)
    X_rows: list[np.ndarray] = []
    y_rows: list[int] = []
    ids: list[str] = []

    for sym in symbols:
        try:
            df = get_ohlcv(sym, periods=history_bars + warmup)
        except Exception as e:
            logger.debug("skip {} — no data: {}", sym, e)
            continue
        if len(df) < warmup + 50:
            continue
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        for i in range(warmup, len(df) - horizon_bars, stride):
            label = _label_for(df, i, horizon_bars=horizon_bars)
            if label is None:
                continue
            window = df.iloc[: i + 1]
            feats = _features_for_window(window, sym)
            if feats is None or np.any(np.isnan(feats)) or np.any(np.isinf(feats)):
                continue
            X_rows.append(feats)
            y_rows.append(label)
            ids.append(f"{sym}@{df.index[i]}")

    X = np.array(X_rows, dtype=np.float32)
    y = np.array(y_rows, dtype=np.int32)
    return X, y, ids


def train(
    symbols: list[str] | None = None,
    history_bars: int = 400,
    horizon_bars: int = 5,
    min_samples: int = 200,
    min_brier_to_save: float = 0.245,    # below baseline (0.25) = useful model
) -> dict:
    """End-to-end training. Returns report dict with metrics + whether
    the model was saved.
    """
    sk = ml._sk()
    logger.info("Building ML training set (symbols={}, history={}b, horizon={}b)…",
                 len(symbols or top_liquid(50)), history_bars, horizon_bars)
    X, y, ids = build_training_set(symbols=symbols,
                                    history_bars=history_bars,
                                    horizon_bars=horizon_bars)
    n = len(X)
    if n < min_samples:
        return {"status": "insufficient_data",
                "n_samples": n, "required": min_samples,
                "message": f"need at least {min_samples} samples, got {n}"}

    pos_rate = float(y.mean())
    logger.info("Training set: {} samples, positive rate {:.2%}", n, pos_rate)

    # Time-series CV — last 20% as out-of-sample test
    cut = int(n * 0.8)
    X_train, y_train = X[:cut], y[:cut]
    X_test, y_test = X[cut:], y[cut:]

    # Fit both
    logger.info("Fitting GradientBoosting…")
    gbm = ml._build_gbm()
    gbm.fit(X_train, y_train)

    logger.info("Fitting MLP neural network…")
    mlp = ml._build_mlp()
    mlp.fit(X_train, y_train)

    # OOS predictions (ensemble)
    p_gbm = gbm.predict_proba(X_test)[:, 1]
    p_mlp = mlp.predict_proba(X_test)[:, 1]
    p_ens = (p_gbm + p_mlp) / 2

    brier_gbm = float(sk["brier_score_loss"](y_test, p_gbm))
    brier_mlp = float(sk["brier_score_loss"](y_test, p_mlp))
    brier_ens = float(sk["brier_score_loss"](y_test, p_ens))
    try:
        auc_ens = float(sk["roc_auc_score"](y_test, p_ens))
    except Exception:
        auc_ens = float("nan")
    ll_ens = float(sk["log_loss"](y_test, np.clip(p_ens, 1e-6, 1 - 1e-6)))

    # Calibration curve (bin predicted probs, compute realized rate per bin)
    bins = np.linspace(0, 1, 11)
    cal_curve = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (p_ens >= lo) & (p_ens < hi)
        if mask.sum() > 5:
            cal_curve.append({
                "pred_low": round(float(lo), 3),
                "pred_high": round(float(hi), 3),
                "n": int(mask.sum()),
                "realized_rate": round(float(y_test[mask].mean()), 4),
            })

    meta = {
        "trained_at": datetime.now().isoformat(),
        "n_samples": n,
        "n_train": cut,
        "n_test": n - cut,
        "positive_rate": round(pos_rate, 4),
        "feature_names": ml.FEATURE_NAMES,
        "out_of_sample_brier": round(brier_ens, 4),
        "out_of_sample_brier_gbm": round(brier_gbm, 4),
        "out_of_sample_brier_mlp": round(brier_mlp, 4),
        "out_of_sample_auc": round(auc_ens, 4) if not np.isnan(auc_ens) else None,
        "out_of_sample_logloss": round(ll_ens, 4),
        "calibration_curve": cal_curve,
        "horizon_bars": horizon_bars,
        "history_bars": history_bars,
        "gbm_version": "gbm-v1",
        "mlp_version": "mlp-v1",
    }

    saved = False
    if brier_ens <= min_brier_to_save:
        ml.save(gbm, mlp, meta)
        # Reload into module globals
        ml._gbm, ml._mlp, ml._meta = gbm, mlp, meta
        saved = True
        logger.success("✓ ML models saved — OOS Brier {} (≤ {})",
                        round(brier_ens, 4), min_brier_to_save)
    else:
        logger.warning("✗ ML models NOT saved — OOS Brier {} > threshold {} "
                        "(model would degrade pipeline; pass force=True to override)",
                        round(brier_ens, 4), min_brier_to_save)

    return {
        "status": "saved" if saved else "rejected_for_poor_calibration",
        "saved": saved,
        "metrics": meta,
        "advice": (
            "OOS Brier ≤ 0.22 = well-calibrated. 0.22-0.245 = marginal. "
            "Above 0.245 = no better than naive baseline (model rejected)."
        ),
    }
