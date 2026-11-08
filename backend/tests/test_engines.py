"""Engine golden-output tests.

Why these exist: the composite confidence score depends on ~17 engines.
One untested refactor that silently breaks an engine's output type
(e.g. returns int where a float was expected) corrupts every downstream
calibration. These tests are the safety net.

For each engine we verify three invariants:
  1. analyze() runs without exception on a normal dataset
  2. analyze() returns the expected dataclass shape
  3. score is in [0, 100] and bias is one of the known labels
  4. analyze() doesn't crash on edge cases (flat data, too few bars)

We deliberately do NOT assert specific score values — those are
sensitive to engine tuning and would create false-positive failures.
We assert SHAPE and INVARIANTS, not specific outputs.
"""
from __future__ import annotations

import math
import pytest


VALID_BIAS = {"BULLISH", "BEARISH", "NEUTRAL"}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _assert_score_invariant(score: float, label: str = ""):
    """Score must be a finite number in [0, 100]."""
    assert score is not None, f"{label} score is None"
    assert isinstance(score, (int, float)), f"{label} score is not numeric: {type(score)}"
    assert not math.isnan(score), f"{label} score is NaN"
    assert 0 <= score <= 100, f"{label} score out of range: {score}"


def _assert_bias_invariant(bias: str, label: str = ""):
    assert bias in VALID_BIAS, f"{label} bias unknown: {bias!r}"


# ============================================================================
# Technical analysis engine
# ============================================================================

class TestTechnical:
    def test_runs_on_normal_data(self, synthetic_ohlcv):
        from app.engines import technical
        result = technical.analyze(synthetic_ohlcv)
        _assert_score_invariant(result.score, "technical")
        _assert_bias_invariant(result.bias, "technical")
        assert "atr14" in result.indicators
        assert "last" in result.indicators

    def test_handles_flat_data(self, flat_ohlcv):
        from app.engines import technical
        # Should not crash, may return NEUTRAL
        result = technical.analyze(flat_ohlcv)
        _assert_bias_invariant(result.bias)


# ============================================================================
# Advanced TA (VWAP + divergence + MTF momentum)
# ============================================================================

class TestAdvancedTa:
    def test_runs_on_normal_data(self, synthetic_ohlcv):
        from app.engines import advanced_ta
        result = advanced_ta.analyze(synthetic_ohlcv)
        _assert_score_invariant(result.composite_score, "advanced_ta")
        _assert_bias_invariant(result.composite_bias, "advanced_ta")
        assert 0 <= result.confluence_count <= 3

    def test_vwap_subcomponent(self, synthetic_ohlcv):
        from app.engines.advanced_ta import vwap_analysis
        v = vwap_analysis(synthetic_ohlcv)
        _assert_score_invariant(v.score, "vwap")
        _assert_bias_invariant(v.bias, "vwap")
        # Bands must respect ordering
        assert v.lower_2sigma <= v.lower_1sigma <= v.vwap <= v.upper_1sigma <= v.upper_2sigma

    def test_trending_data_gives_bullish_mtf(self, trending_ohlcv):
        """In a strong uptrend, MTF momentum should say BULLISH."""
        from app.engines.advanced_ta import mtf_momentum
        m = mtf_momentum(trending_ohlcv)
        # Strong uptrend should produce positive long-TF momentum
        assert m.long_tf_momentum > 0

    def test_crash_data_gives_bearish_mtf(self, crash_ohlcv):
        from app.engines.advanced_ta import mtf_momentum
        m = mtf_momentum(crash_ohlcv)
        assert m.long_tf_momentum < 0

    def test_handles_tiny_data(self, tiny_ohlcv):
        """Too few bars should NOT crash."""
        from app.engines import advanced_ta
        result = advanced_ta.analyze(tiny_ohlcv)
        # No assertion on values — just no crash
        assert result is not None


# ============================================================================
# Gann engines
# ============================================================================

class TestGannNaturalSquares:
    def test_basic(self):
        from app.engines.gann_natural_squares import compute
        # Spot of 23792: base_n = 154, zero = 23716
        r = compute(spot=23792.0, levels=3)
        assert r.base_n == 154
        assert r.zero_level == 154 ** 2
        assert len(r.upper_levels) == 3
        assert len(r.lower_levels) >= 1
        # All upper level prices must be > spot
        for lvl in r.upper_levels:
            assert lvl["price"] > 23792.0

    def test_small_spot_no_duplicates(self):
        """Regression test for the duplicate-lower-level bug we fixed."""
        from app.engines.gann_natural_squares import compute
        r = compute(spot=5.0, levels=4)
        # All lower levels must have unique n values
        ns = [lvl["n"] for lvl in r.lower_levels]
        assert len(ns) == len(set(ns)), f"Duplicate ns in lower levels: {ns}"

    def test_invalid_spot(self):
        from app.engines.gann_natural_squares import compute
        r = compute(spot=0, levels=4)
        assert r.upper_levels == []


class TestFibonacciFractal:
    def test_runs(self, synthetic_ohlcv):
        from app.engines import fibonacci_fractal
        r = fibonacci_fractal.compute(synthetic_ohlcv, lookback=100)
        # Must produce levels of each category
        assert r.swing_high > r.swing_low
        assert len(r.levels) > 15    # 5 primary + 2 endpoints + 8 ext + 35 nested ≈ 50
        # Confluence zones must be sorted by distance from spot
        if len(r.confluence_zones) > 1:
            distances = [abs(z["distance_pct_from_spot"]) for z in r.confluence_zones]
            assert distances == sorted(distances)


# ============================================================================
# Risk Guard — discipline enforcer
# ============================================================================

class TestRiskGuard:
    def test_normal_setup_ok(self):
        from app.services.risk_guard import check
        # Reasonable setup: 1% SL distance, 2:1 RR, ₹1L capital
        rg = check(entry=100, stoploss=99, target_1=102,
                    capital=100_000, lot_size=1)
        assert rg.verdict == "OK"
        assert rg.suggested_quantity > 0
        # Risk should be ≤ 2% of capital
        assert rg.risk_pct_of_capital <= 2.0
        # R:R should be 2.0
        assert rg.risk_reward_ratio == 2.0

    def test_excessive_risk_blocked(self):
        from app.services.risk_guard import check
        # SL 20% away — even one share blows 2% cap on small capital
        rg = check(entry=10000, stoploss=8000, target_1=11000,
                    capital=10_000, lot_size=1)
        assert rg.verdict == "BLOCK"

    def test_bad_rr_downgraded(self):
        from app.services.risk_guard import check
        # SL 1% away, target only 1% away — R:R = 1.0, below 1.2 floor
        rg = check(entry=100, stoploss=99, target_1=101,
                    capital=100_000, lot_size=1)
        assert rg.verdict == "DOWNGRADE_WAIT"

    def test_loss_circuit_breaker(self):
        from app.services.risk_guard import check, LOSS_CIRCUIT_THRESHOLD
        rg = check(entry=100, stoploss=99, target_1=102,
                    capital=100_000, lot_size=1,
                    recent_losses=LOSS_CIRCUIT_THRESHOLD)
        assert rg.verdict == "BLOCK"
        assert rg.in_circuit_breaker

    def test_portfolio_cap_respected(self):
        from app.services.risk_guard import check
        # Already at 5% open risk → only 1% room for new position
        rg = check(entry=100, stoploss=99, target_1=102,
                    capital=100_000, lot_size=1,
                    open_positions_risk_pct=5.0)
        # Should downsize, not block, with room remaining
        assert rg.verdict in ("OK", "DOWNGRADE_WAIT")
        assert rg.risk_pct_of_capital <= 1.0

    def test_invalid_inputs_handled(self):
        from app.services.risk_guard import check
        rg = check(entry=0, stoploss=0, target_1=0,
                    capital=0, lot_size=1)
        assert rg.verdict == "BLOCK"


# ============================================================================
# Calibration fit — isotonic regression
# ============================================================================

class TestCalibrationFit:
    def test_pav_monotonic(self):
        """PAV output must be monotonically non-decreasing."""
        from app.services.calibration_fit import _pav_isotonic
        # Adversarial inputs — not sorted, with violations
        xs = [10, 20, 30, 40, 50, 60, 70, 80, 90]
        ys = [0.2, 0.3, 0.1, 0.6, 0.4, 0.7, 0.65, 0.8, 0.9]  # 0.1<0.3, 0.4<0.6, 0.65<0.7 violations
        x_knots, y_knots = _pav_isotonic(xs, ys)
        # y_knots must be monotonic non-decreasing
        for i in range(1, len(y_knots)):
            assert y_knots[i] >= y_knots[i - 1] - 1e-9, \
                f"PAV output not monotonic at {i}: {y_knots}"

    def test_calibrator_clamps_to_range(self):
        """Inputs outside fitted range must clamp to endpoint y values."""
        from app.services.calibration_fit import Calibrator
        from datetime import datetime
        cal = Calibrator(
            x_knots=[10, 50, 90],
            y_knots=[0.1, 0.5, 0.9],
            n_samples=100, fitted_at=datetime.utcnow(),
            brier_before=0.25, brier_after=0.20,
        )
        # Below fitted range
        assert cal.calibrate(0) == 10.0      # y_knots[0] × 100
        # Above fitted range
        assert cal.calibrate(100) == 90.0    # y_knots[-1] × 100
        # Inside — linear interpolation
        result_30 = cal.calibrate(30)         # midpoint of 10..50 → midpoint of 10..50 → 30
        assert 25 <= result_30 <= 35


# ============================================================================
# Daily astro forecast — view stripping
# ============================================================================

class TestForecastViewStripping:
    def test_user_view_removes_astrology(self):
        """USER view must not contain nakshatra/day_lord/tara/tithi/paksha."""
        from app.engines.daily_astro_forecast import forecast
        result = forecast("NIFTY", days=7, view="user")
        for day in result["days"]:
            if not day["is_market_open"]:
                continue
            # These fields MUST NOT appear in user view
            for forbidden in ("day_lord", "moon_nakshatra",
                                "moon_nakshatra_ruler", "tithi", "paksha",
                                "tara_distance", "tara_class", "astro_score"):
                assert forbidden not in day, \
                    f"User view leaked {forbidden!r}: {day}"
            # These MUST appear
            for required in ("date", "bias", "confidence", "expected_range_pct"):
                assert required in day, f"User view missing {required!r}"

    def test_admin_view_includes_astrology(self):
        """ADMIN view must contain the full astrology breakdown."""
        from app.engines.daily_astro_forecast import forecast
        result = forecast("NIFTY", days=7, view="admin")
        for day in result["days"]:
            if not day["is_market_open"]:
                continue
            # These MUST appear in admin view
            for required in ("day_lord", "moon_nakshatra", "astro_score",
                              "tara_class"):
                assert required in day, f"Admin view missing {required!r}"

    def test_sanitize_event_drops_jargon(self):
        from app.engines.daily_astro_forecast import sanitize_event
        # Jargon should be rewritten to neutral OR dropped entirely
        assert sanitize_event("Moon enters Magha (Ketu)") is not None
        assert "Magha" not in sanitize_event("Moon enters Magha (Ketu)").lower()
        # Pure jargon with no neutral mapping → dropped
        assert sanitize_event("Saturn aspecting Ashlesha nakshatra") is None
