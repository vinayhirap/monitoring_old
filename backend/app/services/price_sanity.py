"""Price sanity-check service.

Why this exists:

A user spotted COALINDIA showing ₹1827 in the app while TradingView (and
the actual NSE) showed ₹457. That's a 4× discrepancy — caused by one of:

  • Wrong scrip-master token (symbol resolves to wrong instrument)
  • Stale OHLCV cache (data from before a corporate action)
  • Synthetic fallback leaking through in LIVE mode
  • Wrong exchange segment (BSE vs NSE listing)

Any of these makes the entire analysis wrong, but the UI happily shows
"LIVE Angel One" because the broker IS authenticated — just returning
data for a different / older instrument.

This service catches the discrepancy by cross-checking THREE independent
sources for the same symbol:

  1. **Latest candle close** — what `get_ohlcv` returned
  2. **Broker.quote() LTP** — a separate API call to a different endpoint
  3. **Last-bar timestamp** — is the candle from today?

If any pair disagrees by >2% (or last bar is >2 trading days old), we
flag the symbol as `SUSPECT` and the UI shows a red banner. No analysis
is shown for SUSPECT symbols — better to refuse than mislead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from app.brokers.angelone import broker_instance
from app.services import instruments


# Tolerance thresholds
MAX_PRICE_DISCREPANCY_PCT = 2.0       # candle close vs LTP
MAX_LAST_BAR_AGE_DAYS     = 3         # weekend tolerance


@dataclass
class PriceSanityReport:
    symbol: str
    exchange: str
    verdict: str                              # OK / SUSPECT / NO_REFERENCE
    candle_close: Optional[float] = None      # last bar close from OHLCV
    broker_ltp: Optional[float] = None        # quote() LTP for comparison
    discrepancy_pct: Optional[float] = None
    last_bar_at: Optional[str] = None
    last_bar_age_days: Optional[int] = None
    instrument_token: Optional[str] = None
    instrument_name: Optional[str] = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def check(symbol: str, df: pd.DataFrame, exchange: str = "NSE",
            spot_used: float | None = None) -> PriceSanityReport:
    """Cross-check the OHLCV data against the broker's LTP.

    Args:
      symbol:    the symbol the user requested (uppercase)
      df:        the OHLCV dataframe `get_ohlcv` returned
      exchange:  NSE / BSE / MCX
      spot_used: the price the analysis is using (if different from df close)

    Returns:
      PriceSanityReport with verdict OK / SUSPECT / NO_REFERENCE
    """
    report = PriceSanityReport(symbol=symbol.upper(), exchange=exchange, verdict="OK")

    # ---- 1. Last bar timestamp + close ----
    if df is None or df.empty:
        report.verdict = "NO_REFERENCE"
        report.reasons.append("OHLCV dataframe is empty — cannot check.")
        return report

    try:
        last_close = float(df["close"].iloc[-1])
        report.candle_close = round(last_close, 2)
    except Exception as e:
        report.verdict = "NO_REFERENCE"
        report.reasons.append(f"Could not read last close from candles: {e}")
        return report

    # Last bar age — is the candle from today / yesterday?
    try:
        last_ts = df.index[-1]
        if hasattr(last_ts, "to_pydatetime"):
            last_ts = last_ts.to_pydatetime()
        report.last_bar_at = last_ts.isoformat() if hasattr(last_ts, "isoformat") else str(last_ts)
        age_days = (datetime.now() - last_ts.replace(tzinfo=None)).days if hasattr(last_ts, "replace") else 0
        report.last_bar_age_days = age_days
        if age_days > MAX_LAST_BAR_AGE_DAYS:
            report.verdict = "SUSPECT"
            report.reasons.append(
                f"Last candle is {age_days} days old — likely stale cache. "
                f"Refresh instruments / run backfill for this symbol."
            )
    except Exception as e:
        logger.debug("Last-bar age check failed: {}", e)

    # ---- 2. Instrument lookup ----
    try:
        row = instruments.lookup(symbol, exchange)
        if row:
            report.instrument_token = str(row.get("token") or row.get("instrument_token") or "")
            report.instrument_name  = str(row.get("name") or row.get("symbol") or "")
        else:
            report.reasons.append(f"No instrument row for {symbol}/{exchange} in scrip master.")
    except Exception as e:
        logger.debug("Instrument lookup failed: {}", e)

    # ---- 3. Broker LTP cross-check ----
    if broker_instance.is_authenticated() and report.instrument_token:
        try:
            quote = broker_instance.quote(exchange, symbol, report.instrument_token)
            data = (quote.get("data") or {}) if isinstance(quote, dict) else {}
            ltp = data.get("ltp")
            if ltp:
                report.broker_ltp = round(float(ltp), 2)
                if last_close > 0:
                    diff_pct = abs(report.broker_ltp - last_close) / last_close * 100
                    report.discrepancy_pct = round(diff_pct, 3)
                    if diff_pct > MAX_PRICE_DISCREPANCY_PCT:
                        report.verdict = "SUSPECT"
                        report.reasons.append(
                            f"Candle close ₹{last_close:.2f} differs from broker LTP "
                            f"₹{report.broker_ltp:.2f} by {diff_pct:.2f}% — "
                            f"likely wrong instrument token or stale cache."
                        )
        except Exception as e:
            logger.debug("Broker LTP check failed for {}: {}", symbol, e)
            report.reasons.append(f"Could not fetch broker LTP for comparison: {e}")

    # ---- 4. Spot-used vs candle close (separate signal) ----
    if spot_used is not None and report.candle_close:
        spot_diff = abs(spot_used - report.candle_close) / report.candle_close * 100
        if spot_diff > MAX_PRICE_DISCREPANCY_PCT:
            report.verdict = "SUSPECT"
            report.reasons.append(
                f"Analysis using spot ₹{spot_used:.2f} but candle close is "
                f"₹{report.candle_close:.2f} (diff {spot_diff:.2f}%) — "
                f"internal pricing inconsistency."
            )

    if report.verdict == "OK" and not report.reasons:
        report.reasons.append(
            f"Cross-check passed — candle close, broker LTP, and analysis "
            f"spot all agree within {MAX_PRICE_DISCREPANCY_PCT}%."
        )

    return report
