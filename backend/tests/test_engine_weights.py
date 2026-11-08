"""Tests for engine_weights — the bridge between attribution data and the
confluence engine's voting weights.

Critical properties tested:
  • edge_to_weight monotonic — higher edge → higher weight
  • Weight clamped to [WEIGHT_FLOOR, WEIGHT_CEILING] — no engine can have
    weight 0 (would silently zero out a signal) or weight > 2 (would let
    one engine dominate)
  • INSUFFICIENT_DATA engines are NOT in returned weights (caller treats as 1.0)
  • Cache TTL prevents per-request DB hits but force_refresh bypasses it
  • All errors return weights={} so confluence falls back to equal weighting
    rather than crashing the request pipeline
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.services import engine_weights


# ============================================================================
# edge_to_weight — the core mapping
# ============================================================================

class TestEdgeToWeight:
    def test_zero_edge_returns_one(self):
        assert engine_weights.edge_to_weight(0) == 1.0

    def test_positive_edge_increases_weight(self):
        assert engine_weights.edge_to_weight(5) > 1.0
        assert engine_weights.edge_to_weight(10) > engine_weights.edge_to_weight(5)

    def test_negative_edge_decreases_weight(self):
        assert engine_weights.edge_to_weight(-5) < 1.0
        assert engine_weights.edge_to_weight(-10) < engine_weights.edge_to_weight(-5)

    def test_weight_ceiling_2x(self):
        """Even a freakishly high edge can't push weight past the cap."""
        assert engine_weights.edge_to_weight(100) == 2.0
        assert engine_weights.edge_to_weight(50) == 2.0     # 1 + 50*0.05 = 3.5 → clamped

    def test_weight_floor_never_zero(self):
        """An anti-predictive engine still has SOME signal — never zero
        (would silently drop the engine's votes from the count entirely)."""
        assert engine_weights.edge_to_weight(-100) == 0.1
        assert engine_weights.edge_to_weight(-50)  == 0.1

    def test_expected_values_per_design_doc(self):
        """Spot-check the documented design values:
            edge +5  → 1.25
            edge +10 → 1.50
            edge -5  → 0.75
            edge -10 → 0.50
        """
        assert engine_weights.edge_to_weight(5)   == pytest.approx(1.25)
        assert engine_weights.edge_to_weight(10)  == pytest.approx(1.50)
        assert engine_weights.edge_to_weight(-5)  == pytest.approx(0.75)
        assert engine_weights.edge_to_weight(-10) == pytest.approx(0.50)


# ============================================================================
# _compute_weights — reads attribution, returns weights + meta
# ============================================================================

class TestComputeWeights:
    def _mock_attribution(self, engines: list[dict], baseline: float = 0.5,
                           evaluated: int = 50) -> dict:
        return {
            "as_of": "2026-05-26T12:00:00Z",
            "lookback_days":     90,
            "horizon":           None,
            "total_signals":     evaluated + 10,
            "evaluated_signals": evaluated,
            "baseline_hit_rate": baseline,
            "min_samples_threshold": 15,
            "engines":           engines,
        }

    def test_all_engines_data_driven(self):
        engines_payload = [
            {"engine": "technical", "status": "ALPHA",   "edge_pp": 8.0,  "decided_size": 30},
            {"engine": "smc",       "status": "ALPHA",   "edge_pp": 6.0,  "decided_size": 25},
            {"engine": "numerology","status": "NEUTRAL", "edge_pp": 1.0,  "decided_size": 20},
            {"engine": "astrology", "status": "NOISE",   "edge_pp": -7.0, "decided_size": 20},
        ]
        with patch.object(engine_weights, "_compute_weights",
                           wraps=engine_weights._compute_weights):
            with patch("app.services.engine_attribution.attribute_engines",
                        return_value=self._mock_attribution(engines_payload)), \
                 patch("app.database.SessionLocal", return_value=MagicMock(__enter__=lambda s: MagicMock(),
                                                                              __exit__=lambda *a: None)):
                engine_weights.clear_cache()
                out = engine_weights.get_weights_with_meta(force_refresh=True)
                w = out["weights"]
                assert w["technical"]   == pytest.approx(1.40)
                assert w["smc"]         == pytest.approx(1.30)
                assert w["numerology"]  == pytest.approx(1.05)
                assert w["astrology"]   == pytest.approx(0.65)
                assert out["meta"]["status"] == "DATA_DRIVEN"

    def test_insufficient_data_engines_omitted(self):
        engines_payload = [
            {"engine": "technical", "status": "ALPHA", "edge_pp": 8.0, "decided_size": 30},
            {"engine": "gann",      "status": "INSUFFICIENT_DATA", "edge_pp": None, "decided_size": 3},
        ]
        with patch("app.services.engine_attribution.attribute_engines",
                    return_value=self._mock_attribution(engines_payload)), \
             patch("app.database.SessionLocal", return_value=MagicMock(__enter__=lambda s: MagicMock(),
                                                                          __exit__=lambda *a: None)):
            engine_weights.clear_cache()
            out = engine_weights.get_weights_with_meta(force_refresh=True)
            assert "technical" in out["weights"]
            assert "gann" not in out["weights"]      # not in dict → caller uses 1.0
            assert "gann" in out["meta"]["equal_weight_engines"]
            assert out["meta"]["status"] == "MIXED"

    def test_no_engines_have_data_falls_back(self):
        engines_payload = [
            {"engine": "technical", "status": "INSUFFICIENT_DATA", "edge_pp": None, "decided_size": 5},
            {"engine": "smc",       "status": "INSUFFICIENT_DATA", "edge_pp": None, "decided_size": 4},
        ]
        with patch("app.services.engine_attribution.attribute_engines",
                    return_value=self._mock_attribution(engines_payload, evaluated=10)), \
             patch("app.database.SessionLocal", return_value=MagicMock(__enter__=lambda s: MagicMock(),
                                                                          __exit__=lambda *a: None)):
            engine_weights.clear_cache()
            out = engine_weights.get_weights_with_meta(force_refresh=True)
            assert out["weights"] == {}
            assert out["meta"]["status"] == "EQUAL_WEIGHT"

    def test_attribution_service_failure_returns_empty_weights(self):
        """If the journal is unreachable, return empty weights → caller falls
        back to equal weighting. Don't crash the request pipeline."""
        with patch("app.services.engine_attribution.attribute_engines",
                    side_effect=RuntimeError("DB unreachable")):
            engine_weights.clear_cache()
            out = engine_weights.get_weights_with_meta(force_refresh=True)
            assert out["weights"] == {}
            assert out["meta"]["status"] == "ERROR"


# ============================================================================
# Caching
# ============================================================================

class TestCaching:
    def test_cache_returns_same_result_within_ttl(self):
        engine_weights.clear_cache()
        with patch("app.services.engine_attribution.attribute_engines",
                    return_value={"engines": [], "evaluated_signals": 0,
                                   "baseline_hit_rate": 0.5}) as mock_attr, \
             patch("app.database.SessionLocal", return_value=MagicMock(__enter__=lambda s: MagicMock(),
                                                                          __exit__=lambda *a: None)):
            engine_weights.get_weights_with_meta()
            engine_weights.get_weights_with_meta()
            engine_weights.get_weights_with_meta()
            # Three calls → only one attribute_engines call (cache hits)
            assert mock_attr.call_count == 1

    def test_force_refresh_bypasses_cache(self):
        engine_weights.clear_cache()
        with patch("app.services.engine_attribution.attribute_engines",
                    return_value={"engines": [], "evaluated_signals": 0,
                                   "baseline_hit_rate": 0.5}) as mock_attr, \
             patch("app.database.SessionLocal", return_value=MagicMock(__enter__=lambda s: MagicMock(),
                                                                          __exit__=lambda *a: None)):
            engine_weights.get_weights_with_meta()
            engine_weights.get_weights_with_meta(force_refresh=True)
            assert mock_attr.call_count == 2

    def test_clear_cache_works(self):
        engine_weights.clear_cache()
        with patch("app.services.engine_attribution.attribute_engines",
                    return_value={"engines": [], "evaluated_signals": 0,
                                   "baseline_hit_rate": 0.5}) as mock_attr, \
             patch("app.database.SessionLocal", return_value=MagicMock(__enter__=lambda s: MagicMock(),
                                                                          __exit__=lambda *a: None)):
            engine_weights.get_weights_with_meta()
            engine_weights.clear_cache()
            engine_weights.get_weights_with_meta()
            assert mock_attr.call_count == 2


# ============================================================================
# Integration: confluence_boost honors weights
# ============================================================================

class TestConfluenceIntegration:
    def test_equal_weight_path_when_no_weights_given(self):
        """Back-compat: callers that don't pass weights get count-based logic."""
        from app.engines import confluence
        engines = {
            "technical": {"bias": "BULLISH"},
            "smc":       {"bias": "BULLISH"},
            "gann":      {"bias": "BULLISH"},
            "fibonacci": {"bias": "BULLISH"},
            "astrology": {"bias": "BEARISH"},
        }
        result = confluence.confluence_boost(
            engines=engines, intended_direction="BULLISH", original_confidence=60.0,
        )
        # 4 aligned / 5 total → STRONG, +6 boost, minus 5 for astrology contrarian
        assert result.aligned_count == 4
        assert result.grade in ("STRONG", "VERY_STRONG")
        assert result.weights_used == {}    # no weights → empty

    def test_weighted_path_uses_supplied_weights(self):
        from app.engines import confluence
        engines = {
            "technical": {"bias": "BULLISH"},   # weight 1.5 (alpha)
            "smc":       {"bias": "BULLISH"},   # weight 1.3 (alpha)
            "astrology": {"bias": "BEARISH"},   # weight 0.5 (noise)
        }
        weights = {"technical": 1.5, "smc": 1.3, "astrology": 0.5}
        result = confluence.confluence_boost(
            engines=engines, intended_direction="BULLISH",
            original_confidence=60.0, weights=weights, weight_status="DATA_DRIVEN",
        )
        # Weighted: aligned = 1.5 + 1.3 = 2.8; total = 2.8 + 0.5 = 3.3
        # Alignment = 2.8/3.3 = 84.8% → VERY_STRONG/UNANIMOUS bucket
        assert result.weighted_alignment > 0.8
        assert result.grade in ("VERY_STRONG", "UNANIMOUS")
        assert result.weight_status == "DATA_DRIVEN"
        assert result.weights_used["technical"] == 1.5

    def test_noise_engine_dissent_does_not_penalize_when_weighted(self):
        """If a NOISE-flagged engine dissents, its low weight already de-rates
        it — we shouldn't double-penalize."""
        from app.engines import confluence
        engines = {
            "technical": {"bias": "BULLISH"},
            "astrology": {"bias": "BEARISH"},
        }
        weights = {"technical": 1.5, "astrology": 0.3}
        result = confluence.confluence_boost(
            engines=engines, intended_direction="BULLISH",
            original_confidence=60.0, weights=weights, weight_status="DATA_DRIVEN",
        )
        # technical (weight 1.5) aligned, astrology (0.3) contrarian
        # alignment = 1.5 / 1.8 = 83.3%
        # Boost: 12 (VERY_STRONG); astrology has weight < 1.0 → no extra penalty
        assert result.boost >= 0   # should NOT be penalized further
