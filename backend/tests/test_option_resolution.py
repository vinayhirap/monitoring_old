"""Tests for option-contract resolution.

The critical bug being prevented: F&O orders sent to the broker MUST use
the contract tradingsymbol (e.g. NIFTY24APR23500CE), NOT the underlying
(NIFTY). Without the right contract symbol, the broker either rejects the
order or — worse — places an EQUITY order against the index at the option
premium price (₹100 instead of ₹23,500), which is a nonsensical position.

These tests cover:
  • _format_option_tradingsymbol — correct NSE F&O symbol convention
  • lookup_option — finds contract in loaded scrip master
  • resolve_option_for_order — returns (tradingsymbol, token), with
    fallback to constructed name when dump is empty
  • OrderIntent with option meta → broker receives the contract symbol,
    not the underlying
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.services import instruments


# ============================================================================
# _format_option_tradingsymbol — the construction convention
# ============================================================================

class TestFormatOptionTradingsymbol:
    def test_monthly_nifty_call(self):
        ts = instruments._format_option_tradingsymbol(
            "NIFTY", "2024-04-25", 23500, "CE")
        assert ts == "NIFTY24APR23500CE"

    def test_monthly_nifty_put(self):
        ts = instruments._format_option_tradingsymbol(
            "NIFTY", "2024-04-25", 23500, "PE")
        assert ts == "NIFTY24APR23500PE"

    def test_banknifty_with_higher_strike(self):
        ts = instruments._format_option_tradingsymbol(
            "BANKNIFTY", "2024-12-26", 51000, "CE")
        assert ts == "BANKNIFTY24DEC51000CE"

    def test_year_2025(self):
        ts = instruments._format_option_tradingsymbol(
            "NIFTY", "2025-01-30", 22000, "PE")
        assert ts == "NIFTY25JAN22000PE"

    def test_lowercase_normalized_to_upper(self):
        ts = instruments._format_option_tradingsymbol(
            "nifty", "2024-04-25", 23500, "ce")
        assert ts == "NIFTY24APR23500CE"

    def test_whole_strike_drops_decimal(self):
        ts = instruments._format_option_tradingsymbol(
            "NIFTY", "2024-04-25", 23500.0, "CE")
        assert ts == "NIFTY24APR23500CE"      # not "23500.0"

    def test_invalid_option_type_raises(self):
        with pytest.raises(ValueError, match="CE or PE"):
            instruments._format_option_tradingsymbol(
                "NIFTY", "2024-04-25", 23500, "XX")


# ============================================================================
# resolve_option_for_order — fallback when scrip master can't find it
# ============================================================================

class TestResolveOptionForOrder:
    def test_falls_back_to_constructed_when_not_found(self):
        """When the scrip master returns None for the lookup, we still need
        to give the broker SOMETHING — the constructed format is our best
        guess. Broker rejection surfaces as a clear error downstream."""
        with patch.object(instruments, "lookup_option", return_value=None):
            ts, token = instruments.resolve_option_for_order(
                underlying="NIFTY", expiry_iso="2024-04-25",
                strike=23500, option_type="CE",
            )
            assert ts == "NIFTY24APR23500CE"
            assert token is None       # explicit signal that no row was found

    def test_returns_row_token_when_found(self):
        fake_row = {
            "token":  "12345",
            "symbol": "NIFTY24APR23500CE",
            "name":   "NIFTY",
            "exch_seg": "NFO",
            "instrumenttype": "OPTIDX",
            "strike": 23500.0,
            "expiry": "25APR2024",
        }
        with patch.object(instruments, "lookup_option", return_value=fake_row):
            ts, token = instruments.resolve_option_for_order(
                underlying="NIFTY", expiry_iso="2024-04-25",
                strike=23500, option_type="CE",
            )
            assert ts == "NIFTY24APR23500CE"
            assert token == "12345"


# ============================================================================
# OrderIntent → broker call uses contract symbol, not underlying
# ============================================================================

class TestExecutorOptionResolution:
    def test_resolver_overwrites_symbol_and_exchange(self):
        """When option meta is set, _resolve_option_contract must rewrite
        the Order row's symbol+exchange to the resolved contract+NFO."""
        from app.services.trade_executor import _resolve_option_contract, OrderIntent

        intent = OrderIntent(
            user_id=1, symbol="NIFTY", direction="BUY", quantity=50,
            option_strike=23500, option_type="CE", option_expiry="2024-04-25",
        )
        order = MagicMock()
        order.symbol = "NIFTY"
        order.exchange = "NSE"
        order.broker_response = None

        with patch("app.services.instruments.resolve_option_for_order",
                    return_value=("NIFTY24APR23500CE", "12345")):
            ok, err = _resolve_option_contract(order, intent)
            assert ok is True
            assert err is None
            assert order.symbol == "NIFTY24APR23500CE"
            assert order.exchange == "NFO"
            assert order.broker_response["resolved_token"] == "12345"

    def test_resolver_noop_when_no_option_meta(self):
        """Equity orders (no option_* fields) must NOT be touched."""
        from app.services.trade_executor import _resolve_option_contract, OrderIntent

        intent = OrderIntent(
            user_id=1, symbol="RELIANCE", direction="BUY", quantity=10,
        )
        order = MagicMock()
        order.symbol = "RELIANCE"
        order.exchange = "NSE"

        ok, err = _resolve_option_contract(order, intent)
        assert ok is True
        assert order.symbol == "RELIANCE"            # unchanged
        assert order.exchange == "NSE"               # unchanged

    def test_resolver_returns_error_when_resolution_throws(self):
        from app.services.trade_executor import _resolve_option_contract, OrderIntent

        intent = OrderIntent(
            user_id=1, symbol="NIFTY", direction="BUY", quantity=50,
            option_strike=23500, option_type="CE", option_expiry="2024-04-25",
        )
        order = MagicMock()
        order.symbol = "NIFTY"

        with patch("app.services.instruments.resolve_option_for_order",
                    side_effect=RuntimeError("instruments dump unavailable")):
            ok, err = _resolve_option_contract(order, intent)
            assert ok is False
            assert "instruments dump unavailable" in (err or "")
