from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import risk_guard


def _db_with(positions=None, count=0):
    db = MagicMock()
    q = db.query.return_value.filter.return_value
    q.all.return_value = positions or []
    q.count.return_value = count
    return db


def test_open_risk_uses_real_position_model():
    pos = SimpleNamespace(avg_entry_price=100.0, current_sl=95.0, net_quantity=10)
    # risk = 5 * 10 = 50 -> 0.5% of 10,000
    assert risk_guard.open_portfolio_risk_pct(_db_with([pos]), 1, 10_000) == 0.5


def test_open_risk_missing_stop_counts_full_notional():
    pos = SimpleNamespace(avg_entry_price=100.0, current_sl=None, net_quantity=10)
    # 100 * 10 = 1000 -> 10% of 10,000 (fail closed)
    assert risk_guard.open_portfolio_risk_pct(_db_with([pos]), 1, 10_000) == 10.0


def test_recent_loss_count_uses_real_position_model():
    assert risk_guard.recent_loss_count(_db_with(count=3), 1) == 3
