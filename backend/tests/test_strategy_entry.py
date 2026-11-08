"""Tests for the smart-entry logic in app.engines.strategy.

Critical property: the recommendation MUST NOT just echo current LTP back as
the entry price. _smart_entry picks PULLBACK / BREAKOUT / MARKET based on
Gann support/resistance and consecutive-candle confirmation.

Bug history: previously `entry = round(spot, 2)` unconditionally, which made
every recommendation read "buy at current price" with no edge. These tests
exist to keep that regression from coming back.
"""
from __future__ import annotations

import pytest

from app.engines.strategy import (
    _consecutive_in_direction,
    _smart_entry,
    select,
)


# ============================================================================
# _consecutive_in_direction
# ============================================================================

class TestConsecutiveInDirection:
    def test_empty_candles_returns_zero(self):
        assert _consecutive_in_direction([], "BULLISH") == 0
        assert _consecutive_in_direction(None, "BULLISH") == 0

    def test_all_bullish_candles(self):
        bars = [{"open": 100, "close": 101},
                {"open": 101, "close": 102},
                {"open": 102, "close": 103}]
        assert _consecutive_in_direction(bars, "BULLISH") == 3
        assert _consecutive_in_direction(bars, "BEARISH") == 0

    def test_all_bearish_candles(self):
        bars = [{"open": 103, "close": 102},
                {"open": 102, "close": 101},
                {"open": 101, "close": 100}]
        assert _consecutive_in_direction(bars, "BEARISH") == 3
        assert _consecutive_in_direction(bars, "BULLISH") == 0

    def test_doji_breaks_streak(self):
        # Two green, then doji, then another green — streak from newest
        # should be 1 (the doji stops the count after the most recent green).
        bars = [{"open": 100, "close": 101},
                {"open": 101, "close": 102},
                {"open": 102, "close": 102},     # doji
                {"open": 102, "close": 103}]
        assert _consecutive_in_direction(bars, "BULLISH") == 1

    def test_opposing_bar_breaks_streak(self):
        bars = [{"open": 100, "close": 101},
                {"open": 101, "close": 102},
                {"open": 102, "close": 100},     # bearish bar
                {"open": 100, "close": 101},
                {"open": 101, "close": 102}]
        # Last 2 bars are bullish; the bearish one before that stops the count
        assert _consecutive_in_direction(bars, "BULLISH") == 2

    def test_counts_from_newest_bar(self):
        # Even if the older bars are all bullish, only the trailing streak counts
        bars = [{"open": 100, "close": 110},
                {"open": 110, "close": 120},
                {"open": 120, "close": 130},
                {"open": 130, "close": 125}]     # one bearish at end
        assert _consecutive_in_direction(bars, "BULLISH") == 0
        assert _consecutive_in_direction(bars, "BEARISH") == 1


# ============================================================================
# _smart_entry — BULLISH paths
# ============================================================================

class TestSmartEntryBullish:
    def test_breakout_above_resistance_with_momentum(self):
        """Recent close above Gann resistance + 2 consecutive bullish bars → BREAKOUT."""
        # Spot is just above resistance; last 2 bars are green
        bars = [{"open": 100, "close": 101},
                {"open": 101, "close": 102}]      # 2 consecutive bullish, last close = 102
        result = _smart_entry(
            spot=102.0, direction="BULLISH", atr=2.0,
            gann_support=95.0, gann_resistance=100.0,
            recent_candles=bars,
        )
        assert result["trigger_type"] == "BREAKOUT"
        # Entry should be just above resistance with a buffer
        assert result["entry"] > 100.0
        assert result["entry"] < 101.0      # not just spot back
        assert result["entry_zone"]["anchor"] == "GANN_RESISTANCE"
        assert "breakout" in result["trigger_note"].lower()

    def test_pullback_to_support_when_spot_above(self):
        """Spot meaningfully above support → PULLBACK, entry between support and spot."""
        bars = [{"open": 100, "close": 101}]    # only 1 bullish — not enough for breakout
        result = _smart_entry(
            spot=110.0, direction="BULLISH", atr=2.0,
            gann_support=100.0, gann_resistance=120.0,
            recent_candles=bars,
        )
        assert result["trigger_type"] == "PULLBACK"
        # Entry should be a pullback target — below current spot
        assert result["entry"] < 110.0
        # But above support (with small buffer)
        assert result["entry"] > 100.0
        assert result["entry_zone"]["anchor"] == "GANN_SUPPORT"

    def test_entry_is_NOT_spot_in_pullback_path(self):
        """The original bug: entry == spot. Make absolutely sure that's fixed."""
        result = _smart_entry(
            spot=150.0, direction="BULLISH", atr=3.0,
            gann_support=140.0, gann_resistance=160.0,
            recent_candles=[{"open": 148, "close": 150}],
        )
        # PULLBACK should produce a meaningfully different price from spot
        assert abs(result["entry"] - 150.0) > 0.5, \
            f"PULLBACK entry should differ from spot, got {result['entry']}"

    def test_market_entry_when_no_gann_levels(self):
        """No Gann S/R → falls back to MARKET with wider zone."""
        result = _smart_entry(
            spot=100.0, direction="BULLISH", atr=2.0,
            gann_support=None, gann_resistance=None,
            recent_candles=[{"open": 99, "close": 100}],
        )
        assert result["trigger_type"] == "MARKET"
        assert result["entry"] == 100.0
        assert result["entry_zone"]["anchor"] == "MARKET"

    def test_market_entry_when_spot_at_support(self):
        """Spot very close to support — no meaningful pullback distance → MARKET."""
        result = _smart_entry(
            spot=100.5, direction="BULLISH", atr=2.0,
            gann_support=100.0, gann_resistance=110.0,
            recent_candles=[{"open": 100, "close": 100.5}],
        )
        # Distance from support is < 0.5×ATR (=1.0) so PULLBACK path doesn't activate
        assert result["trigger_type"] == "MARKET"


# ============================================================================
# _smart_entry — BEARISH paths
# ============================================================================

class TestSmartEntryBearish:
    def test_breakdown_below_support_with_momentum(self):
        bars = [{"open": 100, "close": 99},
                {"open": 99, "close": 98}]       # 2 consecutive bearish
        result = _smart_entry(
            spot=98.0, direction="BEARISH", atr=2.0,
            gann_support=100.0, gann_resistance=110.0,
            recent_candles=bars,
        )
        assert result["trigger_type"] == "BREAKOUT"
        # Entry should be just below support (sell-on-breakdown)
        assert result["entry"] < 100.0
        assert "breakdown" in result["trigger_note"].lower()

    def test_rally_to_resistance_pullback(self):
        bars = [{"open": 101, "close": 100}]    # 1 bearish bar only
        result = _smart_entry(
            spot=100.0, direction="BEARISH", atr=2.0,
            gann_support=90.0, gann_resistance=110.0,
            recent_candles=bars,
        )
        assert result["trigger_type"] == "PULLBACK"
        # Entry should be a rally target — above current spot
        assert result["entry"] > 100.0
        # But below resistance
        assert result["entry"] < 110.0
        assert result["entry_zone"]["anchor"] == "GANN_RESISTANCE"


# ============================================================================
# _smart_entry — robustness
# ============================================================================

class TestSmartEntryRobustness:
    def test_zero_atr_does_not_crash(self):
        """ATR=0 (e.g. for a brand-new instrument) — must floor to something usable."""
        result = _smart_entry(
            spot=100.0, direction="BULLISH", atr=0,
            gann_support=None, gann_resistance=None,
            recent_candles=None,
        )
        assert result["entry"] > 0
        assert "low" in result["entry_zone"]
        assert "high" in result["entry_zone"]

    def test_negative_gann_levels_ignored(self):
        """Defensive: a bogus negative S/R should not derail entry pricing."""
        result = _smart_entry(
            spot=100.0, direction="BULLISH", atr=2.0,
            gann_support=-50.0,         # bogus
            gann_resistance=-10.0,      # bogus
            recent_candles=None,
        )
        assert result["trigger_type"] == "MARKET"

    def test_sideways_direction_returns_market(self):
        result = _smart_entry(
            spot=100.0, direction="SIDEWAYS", atr=2.0,
            gann_support=95.0, gann_resistance=105.0,
            recent_candles=None,
        )
        assert result["trigger_type"] == "MARKET"


# ============================================================================
# select() — end-to-end: smart entry fields are surfaced on the StrategyPlan
# ============================================================================

class TestSelectIntegration:
    def test_plan_includes_trigger_metadata(self):
        plan = select(
            symbol="TEST", spot=110.0, direction="BULLISH",
            confidence=70, atr=2.0, iv_pct=20.0,
            horizon="SWING", capital=100_000,
            gann_support=100.0, gann_resistance=120.0,
            recent_candles=[{"open": 108, "close": 110}],
            attach_timing=False,        # avoid pulling hora_eng in tests
        )
        # Smart-entry fields must populate
        assert plan.trigger_type in ("PULLBACK", "BREAKOUT", "MARKET")
        assert "anchor" in plan.entry_zone
        assert "low" in plan.entry_zone
        assert "high" in plan.entry_zone

    def test_candle_confirmation_block_populated(self):
        plan = select(
            symbol="TEST", spot=110.0, direction="BULLISH",
            confidence=70, atr=2.0, iv_pct=20.0,
            horizon="SWING", capital=100_000,
            gann_support=100.0, gann_resistance=120.0,
            recent_candles=[{"open": 108, "close": 110},
                             {"open": 109, "close": 111}],
            attach_timing=False,
        )
        cc = plan.candle_confirmation
        assert cc["consecutive_in_direction"] == 2
        assert cc["required"] == 2          # SWING requires 2
        assert cc["confirmed"] is True

    def test_intraday_requires_3_consecutive_bars(self):
        plan = select(
            symbol="TEST", spot=110.0, direction="BULLISH",
            confidence=70, atr=2.0, iv_pct=20.0,
            horizon="INTRADAY", capital=100_000,
            gann_support=100.0, gann_resistance=120.0,
            recent_candles=[{"open": 108, "close": 110},
                             {"open": 109, "close": 111}],     # only 2 bullish
            attach_timing=False,
        )
        cc = plan.candle_confirmation
        assert cc["required"] == 3
        assert cc["confirmed"] is False
        # Should also add a "wait for momentum" note
        assert any("consecutive" in n.lower() for n in plan.notes)

    def test_stoploss_anchored_below_support_for_bullish(self):
        """SL should sit below Gann support (with buffer), not just entry - 1.5×ATR.
        This is the structural-stop fix: ATR-only stops get swept by noise."""
        plan = select(
            symbol="TEST", spot=110.0, direction="BULLISH",
            confidence=70, atr=2.0, iv_pct=18.0,
            horizon="SWING", capital=100_000,
            gann_support=104.0, gann_resistance=120.0,
            recent_candles=[{"open": 108, "close": 110}],
            attach_timing=False,
        )
        # SL should be at-or-below gann_support*0.995 = ~103.48
        assert plan.stoploss <= 104.0
