"""Risk-management helpers."""
from app.config import settings


def position_size(capital: float, entry: float, stoploss: float,
                  max_position_pct: float | None = None,
                  max_risk_pct: float = 1.0) -> int:
    """Return integer share quantity sized to risk `max_risk_pct` of capital
    (Kelly-lite cap), bounded by `max_position_pct` of capital exposure.
    """
    max_position_pct = max_position_pct or settings.risk_max_position_pct
    risk_per_share = abs(entry - stoploss)
    if risk_per_share <= 0 or entry <= 0:
        return 0
    risk_capital = capital * (max_risk_pct / 100)
    qty_by_risk = int(risk_capital // risk_per_share)
    max_exposure = capital * (max_position_pct / 100)
    qty_by_exposure = int(max_exposure // entry)
    return max(0, min(qty_by_risk, qty_by_exposure))


def daily_loss_breach(today_pnl: float, capital: float) -> bool:
    return today_pnl < 0 and abs(today_pnl) > capital * (settings.risk_max_daily_loss_pct / 100)
