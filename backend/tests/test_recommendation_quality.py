"""Tests for the recommendation_quality clarity layer.

The single most important property: HARD BLOCKS take precedence.

  • Suspect price → AVOID, regardless of any other signal
  • Risk-guard BLOCK → AVOID, regardless of confidence
  • NEUTRAL direction → WATCH, never BUY/SELL
  • Confidence < 50 → WAIT, never BUY/SELL

The promotion logic (1→2→3 promotions → WEAK/MEDIUM/STRONG) is also tested
to make sure that adding multiple agreeing signals actually escalates the
verdict.
"""
from __future__ import annotations

import pytest


from app.services.recommendation_quality import assess


# Helper — build a minimal symbol_data dict that satisfies the schema
def _base(**overrides):
    data = {
        "direction":      "BULLISH",
        "confidence":     60,
        "confidence_raw": 60,
        "confidence_is_calibrated": False,
        "price_sanity":   {"verdict": "OK"},
        "risk_guard":     {"verdict": "OK",
                            "suggested_quantity": 10,
                            "risk_amount_rs": 1000,
                            "risk_pct_of_capital": 1.0,
                            "risk_reward_ratio": 2.0,
                            "reasons": [], "warnings": []},
        "confidence_band":   {"conviction_quality": "ALIGNED"},
        "advanced_ta":       {"confluence_count": 2, "composite_bias": "BULLISH"},
        "historical_analog": {"has_enough_data": False, "outcomes": {"n": 0}},
        "meta_learner":      {"is_trustworthy": False, "p_win": 0.5},
        "strategy":          {"entry": 100.0, "stoploss": 98.0, "targets": [104.0, 106.0]},
        "stop_loss_analysis": {"recommended_method": "STRUCTURAL"},
    }
    data.update(overrides)
    return data


# ============================================================================
# HARD BLOCKS — should win over any other signal
# ============================================================================

class TestHardBlocks:
    def test_suspect_price_overrides_everything(self):
        d = _base(
            direction="BULLISH", confidence=95,
            advanced_ta={"confluence_count": 3, "composite_bias": "BULLISH"},
            price_sanity={"verdict": "SUSPECT", "reasons": ["candle vs LTP off by 75%"]},
        )
        q = assess(d)
        assert q.verdict == "AVOID"
        assert q.conviction == "NONE"
        assert "suspect" in q.headline.lower()
        assert q.trade_plan is None

    def test_risk_guard_block_overrides_strong_signal(self):
        d = _base(
            direction="BULLISH", confidence=90,
            risk_guard={"verdict": "BLOCK",
                          "reasons": ["Loss circuit breaker active"],
                          "warnings": []},
        )
        q = assess(d)
        assert q.verdict == "AVOID"
        assert "blocked" in q.headline.lower() or "block" in q.headline.lower()
        assert q.trade_plan is None


# ============================================================================
# SOFT GATES — should produce WATCH or WAIT
# ============================================================================

class TestSoftGates:
    def test_neutral_direction_produces_watch(self):
        d = _base(direction="NEUTRAL", confidence=70)
        q = assess(d)
        assert q.verdict == "WATCH"

    def test_low_confidence_produces_wait(self):
        d = _base(confidence=45)
        q = assess(d)
        assert q.verdict == "WAIT"

    def test_conflicted_engines_produce_watch(self):
        d = _base(
            confidence=65,
            confidence_band={"conviction_quality": "CONFLICTED"},
        )
        q = assess(d)
        assert q.verdict == "WATCH"

    def test_bad_rr_produces_wait(self):
        d = _base(
            risk_guard={"verdict": "DOWNGRADE_WAIT",
                          "risk_reward_ratio": 0.8,
                          "reasons": [],
                          "warnings": ["R:R below 1.2"]},
        )
        q = assess(d)
        assert q.verdict == "WAIT"


# ============================================================================
# ACTIONABLE — verdict + conviction by promotion count
# ============================================================================

class TestActionable:
    def test_borderline_signal_is_watch(self):
        """Confidence 55 with no promotions → WATCH, not BUY"""
        d = _base(confidence=55,
                   advanced_ta={"confluence_count": 1, "composite_bias": "BULLISH"})
        q = assess(d)
        assert q.verdict == "WATCH"

    def test_one_promotion_is_weak_buy(self):
        """Confidence 65 + ATA confluence 3/3 → BUY with WEAK conviction"""
        d = _base(confidence=65,
                   advanced_ta={"confluence_count": 3, "composite_bias": "BULLISH"})
        q = assess(d)
        assert q.verdict == "BUY"
        assert q.conviction == "WEAK"

    def test_three_promotions_is_strong_buy(self):
        d = _base(
            confidence=75,
            confidence_is_calibrated=True,
            advanced_ta={"confluence_count": 3, "composite_bias": "BULLISH"},
            historical_analog={"has_enough_data": True,
                                 "outcomes": {"n": 14, "win_rate": 0.71}},
            meta_learner={"is_trustworthy": True, "p_win": 0.68},
        )
        q = assess(d)
        assert q.verdict == "STRONG_BUY"
        assert q.conviction == "STRONG"

    def test_bearish_direction_produces_sell(self):
        d = _base(direction="BEARISH", confidence=70,
                    advanced_ta={"confluence_count": 3, "composite_bias": "BEARISH"})
        q = assess(d)
        assert q.verdict in ("SELL", "STRONG_SELL")

    def test_trade_plan_present_when_actionable(self):
        d = _base(confidence=70,
                   advanced_ta={"confluence_count": 3, "composite_bias": "BULLISH"})
        q = assess(d)
        assert q.trade_plan is not None
        assert q.trade_plan["entry"] == 100.0

    def test_trade_plan_absent_when_watch(self):
        d = _base(direction="NEUTRAL")
        q = assess(d)
        assert q.trade_plan is None


# ============================================================================
# Caveats — honest about what's unknown
# ============================================================================

class TestCaveats:
    def test_lists_unknown_signals(self):
        """When historical analog + AI + calibration are all NOT ready,
        the verdict should list all three as caveats."""
        d = _base(
            confidence=70,
            confidence_is_calibrated=False,
            historical_analog={"has_enough_data": False, "outcomes": {"n": 0}},
            meta_learner={"is_trustworthy": False, "p_win": 0.5},
        )
        q = assess(d)
        # Three categories of unknown → three caveats
        assert len(q.caveats) >= 3
        text = " ".join(q.caveats).lower()
        assert "historical" in text
        assert "ai" in text or "warmup" in text
        assert "calibrat" in text or "validated" in text

    def test_no_caveats_when_fully_warm(self):
        """When all signals are warmed up, only the strategy-level warnings remain."""
        d = _base(
            confidence=70,
            confidence_is_calibrated=True,
            historical_analog={"has_enough_data": True,
                                 "outcomes": {"n": 15, "win_rate": 0.60}},
            meta_learner={"is_trustworthy": True, "p_win": 0.65},
        )
        q = assess(d)
        # No "warmup" / "accumulating" / "calibrat" caveats at this point
        joined = " ".join(q.caveats).lower()
        assert "warmup" not in joined
        assert "accumulating" not in joined


# ============================================================================
# Trust signals — should always be populated
# ============================================================================

class TestTrustSignals:
    def test_always_includes_trust_signals(self):
        for d in [_base(), _base(direction="NEUTRAL"),
                    _base(confidence=30),
                    _base(price_sanity={"verdict": "SUSPECT", "reasons": []})]:
            q = assess(d)
            assert "price_sanity" in q.trust_signals
            assert "calibrated" in q.trust_signals
            assert "ai_trustworthy" in q.trust_signals
