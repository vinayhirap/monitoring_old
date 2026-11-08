"""Unit tests for the service-layer modules added in recent turns.

Each module gets its own test class. Assertions focus on:
  • Inputs that triggered real production bugs (e.g. spot=0, qty=0)
  • Boundary conditions (just above/below thresholds)
  • Output shape invariants (so the API contract doesn't drift)

These complement the engine golden tests in test_engines.py.
"""
from __future__ import annotations

import pytest


# ============================================================================
# price_sanity.check
# ============================================================================

class TestPriceSanity:
    def test_empty_dataframe_returns_no_reference(self):
        import pandas as pd
        from app.services.price_sanity import check
        result = check("NIFTY", pd.DataFrame(), exchange="NSE")
        assert result.verdict == "NO_REFERENCE"
        assert "empty" in result.reasons[0].lower()

    def test_normal_data_passes(self, synthetic_ohlcv):
        """Synthetic OHLCV — no broker auth means LTP check is skipped,
        but candle-age check should pass since the fixture has fresh dates."""
        from app.services.price_sanity import check
        result = check("TEST_SYM", synthetic_ohlcv, exchange="NSE")
        # Without broker auth we can't get LTP, but verdict should still be OK
        # because no positive evidence of corruption.
        assert result.verdict in ("OK", "NO_REFERENCE")
        assert result.candle_close is not None
        assert result.candle_close > 0

    def test_spot_disagrees_with_candle_close(self, synthetic_ohlcv):
        """When the spot used differs from the candle close by >2%, verdict
        must be SUSPECT — that's exactly the COALINDIA scenario."""
        from app.services.price_sanity import check
        last_close = float(synthetic_ohlcv["close"].iloc[-1])
        # Simulate a 10% disagreement
        result = check("TEST_SYM", synthetic_ohlcv, exchange="NSE",
                        spot_used=last_close * 1.10)
        assert result.verdict == "SUSPECT"
        assert any("inconsistency" in r.lower() or "off" in r.lower() or "differ" in r.lower()
                    for r in result.reasons)


# ============================================================================
# funds_check
# ============================================================================

class TestFundsCheck:
    def test_estimate_required_margin_intraday(self):
        from app.services.funds_check import estimate_required_margin
        # 100 shares × ₹2000 = ₹200,000 notional. Intraday = 20% = ₹40,000.
        margin, src = estimate_required_margin(entry=2000, quantity=100,
                                                  product_type="INTRADAY")
        assert abs(margin - 40_000) < 0.01
        assert src == "fallback_equity_intraday"

    def test_estimate_required_margin_delivery(self):
        from app.services.funds_check import estimate_required_margin
        # Delivery requires 100% cash
        margin, src = estimate_required_margin(entry=2000, quantity=100,
                                                  product_type="DELIVERY")
        assert abs(margin - 200_000) < 0.01
        assert src == "fallback_equity_delivery"

    def test_estimate_required_margin_fno(self):
        from app.services.funds_check import estimate_required_margin
        # F&O ~15% margin estimate
        margin, src = estimate_required_margin(entry=100, quantity=750, product_type="NRML", is_fno=True)
        assert margin == pytest.approx(100 * 750 * 0.15, rel=0.01)
        assert "fno" in src.lower()

    def test_check_with_no_broker_soft_allows(self):
        """When broker can't be reached, sufficient=True with a warning so
        the order goes through (broker will reject if truly under-funded)."""
        from app.services.funds_check import check
        result = check(entry=100, quantity=10, product_type="DELIVERY")
        # Broker is not authenticated in test env → soft-allow path
        assert result.sufficient is True
        assert any("unavailable" in w.lower() for w in result.warnings)


# ============================================================================
# brokerage_estimator
# ============================================================================

class TestBrokerage:
    def test_equity_delivery_buy(self):
        from app.services.brokerage_estimator import estimate
        # 10 shares × ₹500 = ₹5000 notional
        r = estimate(entry=500, quantity=10, segment="EQUITY_DELIVERY", direction="BUY")
        assert r.notional == 5000
        # Discount-broker brokerage is 0 for delivery
        assert r.brokerage == 0
        # STT 0.1% × ₹5000 = ₹5
        assert r.stt == pytest.approx(5.0, rel=0.01)
        # Stamp duty applies on BUY side only — 0.015%
        assert r.stamp_duty == pytest.approx(5000 * 0.00015, rel=0.01)
        # Total charges > 0 (statutory fees always apply)
        assert r.total_charges > 0

    def test_equity_intraday_caps_brokerage_at_20(self):
        from app.services.brokerage_estimator import estimate
        # Large notional — brokerage should be capped at ₹20
        r = estimate(entry=2000, quantity=500, segment="EQUITY_INTRADAY", direction="BUY")
        assert r.brokerage == 20

    def test_sell_side_has_no_stamp_duty(self):
        from app.services.brokerage_estimator import estimate
        r = estimate(entry=500, quantity=10, segment="EQUITY_DELIVERY", direction="SELL")
        assert r.stamp_duty == 0
        # But STT still applies on sell side too for delivery
        assert r.stt > 0

    def test_round_trip_includes_both_legs(self):
        from app.services.brokerage_estimator import estimate_round_trip
        # Buy at 100, sell at 102, qty 100 = 200 gross profit before charges
        rt = estimate_round_trip(entry=100, exit_=102, quantity=100,
                                    segment="EQUITY_INTRADAY")
        assert rt["gross_pnl"] == 200
        # Net is gross minus total_charges
        assert rt["net_pnl"] == pytest.approx(200 - rt["total_charges"], rel=0.001)
        assert rt["total_charges"] > 0


# ============================================================================
# stop_loss_engine
# ============================================================================

class TestStopLossEngine:
    def test_atr_fallback_when_nothing_else_provided(self):
        from app.engines.stop_loss_engine import compute
        # Just entry + direction + ATR — no other inputs
        r = compute(entry=100, direction="BULLISH", atr=2.0)
        # Should produce some level via ATR method
        assert r.recommended_sl > 0
        assert r.recommended_sl < 100    # below entry for bullish

    def test_bullish_long_sl_below_entry(self):
        from app.engines.stop_loss_engine import compute
        r = compute(entry=100, direction="BULLISH", atr=2.0,
                     swing_low=96, swing_high=110)
        assert r.recommended_sl < 100
        # Should pick structural over ATR (defensibility 5 vs 2)
        assert r.recommended_method in ("STRUCTURAL", "CONFLUENCE")

    def test_bearish_short_sl_above_entry(self):
        from app.engines.stop_loss_engine import compute
        r = compute(entry=100, direction="BEARISH", atr=2.0,
                     swing_low=90, swing_high=104)
        assert r.recommended_sl > 100

    def test_invalid_entry_returns_fallback(self):
        from app.engines.stop_loss_engine import compute
        r = compute(entry=0, direction="BULLISH", atr=2.0)
        # Engine returns SOME report (even if FALLBACK_2PCT)
        assert r is not None

    def test_invalid_direction_raises(self):
        from app.engines.stop_loss_engine import compute
        with pytest.raises(ValueError):
            compute(entry=100, direction="SIDEWAYS", atr=2.0)


# ============================================================================
# candlestick_patterns
# ============================================================================

class TestCandlestickPatterns:
    def test_no_crash_on_short_data(self):
        import pandas as pd
        from app.engines.candlestick_patterns import detect
        df = pd.DataFrame({"open": [100], "high": [102], "low": [99], "close": [101], "volume": [100]})
        r = detect(df)
        # 1 bar isn't enough — should NOT crash, returns NEUTRAL
        assert r.composite_bias == "NEUTRAL"

    def test_returns_known_shape_on_normal_data(self, synthetic_ohlcv):
        from app.engines.candlestick_patterns import detect
        r = detect(synthetic_ohlcv)
        # Schema invariants
        assert hasattr(r, "patterns")
        assert hasattr(r, "composite_bias")
        assert r.composite_bias in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 0 <= r.composite_score <= 100


# ============================================================================
# signal_explainer (i18n smoke test)
# ============================================================================

class TestSignalExplainer:
    def test_english_explanation_renders(self):
        from app.engines.signal_explainer import explain
        data = {
            "symbol": "RELIANCE", "direction": "BULLISH", "confidence": 72,
            "analyzers": {"technical": {"bias": "BULLISH", "reasons": ["trend up"]}},
        }
        e = explain(data, hide_astrology=False, lang="en")
        assert "high conviction" in e.headline.lower() or "moderate" in e.headline.lower()
        assert e.body  # non-empty

    def test_hindi_falls_back_to_english_for_unknown_keys(self):
        from app.engines.signal_explainer import explain
        data = {"symbol": "RELIANCE", "direction": "BULLISH", "confidence": 72}
        e = explain(data, hide_astrology=True, lang="hi")
        # Hindi opener should appear (खरीदार or similar Devanagari character)
        assert any(ord(c) > 127 for c in e.headline)

    def test_unknown_language_falls_back(self):
        from app.engines.signal_explainer import explain
        data = {"symbol": "RELIANCE", "direction": "BULLISH", "confidence": 72}
        e = explain(data, lang="xx")
        # Should NOT crash; falls back to English
        assert e.headline
