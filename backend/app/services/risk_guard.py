"""Risk Guard — the discipline-enforcer layer.

Why this exists:

SEBI's own studies: 89% of equity-F&O retail traders lose money. The root
cause is not bad stock picks — it's poor risk management. Specifically:
  • Oversizing positions (using 10-20% of capital on one trade)
  • No stop-loss
  • Doubling-down after losses (revenge trading)
  • Holding losers indefinitely
  • Closing winners too early

This service enforces hard limits on the recommendation layer so the system
literally cannot suggest a position that violates safe-trading rules.

Three load-bearing guards:

1. POSITION SIZING — cap risk at 2% of capital per trade
   (risk = (entry - stoploss) × quantity)
   If a recommendation's stoploss is too far from entry, quantity is reduced
   until risk ≤ 2%. If the smallest viable size already violates, the
   recommendation is downgraded to WAIT.

2. PORTFOLIO RISK CAP — cap total open risk at 6% of capital
   Across all active positions in the user's portfolio. New positions that
   would push total risk above 6% are refused (or downgraded to WAIT).

3. LOSS CIRCUIT BREAKER — block new positions after consecutive losses
   3 losing trades in last 5 trading days → "step back" warning. 5 losses
   in 5 days → all new BUY/SELL recommendations downgraded to WAIT until
   next calendar day.

The output structure is non-opinionated: this service returns a `RiskGuard`
dataclass with the guard verdict. Callers decide whether to enforce it (the
recommendation endpoint does; standalone analyzer endpoints don't).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger


# Hard policy constants. Conservative by design — these are the limits at
# which catastrophic account loss becomes statistically unlikely.
MAX_RISK_PER_TRADE_PCT     = 2.0      # ≤2% of capital at risk per trade
MAX_PORTFOLIO_OPEN_RISK_PCT = 6.0      # ≤6% total open risk
LOSS_WARNING_THRESHOLD     = 3         # 3 losses in N days → warning
LOSS_CIRCUIT_THRESHOLD     = 5         # 5 losses in N days → block new entries
LOSS_LOOKBACK_DAYS         = 5
MIN_RR_RATIO               = 1.2       # require at least 1.2:1 reward:risk


@dataclass
class RiskGuard:
    """Output of `check()` — describes how the recommendation should be
    presented and whether it should be acted on."""

    # Sizing
    suggested_quantity: int            # number of shares/lots (cap-respecting)
    risk_amount_rs: float              # money at risk if SL hits, in ₹
    risk_pct_of_capital: float
    risk_reward_ratio: float           # (target1 - entry) / (entry - SL)

    # Verdict
    verdict: str                       # OK / DOWNGRADE_WAIT / BLOCK
    severity: str                      # info / warning / critical
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Portfolio context
    portfolio_open_risk_pct: float = 0.0
    portfolio_room_remaining_pct: float = 0.0

    # Behavioral context
    recent_losses: int = 0
    in_loss_warning: bool = False
    in_circuit_breaker: bool = False

    def to_dict(self) -> dict:
        return self.__dict__


def check(
    *,
    entry: float,
    stoploss: float,
    target_1: float,
    capital: float,
    lot_size: int = 1,
    open_positions_risk_pct: float = 0.0,
    recent_losses: int = 0,
) -> RiskGuard:
    """Compute the risk-guarded recommendation.

    Args:
      entry:               Recommended entry price
      stoploss:            Recommended stop-loss price
      target_1:            First target price (used for R:R math)
      capital:             User's capital in ₹
      lot_size:            Equity = 1, F&O = market lot size
      open_positions_risk_pct:  Currently-open risk across all positions, % of capital
      recent_losses:       Number of losing closes in the lookback window
    """
    if entry <= 0 or capital <= 0 or stoploss <= 0:
        return RiskGuard(
            suggested_quantity=0, risk_amount_rs=0, risk_pct_of_capital=0,
            risk_reward_ratio=0, verdict="BLOCK", severity="critical",
            reasons=["Invalid entry/SL/capital — cannot compute sizing"],
        )

    # ----- Direction-aware distance calcs -----
    # BUY: SL below entry; SELL: SL above entry
    is_long = stoploss < entry
    sl_distance = abs(entry - stoploss)
    target_distance = abs(target_1 - entry)
    if sl_distance == 0:
        return RiskGuard(
            suggested_quantity=0, risk_amount_rs=0, risk_pct_of_capital=0,
            risk_reward_ratio=0, verdict="BLOCK", severity="critical",
            reasons=["Stop-loss equals entry — zero distance, refused"],
        )

    rr = round(target_distance / sl_distance, 2) if sl_distance > 0 else 0

    # ----- Position sizing -----
    # Max ₹ at risk = MAX_RISK_PER_TRADE_PCT% of capital
    max_risk_rupees = capital * (MAX_RISK_PER_TRADE_PCT / 100)
    # Quantity that respects this cap
    raw_qty = int(max_risk_rupees / sl_distance)
    qty = (raw_qty // lot_size) * lot_size   # round down to lot size
    qty = max(qty, 0)

    actual_risk_rs = qty * sl_distance
    actual_risk_pct = (actual_risk_rs / capital) * 100 if capital > 0 else 0

    warnings: list[str] = []
    reasons: list[str] = []
    verdict = "OK"
    severity = "info"

    # ----- Hard sizing failure -----
    if qty == 0:
        verdict = "BLOCK"
        severity = "critical"
        reasons.append(
            f"Cannot size position safely — even one {('share' if lot_size == 1 else 'lot')} "
            f"would risk ₹{sl_distance * lot_size:.0f} ({sl_distance * lot_size / capital * 100:.2f}% "
            f"of capital, over the {MAX_RISK_PER_TRADE_PCT}% per-trade limit). "
            f"Either increase capital or wait for a setup with a tighter stop."
        )
        return RiskGuard(
            suggested_quantity=0, risk_amount_rs=0, risk_pct_of_capital=0,
            risk_reward_ratio=rr, verdict=verdict, severity=severity,
            reasons=reasons,
            recent_losses=recent_losses,
        )

    # ----- Reward/risk ratio guard -----
    if rr < MIN_RR_RATIO:
        warnings.append(
            f"Reward:risk only {rr}:1 (below {MIN_RR_RATIO}:1 floor). "
            f"Setup not worth taking — small win, small loss expected value is near zero."
        )
        verdict = "DOWNGRADE_WAIT"
        severity = "warning"

    # ----- Portfolio open-risk cap -----
    proposed_total_risk = open_positions_risk_pct + actual_risk_pct
    room_remaining = max(0, MAX_PORTFOLIO_OPEN_RISK_PCT - open_positions_risk_pct)

    if proposed_total_risk > MAX_PORTFOLIO_OPEN_RISK_PCT:
        # Block — total open risk would exceed safe limit
        if open_positions_risk_pct >= MAX_PORTFOLIO_OPEN_RISK_PCT:
            verdict = "BLOCK"
            severity = "critical"
            reasons.append(
                f"Portfolio already at {open_positions_risk_pct:.1f}% open risk "
                f"(max {MAX_PORTFOLIO_OPEN_RISK_PCT}%). Close an existing position before opening a new one."
            )
        else:
            # We could downsize qty to fit remaining room
            shrunk_risk_rupees = capital * (room_remaining / 100)
            shrunk_raw_qty = int(shrunk_risk_rupees / sl_distance)
            shrunk_qty = (shrunk_raw_qty // lot_size) * lot_size
            if shrunk_qty == 0:
                verdict = "BLOCK"
                severity = "critical"
                reasons.append(
                    f"Only {room_remaining:.1f}% portfolio risk room remaining "
                    f"— not enough for one viable {'share' if lot_size == 1 else 'lot'} of this setup."
                )
            else:
                qty = shrunk_qty
                actual_risk_rs = qty * sl_distance
                actual_risk_pct = (actual_risk_rs / capital) * 100
                warnings.append(
                    f"Position size reduced to fit portfolio risk budget "
                    f"(was {raw_qty} → now {qty} to respect {MAX_PORTFOLIO_OPEN_RISK_PCT}% cap)."
                )
                if severity != "critical":
                    severity = "warning"

    # ----- Behavioral circuit breaker -----
    in_warning = recent_losses >= LOSS_WARNING_THRESHOLD
    in_breaker = recent_losses >= LOSS_CIRCUIT_THRESHOLD

    if in_breaker:
        verdict = "BLOCK"
        severity = "critical"
        reasons.append(
            f"Loss circuit breaker active — {recent_losses} losses in last "
            f"{LOSS_LOOKBACK_DAYS} trading days. Step back today. Tomorrow's session resets this counter."
        )
    elif in_warning:
        warnings.append(
            f"⚠ {recent_losses} losing trades in last {LOSS_LOOKBACK_DAYS} sessions. "
            f"Consider sizing this trade smaller than usual, or waiting for a clearer setup."
        )
        if severity == "info":
            severity = "warning"

    # Summary reason
    if verdict == "OK":
        reasons.append(
            f"Position sizing OK: {qty} {'shares' if lot_size == 1 else 'lots'} × "
            f"₹{sl_distance:.2f} SL = ₹{actual_risk_rs:.0f} risk "
            f"({actual_risk_pct:.2f}% of ₹{capital:,.0f} capital). R:R {rr}:1."
        )

    return RiskGuard(
        suggested_quantity=qty,
        risk_amount_rs=round(actual_risk_rs, 2),
        risk_pct_of_capital=round(actual_risk_pct, 3),
        risk_reward_ratio=rr,
        verdict=verdict,
        severity=severity,
        reasons=reasons,
        warnings=warnings,
        portfolio_open_risk_pct=round(open_positions_risk_pct, 2),
        portfolio_room_remaining_pct=round(room_remaining, 2),
        recent_losses=recent_losses,
        in_loss_warning=in_warning,
        in_circuit_breaker=in_breaker,
    )


# ---------------------------------------------------------------------------
# Helpers to compute the context fields (portfolio open risk, recent losses)
# from existing tables. Both are read-only and cheap; safe to call inline.
# ---------------------------------------------------------------------------

def open_portfolio_risk_pct(db, user_id: int, capital: float) -> float:
    """Sum risk-at-stop across the user's active portfolio positions.
    Returns a percent of capital figure.

    Defensive: if the portfolio model is unavailable / table empty, returns 0.
    """
    try:
        from app.models.portfolio import Position    # type: ignore
        positions = db.query(Position).filter_by(user_id=user_id, status="OPEN").all()
        if not positions or capital <= 0:
            return 0.0
        total_risk = 0.0
        for p in positions:
            sl_dist = abs((p.entry_price or 0) - (p.stop_loss or 0))
            total_risk += sl_dist * (p.quantity or 0)
        return round(total_risk / capital * 100, 3)
    except Exception as e:
        logger.debug("open_portfolio_risk_pct unavailable: {}", e)
        return 0.0


def recent_loss_count(db, user_id: int, lookback_days: int = LOSS_LOOKBACK_DAYS) -> int:
    """Count closed-losing trades for the user in the lookback window."""
    try:
        from app.models.portfolio import Position    # type: ignore
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        rows = (db.query(Position)
                  .filter(Position.user_id == user_id,
                           Position.status == "CLOSED",
                           Position.closed_at >= cutoff,
                           Position.realized_pnl < 0)
                  .count())
        return int(rows)
    except Exception as e:
        logger.debug("recent_loss_count unavailable: {}", e)
        return 0
