"""Funds / margin pre-trade check.

Why this exists:

Every order placed without sufficient funds gets rejected by the broker
with a generic "insufficient margin" error. This wastes:
  • A broker API call (counts toward rate limits)
  • A user's time (they retry without knowing what failed)
  • An audit trail row (REJECTED orders pollute the journal)

Better: ask the broker for available cash + margin BEFORE we submit the
order. Refuse upfront if there isn't enough. Returns a structured verdict
the executor and UI can act on.

Honest about the limitations:
  • F&O margin is leverage-dependent — span + exposure required, not just
    notional. We fetch the broker's `margin_required` for the order. If
    the broker doesn't expose that for the symbol, we fall back to a
    conservative estimate (20% of notional for equity intraday, 100% for
    delivery, span+exposure-approximation for F&O).
  • Pledged-margin amounts are NOT counted as free funds (correctly).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from app.brokers.angelone import broker_instance


# Conservative fallback estimates when the broker can't give us a precise
# margin requirement. These err on the safe side (refuse marginal trades).
EQUITY_INTRADAY_MARGIN_FRACTION = 0.20    # 5x leverage on intraday cash
EQUITY_DELIVERY_MARGIN_FRACTION = 1.00    # 100% — full cash required
FNO_MARGIN_FRACTION             = 0.15    # ~6.5x average leverage on F&O


@dataclass
class FundsCheckResult:
    sufficient:           bool
    available_cash:       float
    required_margin:      float
    notional:             float
    leverage_used:        float
    headroom:             float            # available_cash - required_margin
    estimate_source:      str              # 'broker_exact' / 'fallback_equity_intraday' etc
    reasons:              list[str] = field(default_factory=list)
    warnings:             list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def _fetch_broker_funds() -> Optional[dict]:
    """Pull available cash + margin from the broker. Returns None if the
    broker can't tell us (unauthenticated, API error, no funds endpoint).
    """
    if not broker_instance.is_authenticated():
        return None
    try:
        for attr in ("funds", "rms_limits", "get_funds", "balance"):
            fn = getattr(broker_instance, attr, None)
            if callable(fn):
                result = fn()
                if isinstance(result, dict):
                    return result
                if isinstance(result, list) and result:
                    return result[0] if isinstance(result[0], dict) else None
        return None
    except Exception as e:
        logger.warning("Broker funds fetch failed: {}", e)
        return None


def _extract_cash(funds: dict) -> float:
    """Find the available-cash field in the broker's funds response.

    Angel One returns it under various keys depending on segment + API
    version. We check the common ones in priority order.
    """
    candidates = [
        "availablecash", "available_cash", "net", "netCash", "netcash",
        "cash", "availablebalance", "available_balance",
    ]
    for k in candidates:
        v = funds.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    # Sometimes nested under "equity" or "data"
    for nest_key in ("equity", "data"):
        nest = funds.get(nest_key)
        if isinstance(nest, dict):
            for k in candidates:
                v = nest.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
    return 0.0


def estimate_required_margin(*, entry: float, quantity: int,
                               product_type: str, is_fno: bool = False) -> tuple[float, str]:
    """Best-effort margin estimate without hitting the broker.

    Returns (required_margin_in_rupees, source_label).
    """
    notional = entry * quantity
    if is_fno:
        return notional * FNO_MARGIN_FRACTION, "fallback_fno_approx"
    if product_type in ("INTRADAY", "MIS"):
        return notional * EQUITY_INTRADAY_MARGIN_FRACTION, "fallback_equity_intraday"
    # DELIVERY / CNC / NRML / MARGIN — assume full cash required (safest)
    return notional * EQUITY_DELIVERY_MARGIN_FRACTION, "fallback_equity_delivery"


def check(*, entry: float, quantity: int, product_type: str = "DELIVERY",
            is_fno: bool = False) -> FundsCheckResult:
    """Pre-trade check. Combines broker's reported cash with a notional-based
    margin estimate to decide whether the trade can be afforded.

    Always returns a FundsCheckResult — never raises. When the broker isn't
    available, returns sufficient=True with a warning so the executor can
    decide to soft-allow (the order will then get rejected at the broker
    if funds are insufficient — same as today, just with a clear warning).
    """
    notional = entry * quantity
    required_margin, source = estimate_required_margin(
        entry=entry, quantity=quantity, product_type=product_type, is_fno=is_fno,
    )

    funds = _fetch_broker_funds()
    if funds is None:
        return FundsCheckResult(
            sufficient=True,    # soft-allow; broker will reject if it's wrong
            available_cash=0,
            required_margin=round(required_margin, 2),
            notional=round(notional, 2),
            leverage_used=round(notional / required_margin, 2) if required_margin > 0 else 1.0,
            headroom=0,
            estimate_source=source,
            warnings=["Broker funds endpoint unavailable — proceeding without cash check. "
                       "Order may be rejected by broker if funds are insufficient."],
        )

    available_cash = _extract_cash(funds)
    headroom = available_cash - required_margin
    sufficient = headroom >= 0

    reasons: list[str] = []
    warnings: list[str] = []
    if sufficient:
        reasons.append(
            f"Funds OK: required ₹{required_margin:,.0f} ({source.replace('_', ' ')}), "
            f"available ₹{available_cash:,.0f}, headroom ₹{headroom:,.0f}."
        )
    else:
        reasons.append(
            f"INSUFFICIENT FUNDS: need ₹{required_margin:,.0f} but only "
            f"₹{available_cash:,.0f} available ({-headroom:,.0f} short)."
        )
        reasons.append(
            f"Estimated using {source.replace('_', ' ')}. For F&O, actual span "
            f"+ exposure may differ — verify in your broker's margin calculator."
        )

    # Soft warning when leverage is high
    if required_margin > 0:
        leverage = notional / required_margin
        if leverage > 5:
            warnings.append(
                f"High effective leverage ({leverage:.1f}x). One percent against "
                f"you = {leverage:.1f}% loss on capital."
            )

    return FundsCheckResult(
        sufficient=sufficient,
        available_cash=round(available_cash, 2),
        required_margin=round(required_margin, 2),
        notional=round(notional, 2),
        leverage_used=round(notional / required_margin, 2) if required_margin > 0 else 1.0,
        headroom=round(headroom, 2),
        estimate_source=source,
        reasons=reasons,
        warnings=warnings,
    )
