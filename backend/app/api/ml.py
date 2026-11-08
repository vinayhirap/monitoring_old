"""ML scoring endpoints."""
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.engines import (
    technical, smc, gann, fibonacci, astrology, numerology,
    hora as hora_eng, moon as moon_eng, ml,
)
from app.engines import ml_train
from app.services.market_data import get_ohlcv

router = APIRouter()


@router.get("/status", summary="ML model status — trained? when? performance?")
async def status():
    return ml.status()


@router.get("/predict/{symbol}", summary="Run the trained ML ensemble on a single symbol")
async def predict(symbol: str):
    if not ml.is_trained():
        raise HTTPException(409, "ML models not trained yet — POST /api/ml/train first")
    sym = symbol.upper()
    try:
        df = get_ohlcv(sym, periods=250)
        tech = technical.analyze(df)
        smc_res = smc.analyze(df)
        fib = fibonacci.analyze(df)
        g = gann.analyze(tech.indicators["last"])

        try:
            astro_sym = astrology.symbol_astro_match(sym)
            astro_bias = astro_sym["bias"]; astro_score = astro_sym["score"]
        except Exception:
            astro_bias, astro_score = "NEUTRAL", 50
        num = numerology.analyze(sym)
        mp = astrology.moon_phase(datetime.now())
        lunar = moon_eng.reading()
        h = hora_eng.current_hora()
        merc_rx = astrology.mercury_retrograde(datetime.now())

        feats = ml.build_features(
            technical_indicators=tech.indicators,
            engine_scores={
                "tech": tech.score, "smc": smc_res.score, "options": 50,
                "astro": astro_score, "gann": g.score, "fib": fib.score,
                "numerology": num.score,
            },
            engine_biases={
                "tech": tech.bias, "smc": smc_res.market_structure,
                "astro": astro_bias, "gann": g.bias, "fib": fib.bias,
            },
            moon_phase=mp, hora_bias=h.bias,
            is_full_moon=lunar.is_full_moon,
            is_voc=lunar.is_void_of_course,
            is_eclipse=lunar.eclipse_zone,
            mercury_rx=merc_rx,
        )
        pred = ml.predict(feats, symbol=sym)
        if pred is None:
            raise HTTPException(500, "ML predict returned None")
        return pred.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"ml predict failed: {e}")


class TrainRequest(BaseModel):
    symbols: list[str] | None = None
    history_bars: int = 400
    horizon_bars: int = 5
    min_samples: int = 200


@router.post("/train", summary="Train (or retrain) the ML ensemble — slow (~2-5 min)")
async def train(req: TrainRequest, background: BackgroundTasks):
    """Kicks off training. This trains on historical OHLCV bars from the
    backfill table — needs at least ~3 months of bars per symbol.

    Returns 400 with a clear message if there's not enough data.
    """
    # Fast pre-flight check — confirm cache has bars
    try:
        from app.database import SessionLocal
        from app.models.ohlcv_bar import OHLCVBar
        with SessionLocal() as sess:
            n_bars = sess.query(OHLCVBar).count()
        if n_bars < 500:
            raise HTTPException(
                400,
                f"Only {n_bars} OHLCV bars in cache. ML training needs historical "
                f"data first. Run the backfill: POST /api/backfill/run?days_back=730"
            )
    except HTTPException:
        raise
    except Exception:
        pass        # if check itself fails, continue and let trainer report

    try:
        report = ml_train.train(
            symbols=req.symbols,
            history_bars=req.history_bars,
            horizon_bars=req.horizon_bars,
            min_samples=req.min_samples,
        )
        return report
    except RuntimeError as e:
        # Trainer's own "not enough samples" errors
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"training failed: {e}")


@router.get("/feature-importance", summary="Top GBM feature importances")
async def feature_importance():
    s = ml.status()
    if not s["trained"]:
        raise HTTPException(409, "not trained")
    if ml._gbm is None:
        ml.load()
    try:
        inner = getattr(ml._gbm, "estimator", None) or getattr(ml._gbm, "base_estimator", None)
        importance = inner.feature_importances_  # type: ignore[attr-defined]
        rows = sorted(
            [{"feature": ml.FEATURE_NAMES[i], "importance": round(float(importance[i]), 4)}
             for i in range(len(ml.FEATURE_NAMES))],
            key=lambda r: -r["importance"],
        )
        return {"features": rows, "model": "GradientBoostingClassifier"}
    except Exception as e:
        raise HTTPException(500, f"feature importance unavailable: {e}")


@router.get("/calibration-curve", summary="Predicted-prob vs realized-rate (OOS)")
async def calibration_curve():
    s = ml.status()
    if not s["trained"]:
        raise HTTPException(409, "not trained")
    return {"calibration": (s["meta"] or {}).get("calibration_curve", []),
            "trained_at": (s["meta"] or {}).get("trained_at")}
