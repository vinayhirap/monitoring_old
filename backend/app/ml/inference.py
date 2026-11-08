"""ML inference + SHAP explanation."""
from __future__ import annotations

from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from loguru import logger

from app.ml.training import MODEL_FILE


_MODEL_CACHE: dict | None = None


def _load():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        if not MODEL_FILE.exists():
            return None
        _MODEL_CACHE = joblib.load(MODEL_FILE)
    return _MODEL_CACHE


def predict(features: dict) -> dict:
    """Return calibrated probability of profitable 5d outcome.
    `features` should be the dict from app.ml.features.build().
    """
    bundle = _load()
    if bundle is None:
        return {
            "available": False,
            "reason": "Model not trained yet — POST /api/ml/train after journal has ≥500 evaluated signals",
        }
    cols = bundle["feature_cols"]
    cal  = bundle["calibrator"]
    x = np.array([[features.get(c, 0) for c in cols]], dtype=float)
    proba = float(cal.predict_proba(x)[0, 1])
    return {
        "available": True,
        "prob_profitable_5d": round(proba, 4),
        "label": "FAVOURABLE" if proba > 0.6 else "NEUTRAL" if proba > 0.4 else "UNFAVOURABLE",
        "model_path": str(MODEL_FILE),
    }


def explain(features: dict, top_n: int = 10) -> dict:
    """SHAP explanation — which features drove this particular prediction."""
    bundle = _load()
    if bundle is None:
        return {"available": False, "reason": "Model not trained yet"}
    try:
        import shap
    except ImportError:
        return {"available": False, "reason": "shap not installed"}
    cols = bundle["feature_cols"]
    cal  = bundle["calibrator"]
    base = cal.estimator if hasattr(cal, "estimator") else cal.base_estimator
    x = np.array([[features.get(c, 0) for c in cols]], dtype=float)
    try:
        explainer = shap.TreeExplainer(base)
        sv = explainer.shap_values(x)
        # LightGBM binary classifier returns shape (n_samples, n_features) for class 1
        shap_vals = sv[1][0] if isinstance(sv, list) else sv[0]
        contribs = sorted(
            [{"feature": c, "value": float(x[0][i]), "shap_contribution": float(shap_vals[i])}
             for i, c in enumerate(cols)],
            key=lambda r: -abs(r["shap_contribution"]),
        )[:top_n]
        return {"available": True, "top_contributions": contribs}
    except Exception as e:
        return {"available": False, "reason": f"SHAP failed: {e}"}
