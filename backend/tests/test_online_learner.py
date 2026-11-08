"""Tests for the online-learning meta-model.

What we test:
  • Feature vector has the right shape and stable schema
  • predict() returns (0..1, bool) on fresh state
  • update() reduces loss on the SAME sample (i.e. learns)
  • Convergence: feeding consistent labels makes the prediction approach the label
  • Warmup gate: is_trustworthy=False before WARMUP_SAMPLES updates
  • Reset wipes state
  • Hyperparameter setter respects bounds

NOT tested here (would require an integration env):
  • Concurrent updates from multiple uvicorn workers — single-process only today
  • Persistence across process restart — would need temp file fixtures
"""
from __future__ import annotations

import os
import tempfile
import pytest


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """Each test gets a fresh learner state file in tmp_path. Avoids tests
    leaking state into each other or into the real disk file."""
    from app.services import online_learner
    state_file = tmp_path / "online_learner_test.json"
    monkeypatch.setattr(online_learner, "STATE_PATH", state_file)
    # Force re-initialisation
    monkeypatch.setattr(online_learner, "_state", None)
    yield online_learner


# ============================================================================
# Feature vector
# ============================================================================

class TestFeatureVector:
    def test_returns_correct_dim(self, isolated_state):
        ol = isolated_state
        feats = ol.build_feature_vector(engines_snapshot={}, regime=None)
        assert feats.shape[0] == ol.N_FEATURES

    def test_missing_engines_default_neutral(self, isolated_state):
        ol = isolated_state
        feats = ol.build_feature_vector(engines_snapshot={}, regime=None)
        # All scores default to 0.5, biases to 0
        # First 8 are scores, indices 8-13 are biases, 14-15 are regime flags
        for i in range(8):
            assert feats[i] == 0.5, f"score idx {i} should default to 0.5"
        for i in range(8, 14):
            assert feats[i] == 0.0, f"bias idx {i} should default to 0"

    def test_bias_encoding(self, isolated_state):
        ol = isolated_state
        snap = {
            "technical": {"bias": "BULLISH", "score": 75},
            "smc":       {"bias": "BEARISH", "score": 35},
            "gann":      {"bias": "NEUTRAL", "score": 50},
        }
        feats = ol.build_feature_vector(engines_snapshot=snap)
        # score_technical = 0.75
        assert feats[0] == pytest.approx(0.75, rel=0.01)
        # bias_technical (idx 8) = 1.0 (BULLISH)
        assert feats[8] == 1.0
        # bias_smc (idx 9) = -1.0 (BEARISH)
        assert feats[9] == -1.0
        # bias_gann (idx 10) = 0.0 (NEUTRAL)
        assert feats[10] == 0.0

    def test_regime_flags(self, isolated_state):
        ol = isolated_state
        f = ol.build_feature_vector(engines_snapshot={}, regime="TRENDING")
        assert f[14] == 1.0    # is_trending
        assert f[15] == 0.0
        f = ol.build_feature_vector(engines_snapshot={}, regime="MEAN_REVERTING")
        assert f[14] == 0.0
        assert f[15] == 1.0


# ============================================================================
# Predict
# ============================================================================

class TestPredict:
    def test_fresh_state_returns_half(self, isolated_state):
        ol = isolated_state
        import numpy as np
        feats = np.zeros(ol.N_FEATURES)    # all zeros → z=0 → sigmoid(0)=0.5
        p, trustworthy = ol.predict(feats)
        assert p == pytest.approx(0.5, abs=0.01)
        assert trustworthy is False    # warmup not complete

    def test_dim_mismatch_returns_half_untrusted(self, isolated_state):
        ol = isolated_state
        import numpy as np
        feats = np.zeros(5)    # wrong dim
        p, trustworthy = ol.predict(feats)
        assert p == 0.5
        assert trustworthy is False


# ============================================================================
# Update + learning
# ============================================================================

class TestUpdate:
    def test_single_update_reduces_loss_on_same_sample(self, isolated_state):
        """Classic SGD invariant — after one update step, loss on the SAME
        sample should decrease."""
        ol = isolated_state
        import numpy as np
        rng = np.random.default_rng(42)
        feats = rng.standard_normal(ol.N_FEATURES)
        # Initial probability
        p_before, _ = ol.predict(feats)
        # Update with label=1
        result = ol.update(feats, won=True)
        assert result["updated"] is True
        # Predict again — should move TOWARD 1
        p_after, _ = ol.predict(feats)
        assert p_after > p_before, f"After update toward 1, prob should increase: {p_before} → {p_after}"

    def test_convergence_consistent_labels(self, isolated_state):
        """If we always say label=1 on the same feature vector, the model
        should eventually predict near 1."""
        ol = isolated_state
        import numpy as np
        rng = np.random.default_rng(123)
        feats = rng.standard_normal(ol.N_FEATURES)
        for _ in range(200):
            ol.update(feats, won=True)
        p, trustworthy = ol.predict(feats)
        assert p > 0.85, f"After 200 wins on same features, expected p>0.85 got {p}"
        assert trustworthy is True

    def test_warmup_gate(self, isolated_state):
        """is_trustworthy=False until WARMUP_SAMPLES updates seen."""
        ol = isolated_state
        import numpy as np
        feats = np.zeros(ol.N_FEATURES)

        # Just below warmup
        for _ in range(ol.WARMUP_SAMPLES - 1):
            ol.update(feats, won=True)
        _, trustworthy = ol.predict(feats)
        assert trustworthy is False

        # One more = at warmup
        ol.update(feats, won=True)
        _, trustworthy = ol.predict(feats)
        assert trustworthy is True


# ============================================================================
# Status, reset, tune
# ============================================================================

class TestAdminOps:
    def test_status_shape(self, isolated_state):
        ol = isolated_state
        s = ol.get_status()
        for key in ("n_samples_seen", "n_wins_seen", "ready", "weights", "bias", "lr", "l2"):
            assert key in s, f"status missing {key!r}"
        assert isinstance(s["weights"], dict)
        assert len(s["weights"]) == ol.N_FEATURES

    def test_reset_wipes_state(self, isolated_state):
        ol = isolated_state
        import numpy as np
        feats = np.ones(ol.N_FEATURES)
        for _ in range(20):
            ol.update(feats, won=True)
        assert ol.get_status()["n_samples_seen"] == 20
        ol.reset()
        assert ol.get_status()["n_samples_seen"] == 0

    def test_tune_clamps_to_bounds(self, isolated_state):
        ol = isolated_state
        r = ol.set_hyperparams(lr=999, l2=-5)
        # lr clamped to ≤1.0, l2 clamped to ≥0.0
        assert r["lr"] == 1.0
        assert r["l2"] == 0.0
