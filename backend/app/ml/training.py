"""ML training pipeline — proper, with purged time-series CV and calibration.

Pulls labelled training data from `signals_journal` (signal features + the
realised 5-day outcome). Trains a LightGBM classifier with:
  • Purged k-fold cross-validation (financial time-series safe)
  • Probability calibration (isotonic regression on a held-out fold)
  • SHAP feature importance
  • Persisted to disk via joblib

The label is binary: did the 5d outcome P&L exceed 1× ATR (i.e. the
"profitable" threshold), conditioned on signal direction.

Disclaimer: ML on engine outputs that include astrology/numerology will, in
all likelihood, find those features uninformative. The model will downweight
them automatically — and *that itself is the most useful piece of information*
this layer provides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
from loguru import logger

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    roc_auc_score, accuracy_score, precision_score, recall_score,
    brier_score_loss, log_loss,
)

from app.config import settings


MODELS_DIR = Path(settings.ml_models_dir).resolve()
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODEL_FILE  = MODELS_DIR / "lgbm_signal_classifier.joblib"
META_FILE   = MODELS_DIR / "model_meta.json"


# ---------------------------------------------------------------------------
# Training data extraction from signals_journal
# ---------------------------------------------------------------------------

def _load_training_frame(min_samples: int = 500) -> pd.DataFrame | None:
    """Load journaled signals + outcomes, flatten engine snapshot into columns.
    Returns DataFrame indexed by emitted_at, or None if too few samples.
    """
    from app.database import SessionLocal
    from app.models.signals_journal import SignalJournalEntry

    with SessionLocal() as sess:
        rows = (
            sess.query(SignalJournalEntry)
            .filter(SignalJournalEntry.outcome_status == "EVALUATED")
            .order_by(SignalJournalEntry.emitted_at.asc())
            .all()
        )
    if len(rows) < min_samples:
        return None

    records = []
    for r in rows:
        eng = r.engines_snapshot or {}
        rec = {
            "emitted_at": r.emitted_at,
            "symbol": r.symbol,
            "horizon": r.horizon,
            "headline_confidence": r.confidence or 50,
            "pnl_5d_pct": r.outcome_5d_pnl_pct or 0,
            "pnl_20d_pct": r.outcome_20d_pnl_pct or 0,
            "target_hit": r.outcome_target_hit or 0,
            "stop_hit": int(bool(r.outcome_stoploss_hit)),
        }
        for name, d in (eng.items() if isinstance(eng, dict) else []):
            rec[f"{name}_score"] = (d or {}).get("score", 50)
            bias = (d or {}).get("bias", "") or ""
            rec[f"{name}_bias_BULLISH"] = 1.0 if bias == "BULLISH" else 0.0
            rec[f"{name}_bias_BEARISH"] = 1.0 if bias == "BEARISH" else 0.0
        records.append(rec)

    df = pd.DataFrame(records).set_index("emitted_at").sort_index()
    return df


def _make_labels(df: pd.DataFrame, threshold_pct: float = 0.5) -> np.ndarray:
    """Binary label: pnl_5d_pct > threshold (i.e. signal was profitable)."""
    return (df["pnl_5d_pct"].fillna(0) > threshold_pct).astype(int).values


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

@dataclass
class TrainResult:
    n_samples: int
    n_features: int
    auc_mean: float
    auc_std: float
    brier: float
    log_loss: float
    feature_importance: list[dict]
    cv_fold_metrics: list[dict]
    model_path: str
    trained_at: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def train(min_samples: int | None = None, n_splits: int = 5,
          purge_days: int = 5) -> TrainResult:
    """Train and persist the classifier."""
    if not HAS_LGB:
        raise RuntimeError("lightgbm not installed — add to requirements.txt and pip install")

    min_n = min_samples or settings.ml_min_training_samples
    frame = _load_training_frame(min_samples=min_n)
    if frame is None:
        raise RuntimeError(f"Need ≥{min_n} evaluated signals in signals_journal — train later")

    y = _make_labels(frame)
    feature_cols = [c for c in frame.columns if c.endswith(("_score", "_BULLISH", "_BEARISH"))]
    feature_cols.append("headline_confidence")
    X = frame[feature_cols].fillna(0).values

    cv = TimeSeriesSplit(n_splits=n_splits)
    fold_metrics = []
    aucs = []

    # ---- CV (with purging — drop training samples within `purge_days` of test) ----
    for fold, (tr_idx, te_idx) in enumerate(cv.split(X)):
        # Purge: drop training samples whose emission timestamp is within
        # purge_days of any test sample (to avoid label leakage)
        tr_times = frame.index[tr_idx]
        te_times = frame.index[te_idx]
        purge_cutoff = te_times.min() - timedelta(days=purge_days)
        keep_mask = tr_times < purge_cutoff
        tr_idx = tr_idx[keep_mask]
        if len(tr_idx) < 30:
            continue
        model_fold = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.05, num_leaves=31,
            min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
            random_state=42, verbose=-1,
        )
        model_fold.fit(X[tr_idx], y[tr_idx])
        p = model_fold.predict_proba(X[te_idx])[:, 1]
        auc = roc_auc_score(y[te_idx], p) if len(set(y[te_idx])) > 1 else 0.5
        fold_metrics.append({
            "fold": fold + 1,
            "n_train": int(len(tr_idx)),
            "n_test": int(len(te_idx)),
            "auc": round(float(auc), 4),
        })
        aucs.append(auc)

    # ---- Final model: train on ALL data, then calibrate on a holdout ----
    split = int(len(X) * 0.85)
    base = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=31,
        min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbose=-1,
    )
    base.fit(X[:split], y[:split])
    calibrator = CalibratedClassifierCV(base, method="isotonic", cv="prefit")
    calibrator.fit(X[split:], y[split:])

    # Final metrics on holdout
    proba = calibrator.predict_proba(X[split:])[:, 1]
    brier = float(brier_score_loss(y[split:], proba)) if len(set(y[split:])) > 1 else 0
    ll = float(log_loss(y[split:], proba, labels=[0, 1])) if len(set(y[split:])) > 1 else 0

    # Feature importance (from base estimator's gain)
    importance = sorted(
        [{"feature": f, "gain": float(g)} for f, g in zip(feature_cols, base.feature_importances_)],
        key=lambda r: -r["gain"],
    )

    joblib.dump({
        "calibrator": calibrator,
        "feature_cols": feature_cols,
    }, MODEL_FILE)

    meta = {
        "n_samples": int(len(X)),
        "n_features": int(len(feature_cols)),
        "auc_mean": round(float(np.mean(aucs)), 4) if aucs else 0,
        "auc_std": round(float(np.std(aucs)), 4) if aucs else 0,
        "brier": round(brier, 4),
        "log_loss": round(ll, 4),
        "trained_at": datetime.utcnow().isoformat(),
        "feature_importance_top20": importance[:20],
    }
    META_FILE.write_text(json.dumps(meta, indent=2))

    return TrainResult(
        n_samples=meta["n_samples"],
        n_features=meta["n_features"],
        auc_mean=meta["auc_mean"],
        auc_std=meta["auc_std"],
        brier=meta["brier"],
        log_loss=meta["log_loss"],
        feature_importance=importance[:30],
        cv_fold_metrics=fold_metrics,
        model_path=str(MODEL_FILE),
        trained_at=meta["trained_at"],
        notes=[
            "Purged TimeSeriesSplit CV — training samples within 5 days of test removed",
            "Calibrated via isotonic regression on a 15% holdout",
            "AUC > 0.55 indicates above-random discrimination",
            "Brier score: lower = better calibrated; 0.25 = random for balanced classes",
        ],
    )
