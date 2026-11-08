"""Online learning meta-model — extreme-CPU-minimal "AI" layer.

Why this is the right shape of AI for the platform:

The existing engine scores (technical, advanced_ta, gann, fib, vedic, etc.)
are weighted by hand-tuned constants in confluence.py. As journal data
accumulates, we can ASK THE DATA what weights actually correlate with
winning outcomes. But running batch ML on every request burns CPU; running
a real LLM burns 100x more.

Online logistic regression solves this:
  • Updates in ~10 microseconds when a signal closes (per-sample SGD step)
  • Inference in ~50 microseconds (16-float dot product + sigmoid)
  • ~200 bytes of state (a single weight vector)
  • Zero external dependencies — pure NumPy
  • No GPU, no API, no model files to download
  • Interpretable — you can inspect which engines have positive coefficients
  • Self-correcting — if an engine's predictive value drops, its weight shrinks

This is exactly what "AI on a Raspberry Pi" looks like in production for
predictive scoring problems.

How it works:

  Feature vector x = [normalized engine scores] ∈ R^16
  Weight vector w  ∈ R^16, learned online
  Probability     p = sigmoid(w · x + b)
  Loss            log loss against {0=lost, 1=won}
  Update rule     w_t+1 = w_t - η * (p - y) * x  (one SGD step per closed signal)

Persistence:
  The weight vector is serialised to a small JSON file on disk after each
  update batch, then re-loaded on app startup. That's it. No database
  schema change, no migration, no Redis. ~1KB on disk.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from app.config import settings


# Feature schema — must stay stable; new engines are APPENDED (never inserted
# in the middle, never removed) so previously-trained weights still apply.
FEATURE_KEYS = [
    "score_technical",
    "score_smc",
    "score_gann",
    "score_fibonacci",
    "score_vedic",
    "score_numerology",
    "score_advanced_ta",
    "score_quant",
    "bias_technical",       # encoded as {-1, 0, +1}
    "bias_smc",
    "bias_gann",
    "bias_fibonacci",
    "bias_vedic",
    "bias_advanced_ta",
    "is_trending",          # 1 if regime in (TRENDING, VOLATILE)
    "is_meanrev",           # 1 if regime in (MEAN_REVERTING, RANGING)
]
N_FEATURES = len(FEATURE_KEYS)


# Hyper-parameters — sane defaults; tune with /api/admin/online-learner/tune
DEFAULT_LR = 0.05               # learning rate — small enough to not over-react
DEFAULT_L2 = 0.001              # L2 regularization (keeps weights bounded)
WARMUP_SAMPLES = 30             # don't trust predictions until N updates seen
STATE_PATH = Path(
    getattr(settings, "online_learner_state_path", None)
    or "data/online_learner.json"
)


@dataclass
class LearnerState:
    """Serializable model state. ~200 bytes on disk."""
    weights: list[float] = field(default_factory=lambda: [0.0] * N_FEATURES)
    bias:    float = 0.0
    n_samples_seen: int = 0
    n_wins_seen:    int = 0
    last_updated:   float = 0.0      # unix timestamp
    lr:    float = DEFAULT_LR
    l2:    float = DEFAULT_L2
    version: int = 1


# ----- Module-level singleton state -----
_lock  = threading.Lock()
_state: Optional[LearnerState] = None


# =============================================================================
# Helpers
# =============================================================================

def _sigmoid(z: float) -> float:
    # Numerically stable sigmoid
    if z >= 0:
        ez = np.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = np.exp(z)
    return ez / (1.0 + ez)


def _bias_to_num(bias: str | None) -> float:
    if bias == "BULLISH": return 1.0
    if bias == "BEARISH": return -1.0
    return 0.0


def _engine_score(engines_snapshot: dict, name: str) -> float:
    """Pull engine score (0-100) → normalised 0-1. Returns 0.5 if missing."""
    v = engines_snapshot.get(name, {})
    if isinstance(v, dict):
        score = v.get("score")
        if score is not None:
            try:
                return float(score) / 100.0
            except (TypeError, ValueError):
                pass
    return 0.5


def _engine_bias(engines_snapshot: dict, name: str) -> float:
    v = engines_snapshot.get(name, {})
    if isinstance(v, dict):
        return _bias_to_num(v.get("bias"))
    return 0.0


def build_feature_vector(*, engines_snapshot: dict,
                          regime: str | None = None) -> np.ndarray:
    """Construct a 16-D feature vector from an engines snapshot. Missing
    engines default to neutral (0.5 score, 0 bias) — so the model degrades
    gracefully when an engine fails on a particular symbol."""
    ata = engines_snapshot.get("advanced_ta") or {}
    if isinstance(ata, dict):
        ata_score = float(ata.get("composite_score", 50)) / 100.0
        ata_bias  = _bias_to_num(ata.get("composite_bias"))
    else:
        ata_score, ata_bias = 0.5, 0.0

    quant_score = 0.5
    quant_block = engines_snapshot.get("quant")
    if isinstance(quant_block, dict) and not quant_block.get("error"):
        # Map Hurst (0-1) to "trendiness" — H>0.5 is trending
        h = quant_block.get("hurst")
        if h is not None:
            try:
                quant_score = float(h)
            except (TypeError, ValueError):
                pass

    regime = (regime or "").upper() if regime else ""
    return np.array([
        _engine_score(engines_snapshot, "technical"),
        _engine_score(engines_snapshot, "smc"),
        _engine_score(engines_snapshot, "gann"),
        _engine_score(engines_snapshot, "fibonacci"),
        _engine_score(engines_snapshot, "vedic"),
        _engine_score(engines_snapshot, "numerology"),
        ata_score,
        quant_score,
        _engine_bias(engines_snapshot, "technical"),
        _engine_bias(engines_snapshot, "smc"),
        _engine_bias(engines_snapshot, "gann"),
        _engine_bias(engines_snapshot, "fibonacci"),
        _engine_bias(engines_snapshot, "vedic"),
        ata_bias,
        1.0 if regime in ("TRENDING", "VOLATILE") else 0.0,
        1.0 if regime in ("MEAN_REVERTING", "RANGING") else 0.0,
    ], dtype=np.float64)


# =============================================================================
# State persistence
# =============================================================================

def _load_state() -> LearnerState:
    """Load state from disk, or initialise fresh."""
    global _state
    if _state is not None:
        return _state
    with _lock:
        if _state is not None:
            return _state
        try:
            if STATE_PATH.exists():
                data = json.loads(STATE_PATH.read_text())
                _state = LearnerState(**data)
                logger.info("Online learner loaded: n_samples={}, win_rate={:.2%}",
                              _state.n_samples_seen,
                              (_state.n_wins_seen / _state.n_samples_seen)
                                if _state.n_samples_seen else 0)
            else:
                _state = LearnerState()
                logger.info("Online learner initialised fresh (no prior state file)")
        except Exception as e:
            logger.warning("Online learner load failed ({}) — starting fresh", e)
            _state = LearnerState()
        return _state


def _save_state() -> None:
    """Atomic write — write to a tmp file, then rename."""
    if _state is None:
        return
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_state.__dict__))
        tmp.replace(STATE_PATH)
    except Exception as e:
        logger.warning("Online learner save failed: {}", e)


# =============================================================================
# Public API
# =============================================================================

def predict(features: np.ndarray) -> tuple[float, bool]:
    """Predict P(win | features). Returns (probability, is_trustworthy).

    `is_trustworthy=False` when the model hasn't seen enough samples
    (n_samples < WARMUP_SAMPLES) — callers should ignore the probability
    in that state and fall back to the rule-based composite.
    """
    state = _load_state()
    if features.shape[0] != N_FEATURES:
        return 0.5, False
    z = float(np.dot(state.weights, features) + state.bias)
    p = _sigmoid(z)
    trustworthy = state.n_samples_seen >= WARMUP_SAMPLES
    return p, trustworthy


def update(features: np.ndarray, won: bool) -> dict:
    """Single SGD step. Call this when a journaled signal's outcome is known.

    Update rule (L2-regularised logistic regression):
      gradient_w = (p - y) * x + l2 * w
      gradient_b = (p - y)
      w_new = w_old - lr * gradient_w
      b_new = b_old - lr * gradient_b

    Idempotency caveat: the caller is responsible for not calling update()
    twice for the same signal. The outcome_tracker uses a `learner_updated`
    flag on each journal row to enforce this.
    """
    if features.shape[0] != N_FEATURES:
        logger.warning("Online learner: feature dim mismatch ({} vs {})",
                         features.shape[0], N_FEATURES)
        return {"updated": False, "reason": "feature_dim_mismatch"}

    state = _load_state()
    with _lock:
        y = 1.0 if won else 0.0
        weights = np.asarray(state.weights, dtype=np.float64)
        z = float(np.dot(weights, features) + state.bias)
        p = _sigmoid(z)
        error = p - y

        grad_w = error * features + state.l2 * weights
        grad_b = error

        weights = weights - state.lr * grad_w
        state.bias = state.bias - state.lr * grad_b
        state.weights = weights.tolist()
        state.n_samples_seen += 1
        if won:
            state.n_wins_seen += 1
        state.last_updated = time.time()

        # Persist periodically (every 10 updates) to balance latency vs durability
        if state.n_samples_seen % 10 == 0:
            _save_state()

    return {
        "updated":   True,
        "n_samples": state.n_samples_seen,
        "predicted_pre": round(p, 4),
        "actual": int(y),
        "loss": round(-(y * np.log(max(p, 1e-12)) + (1 - y) * np.log(max(1 - p, 1e-12))), 4),
    }


def get_status() -> dict:
    """Diagnostic snapshot for /api/admin/online-learner/status."""
    state = _load_state()
    return {
        "n_samples_seen": state.n_samples_seen,
        "n_wins_seen":    state.n_wins_seen,
        "in_sample_win_rate": round(state.n_wins_seen / max(state.n_samples_seen, 1), 4),
        "warmup_remaining": max(0, WARMUP_SAMPLES - state.n_samples_seen),
        "ready":            state.n_samples_seen >= WARMUP_SAMPLES,
        "weights":          dict(zip(FEATURE_KEYS, [round(w, 4) for w in state.weights])),
        "bias":             round(state.bias, 4),
        "lr":               state.lr,
        "l2":               state.l2,
        "last_updated":     state.last_updated,
        "state_path":       str(STATE_PATH),
    }


def reset() -> dict:
    """Wipe the model and start fresh. Used when:
      • engine schema changes (new engines added)
      • the model has clearly diverged (test set hit rate falls below baseline)
      • after a corporate-action storm causes a bunch of stale-data updates
    """
    global _state
    with _lock:
        _state = LearnerState()
        _save_state()
    return {"reset": True, "n_samples_seen": 0}


def set_hyperparams(*, lr: float | None = None, l2: float | None = None) -> dict:
    """Tune the learning rate / L2 regularisation. Persisted in the state file."""
    state = _load_state()
    with _lock:
        if lr is not None:
            state.lr = max(0.0001, min(1.0, lr))
        if l2 is not None:
            state.l2 = max(0.0, min(1.0, l2))
        _save_state()
    return {"lr": state.lr, "l2": state.l2}
