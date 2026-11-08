"""Professional ML pipeline endpoints — train, predict, explain."""
from datetime import datetime
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.ml import training, inference, features as feature_eng
from app.services.market_data import get_ohlcv
from app.engines import decision

router = APIRouter()


@router.post("/train", summary="Train the LightGBM classifier on the journaled signals (requires ≥500 evaluated)")
def train(min_samples: int | None = Query(None, ge=100, le=100000)):
    # Fail fast if journal is empty — no point spinning up LightGBM for 0 samples
    try:
        from app.database import SessionLocal
        from app.models.signals_journal import SignalJournalEntry
        with SessionLocal() as sess:
            n_evaluated = (sess.query(SignalJournalEntry)
                            .filter(SignalJournalEntry.outcome_status == "EVALUATED")
                            .count())
        required = min_samples or 500
        if n_evaluated < required:
            raise HTTPException(
                400,
                f"Not enough evaluated journal entries to train (have {n_evaluated}, need {required}). "
                f"Set up the journal cron and let it accumulate signals for 60-90 days "
                f"before training the ML model. Until then, training cannot proceed."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"could not check journal: {e}")

    try:
        result = training.train(min_samples=min_samples)
        return result.to_dict()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"training failed: {e}")


@router.get("/meta", summary="Last training metadata + feature importance")
def meta():
    if not training.META_FILE.exists():
        return {"trained": False, "reason": "Run POST /api/ml/train first"}
    return {"trained": True, **json.loads(Path(training.META_FILE).read_text())}


@router.get("/predict/{symbol}", summary="Calibrated probability of profitable 5d outcome")
def predict(symbol: str):
    try:
        df = get_ohlcv(symbol, periods=120)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {symbol}")
        sig = decision.aggregate(symbol=symbol, df=df, horizon="SWING")
        feats = feature_eng.build(df, decision_output=sig)
        return {
            "symbol": symbol,
            "asof": datetime.utcnow().isoformat(),
            "headline_signal": sig.get("signal"),
            "headline_confidence": sig.get("confidence"),
            "ml": inference.predict(feats),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"ML predict failed: {e}")


@router.get("/explain/{symbol}", summary="SHAP feature contributions for this symbol's prediction")
def explain(symbol: str, top_n: int = Query(10, ge=3, le=30)):
    try:
        df = get_ohlcv(symbol, periods=120)
        if df is None or df.empty:
            raise HTTPException(404, f"No OHLCV for {symbol}")
        sig = decision.aggregate(symbol=symbol, df=df, horizon="SWING")
        feats = feature_eng.build(df, decision_output=sig)
        return {"symbol": symbol, **inference.explain(feats, top_n=top_n)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"SHAP explain failed: {e}")
