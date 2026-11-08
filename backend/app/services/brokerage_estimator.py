"""Brokerage / STT / GST / stamp duty estimator.

What this computes:

Indian retail trades have many small statutory fees. Most platforms only
show the trade notional ("buy 10 RELIANCE × ₹2,847 = ₹28,470"), leaving
users surprised when the broker debits ₹28,536. The difference is:

  • Brokerage (broker-specific)
  • STT / CTT (securities/commodities transaction tax)
  • Exchange transaction charges
  • SEBI charges
  • GST (18% on brokerage + transaction charges)
  • Stamp duty (paid on BUY side only)

We compute all of these per official rates as of April 2026. Rates can
change — this module documents the rate constants so audits are easy.

Reference: Zerodha, Angel One, Groww all publish identical rate sheets
(government-set). Difference between brokers is only the brokerage rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ============================================================================
# Statutory rate constants — change ONLY when government revises.
# Source: SEBI / NSE circulars + Income Tax Act provisions for STT.
# ============================================================================

# STT rates (Securities Transaction Tax) — as % of trade value
STT_EQUITY_DELIVERY  = 0.001     # 0.1% on both buy and sell — applied to each leg
STT_EQUITY_INTRADAY  = 0.00025   # 0.025% on the SELL side only
STT_OPTIONS_PREMIUM  = 0.001     # 0.1% on premium (sell side, options)
STT_OPTIONS_EXERCISE = 0.00125   # 0.125% on exercise (rare)
STT_FUTURES          = 0.0002    # 0.02% on the sell side

# Exchange transaction charges (NSE):
EXCH_EQUITY    = 0.0000325       # 0.00325% per leg
EXCH_FUTURES   = 0.0000173       # 0.00173% per leg
EXCH_OPTIONS   = 0.0003503       # 0.03503% on premium

# SEBI charges (very small)
SEBI_CHARGES_PCT = 0.0000010     # ₹10 per crore = 0.0001%

# GST — 18% on (brokerage + exchange charges + SEBI charges)
GST_RATE = 0.18

# Stamp duty (BUY side only — NSE-NSDL rates April 2026)
STAMP_EQUITY_DELIVERY = 0.00015  # 0.015%
STAMP_EQUITY_INTRADAY = 0.00003  # 0.003%
STAMP_FUTURES         = 0.00002  # 0.002%
STAMP_OPTIONS         = 0.00003  # 0.003%

# Default brokerage rates — Angel One's standard plan as of April 2026.
# Most retail discount brokers charge similar amounts.
BROKERAGE_EQUITY_DELIVERY_FLAT  = 0       # ₹0 (most discount brokers)
BROKERAGE_EQUITY_INTRADAY_FLAT  = 20      # ₹20 per executed order, capped
BROKERAGE_EQUITY_INTRADAY_PCT   = 0.0003  # 0.03% — whichever is lower
BROKERAGE_FNO_FLAT              = 20
BROKERAGE_FNO_PCT               = 0.0003


SegmentT = Literal["EQUITY_DELIVERY", "EQUITY_INTRADAY", "FUTURES", "OPTIONS"]


@dataclass
class CostBreakdown:
    notional:       float
    brokerage:      float
    stt:            float
    exchange_charges: float
    sebi_charges:   float
    gst:            float
    stamp_duty:     float
    total_charges:  float
    total_cost:     float            # notional + total_charges (BUY side perspective)
    breakdown_pct:  float            # total_charges / notional × 100
    segment:        str
    is_buy_side:    bool             # stamp duty only on BUY
    notes:          list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def estimate(*, entry: float, quantity: int, segment: SegmentT = "EQUITY_DELIVERY",
              direction: str = "BUY", lot_size: int = 1) -> CostBreakdown:
    """Compute all-in cost for one leg of a trade.

    Args:
      entry:     execution price per share/lot unit
      quantity:  number of shares (for equity) or lots (for F&O — multiply by lot_size internally)
      segment:   EQUITY_DELIVERY / EQUITY_INTRADAY / FUTURES / OPTIONS
      direction: BUY / SELL (STT and stamp duty differ by side)
      lot_size:  applies to F&O segments; ignored for equity (use quantity)

    For round-trip (buy + sell), call this twice and sum total_charges.
    """
    is_buy = direction == "BUY"
    units = quantity * lot_size if segment in ("FUTURES", "OPTIONS") else quantity
    notional = entry * units
    notes: list[str] = []

    # ----- Brokerage -----
    if segment == "EQUITY_DELIVERY":
        brokerage = float(BROKERAGE_EQUITY_DELIVERY_FLAT)
    elif segment == "EQUITY_INTRADAY":
        brokerage = min(
            BROKERAGE_EQUITY_INTRADAY_FLAT,
            notional * BROKERAGE_EQUITY_INTRADAY_PCT,
        )
    else:    # FUTURES / OPTIONS
        brokerage = min(BROKERAGE_FNO_FLAT, notional * BROKERAGE_FNO_PCT)

    # ----- STT (segment + side dependent) -----
    if segment == "EQUITY_DELIVERY":
        stt = notional * STT_EQUITY_DELIVERY    # applies both sides
    elif segment == "EQUITY_INTRADAY":
        stt = notional * STT_EQUITY_INTRADAY if not is_buy else 0    # sell-side only
    elif segment == "OPTIONS":
        stt = notional * STT_OPTIONS_PREMIUM if not is_buy else 0
        notes.append("STT on options is on premium, sell-side only. On exercise, "
                       "0.125% of intrinsic value also applies.")
    elif segment == "FUTURES":
        stt = notional * STT_FUTURES if not is_buy else 0
    else:
        stt = 0

    # ----- Exchange charges -----
    if segment in ("EQUITY_DELIVERY", "EQUITY_INTRADAY"):
        exch = notional * EXCH_EQUITY
    elif segment == "FUTURES":
        exch = notional * EXCH_FUTURES
    elif segment == "OPTIONS":
        exch = notional * EXCH_OPTIONS
    else:
        exch = 0

    # ----- SEBI charges -----
    sebi = notional * SEBI_CHARGES_PCT

    # ----- GST (18% on brokerage + exchange + sebi) -----
    gst = (brokerage + exch + sebi) * GST_RATE

    # ----- Stamp duty (BUY side only) -----
    if is_buy:
        if segment == "EQUITY_DELIVERY":
            stamp = notional * STAMP_EQUITY_DELIVERY
        elif segment == "EQUITY_INTRADAY":
            stamp = notional * STAMP_EQUITY_INTRADAY
        elif segment == "FUTURES":
            stamp = notional * STAMP_FUTURES
        elif segment == "OPTIONS":
            stamp = notional * STAMP_OPTIONS
        else:
            stamp = 0
    else:
        stamp = 0

    total_charges = brokerage + stt + exch + sebi + gst + stamp
    total_cost = notional + total_charges if is_buy else notional - total_charges
    pct = total_charges / max(notional, 1) * 100

    if pct > 1.0:
        notes.append(f"Charges are {pct:.2f}% of notional — high. For small-ticket "
                       f"trades the fixed brokerage component dominates.")

    return CostBreakdown(
        notional=round(notional, 2),
        brokerage=round(brokerage, 2),
        stt=round(stt, 2),
        exchange_charges=round(exch, 2),
        sebi_charges=round(sebi, 2),
        gst=round(gst, 2),
        stamp_duty=round(stamp, 2),
        total_charges=round(total_charges, 2),
        total_cost=round(total_cost, 2),
        breakdown_pct=round(pct, 3),
        segment=segment,
        is_buy_side=is_buy,
        notes=notes,
    )


def estimate_round_trip(*, entry: float, exit_: float, quantity: int,
                          segment: SegmentT = "EQUITY_DELIVERY",
                          lot_size: int = 1) -> dict:
    """Both legs (buy + sell). Useful for "what does this trade actually
    cost me end-to-end?" calculations."""
    buy  = estimate(entry=entry, quantity=quantity, segment=segment, direction="BUY", lot_size=lot_size)
    sell = estimate(entry=exit_, quantity=quantity, segment=segment, direction="SELL", lot_size=lot_size)
    total_charges = buy.total_charges + sell.total_charges
    gross_pnl = (exit_ - entry) * (quantity * lot_size if segment in ("FUTURES", "OPTIONS") else quantity)
    net_pnl   = gross_pnl - total_charges
    return {
        "buy":            buy.to_dict(),
        "sell":           sell.to_dict(),
        "total_charges":  round(total_charges, 2),
        "gross_pnl":      round(gross_pnl, 2),
        "net_pnl":        round(net_pnl, 2),
        "breakeven_pct":  round(total_charges / buy.notional * 100, 3) if buy.notional else 0,
    }
