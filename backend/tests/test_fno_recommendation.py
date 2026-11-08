"""Tests for the F&O recommendation orchestrator.

`fno_recommendation.build()` projects the giant /api/symbol/{sym} response
down to a focused F&O recommendation. The critical properties:

  • Pass-through verdict from recommendation_quality (NEVER recomputes)
  • Trade plan + legs come from options_strategy.recommend()
  • Astro overlay always populated (even when neutral)
  • Confluence count never NaN — always integers
  • safe_build NEVER raises (used in API handlers)
  • WATCH / WAIT / AVOID verdicts produce execution_payload=None
"""
from __future__ import annotations

import pytest

from app.services.fno_recommendation import (
    build,
    safe_build,
    _build_astro_overlay,
    _build_confluence,
    CONFIRMING_ENGINES,
)


# ============================================================================
# Helpers — build a realistic symbol_data dict
# ============================================================================

def _base_symbol_data(**overrides) -> dict:
    data = {
        "symbol": "NIFTY",
        "direction": "BULLISH",
        "confidence": 72,
        "confidence_is_calibrated": True,
        "ltp": {"ltp": 24500.0},
        "verdict": {
            "verdict": "BUY",
            "conviction": "MEDIUM",
            "caveats": [],
            "hard_blocks": [],
        },
        "analyzers": {
            "technical":  {"bias": "BULLISH"},
            "smc":        {"bias": "BULLISH_STRUCTURE"},
            "gann":       {"bias": "BULLISH"},
            "fibonacci":  {"bias": "BULLISH"},
            "vedic":      {"bias": "BULLISH", "nakshatra": "Rohini", "ruler": "Moon", "tara": "Sampat"},
            "numerology": {"bias": "NEUTRAL"},
            "ml":         {"bias": "BUY"},
        },
        "context": {
            "market_sentiment": {
                "bias": "BULLISH", "score": 65.0, "headline": "Strong bullish session",
                "bullish_factors": ["Moon in Rohini", "Hora bullish"],
                "bearish_factors": [],
            },
        },
        "options_analysis": {
            "analytics": {"pcr": 1.35, "max_pain": 24450, "iv_atm_pct": 16.5,
                            "support_wall": 24400, "resistance_wall": 24600,
                            "institutional_view": "Bullish put writing"},
            "expiry": "2026-06-04",
            "trade_plan": {
                "strategy": "BULL_CALL_SPREAD",
                "strategy_subtype": "Bull-call spread — IV 16.5% mid",
                "expiry": "2026-06-04", "days_to_expiry": 9,
                "iv_pct": 16.5, "iv_regime": "MID",
                "legs": [
                    {"action": "BUY",  "type": "CE", "strike": 24500, "ltp": 120,
                      "delta": 0.52, "theta": -3.1, "gamma": 0.003, "vega": 8.2,
                      "lot_size": 25, "premium_per_lot_inr": 3000},
                    {"action": "SELL", "type": "CE", "strike": 24600, "ltp": 70,
                      "delta": 0.32, "theta": -2.4, "gamma": 0.003, "vega": 7.0,
                      "lot_size": 25, "premium_per_lot_inr": 1750},
                ],
                "net_premium_inr": -1250, "max_profit_inr": 1250, "max_loss_inr": -1250,
                "breakeven_prices": [24550], "risk_reward": 1.0,
                "suggested_lots": 2, "suggested_capital_inr": 2500,
                "margin_required_inr": None,
                "entry_triggers": ["Enter as combined order"],
                "exit_triggers": ["Exit at 70% max profit"],
                "portfolio_greeks": {"net_delta": 10.0},
                "confidence_caveats": [],
            },
        },
        "advanced_ta": {"composite_bias": "BULLISH", "confluence_count": 3},
        "risk_guard": {"verdict": "OK", "suggested_quantity": 50},
        "price_sanity": {"verdict": "OK"},
    }
    # Deep-ish merge for top-level overrides
    for k, v in overrides.items():
        data[k] = v
    return data


# ============================================================================
# build() — happy path
# ============================================================================

class TestBuildHappyPath:
    def test_actionable_bull_call_spread(self):
        d = _base_symbol_data()
        rec = build(d)
        assert rec.symbol == "NIFTY"
        assert rec.verdict == "BUY"
        assert rec.conviction == "MEDIUM"
        assert rec.direction == "BULLISH"
        assert rec.confidence_pct == 72.0
        assert rec.confidence_is_calibrated is True
        assert rec.strategy == "BULL_CALL_SPREAD"
        assert len(rec.legs) == 2
        assert rec.max_profit_inr == 1250
        assert rec.suggested_lots == 2

    def test_headline_contains_strategy_for_multi_leg(self):
        d = _base_symbol_data()
        rec = build(d)
        # Multi-leg strategy → headline shows strategy name, not single strike
        assert "BULL CALL SPREAD" in rec.headline
        assert "(2 legs)" in rec.headline

    def test_execution_payload_built_for_actionable(self):
        d = _base_symbol_data()
        rec = build(d)
        assert rec.execution_payload is not None
        assert rec.execution_payload["product"] == "BO"
        assert rec.execution_payload["lots"] == 2
        assert len(rec.execution_payload["legs"]) == 2


# ============================================================================
# build() — non-actionable paths
# ============================================================================

class TestBuildNonActionable:
    def test_watch_verdict_no_execution_payload(self):
        d = _base_symbol_data()
        d["verdict"]["verdict"] = "WATCH"
        rec = build(d)
        assert rec.verdict == "WATCH"
        assert rec.execution_payload is None

    def test_avoid_verdict_no_execution_payload(self):
        d = _base_symbol_data()
        d["verdict"]["verdict"] = "AVOID"
        d["verdict"]["hard_blocks"] = ["Risk guard BLOCK"]
        rec = build(d)
        assert rec.verdict == "AVOID"
        assert rec.execution_payload is None
        assert "Risk guard BLOCK" in rec.hard_blocks

    def test_missing_options_analysis_graceful(self):
        d = _base_symbol_data()
        d["options_analysis"] = {}     # chain unavailable
        rec = build(d)
        # Should still produce a recommendation object — just empty trade plan
        assert rec.symbol == "NIFTY"
        assert rec.strategy == "WAIT"
        assert rec.legs == []


# ============================================================================
# Astro overlay
# ============================================================================

class TestAstroOverlay:
    def test_aligned_when_bias_matches_direction(self):
        d = _base_symbol_data()
        overlay = _build_astro_overlay(d, direction="BULLISH")
        assert overlay["aligned"] is True
        assert overlay["bias"] == "BULLISH"

    def test_misaligned_when_bias_opposes_direction(self):
        d = _base_symbol_data()
        d["context"]["market_sentiment"]["bias"] = "BEARISH"
        overlay = _build_astro_overlay(d, direction="BULLISH")
        assert overlay["aligned"] is False
        assert overlay["bias"] == "BEARISH"

    def test_neutral_direction_always_aligned(self):
        d = _base_symbol_data()
        overlay = _build_astro_overlay(d, direction="NEUTRAL")
        assert overlay["aligned"] is True

    def test_misalignment_adds_caveat_to_recommendation(self):
        d = _base_symbol_data()
        d["context"]["market_sentiment"]["bias"] = "BEARISH"
        rec = build(d)
        # Caveat string should mention astro misalignment
        assert any("astro" in c.lower() for c in rec.caveats)

    def test_symbol_nakshatra_carried_through(self):
        d = _base_symbol_data()
        overlay = _build_astro_overlay(d, direction="BULLISH")
        assert overlay["symbol_nakshatra"]["name"] == "Rohini"
        assert overlay["symbol_nakshatra"]["ruler"] == "Moon"


# ============================================================================
# Confluence
# ============================================================================

class TestConfluence:
    def test_all_engines_confirming(self):
        d = _base_symbol_data()
        # Every analyzer says BULLISH (already set up that way in _base)
        d["analyzers"]["numerology"]["bias"] = "BULLISH"
        c = _build_confluence(d, direction="BULLISH")
        # 7 engines named in CONFIRMING_ENGINES, all set to BULLISH
        assert c["confirming_count"] == len(CONFIRMING_ENGINES)
        assert c["dissenting_count"] == 0
        assert c["total_engines"] == len(CONFIRMING_ENGINES)

    def test_dissenting_engine_counted_correctly(self):
        d = _base_symbol_data()
        d["analyzers"]["fibonacci"]["bias"] = "BEARISH"   # one dissenter
        c = _build_confluence(d, direction="BULLISH")
        assert c["dissenting_count"] == 1
        assert "fibonacci" in c["dissenting"]
        assert "fibonacci" not in c["confirming"]

    def test_ml_buy_normalized_to_bullish(self):
        """ML reports BUY/SELL/HOLD — must be mapped to BULLISH/BEARISH/NEUTRAL."""
        d = _base_symbol_data()
        d["analyzers"]["ml"]["bias"] = "STRONG_BUY"
        c = _build_confluence(d, direction="BULLISH")
        assert "ml" in c["confirming"]

    def test_smc_bullish_structure_normalized(self):
        """SMC uses BULLISH_STRUCTURE — should still be counted as bullish."""
        d = _base_symbol_data()
        # already BULLISH_STRUCTURE in base
        c = _build_confluence(d, direction="BULLISH")
        assert "smc" in c["confirming"]


# ============================================================================
# safe_build — never raises
# ============================================================================

class TestSafeBuild:
    def test_safe_build_on_complete_data(self):
        result = safe_build(_base_symbol_data())
        assert result["symbol"] == "NIFTY"
        assert result["verdict"] == "BUY"

    def test_safe_build_swallows_corrupt_input(self):
        """Even when symbol_data is missing critical keys, safe_build returns
        a usable dict instead of crashing the API handler."""
        result = safe_build({"symbol": "BROKEN"})       # almost everything missing
        # Should return SOMETHING — possibly AVOID or partial — but never raise
        assert "symbol" in result
        assert "verdict" in result

    def test_safe_build_handles_none_values(self):
        d = _base_symbol_data()
        d["options_analysis"] = None
        d["verdict"] = None
        d["analyzers"] = None
        d["context"] = None
        # safe_build must not throw — that's the entire point
        result = safe_build(d)
        assert isinstance(result, dict)
        assert result.get("symbol") == "NIFTY"

    def test_safe_build_on_empty_dict(self):
        result = safe_build({})
        # Symbol falls back to "?" — accept either "?" or unknown sentinel
        assert isinstance(result, dict)
