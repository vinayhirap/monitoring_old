# apply_round5.py -- run from D:\Project\monitoring_old (dry run unless --apply)
import re, sys, pathlib

APPLY = "--apply" in sys.argv
ROOT = pathlib.Path(__file__).resolve().parent
B = ROOT / "backend"


def _read(p):
    with open(p, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    return raw.replace("\r\n", "\n"), ("\r\n" in raw)


def _write(p, s, crlf):
    if crlf:
        s = s.replace("\n", "\r\n")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)


def patch(rel, old, new, label):
    p = B / rel
    if not p.exists():
        print(f"  MISSING   {rel}")
        return 0
    s, crlf = _read(p)
    if new in s:
        print(f"  ALREADY   {label}")
        return 0
    if s.count(old) != 1:
        print(f"  NO MATCH  {label}  (found {s.count(old)}x; patch manually)")
        return 0
    print(f"  APPLIED   {label}")
    if APPLY:
        _write(p, s.replace(old, new, 1), crlf)
    return 1


def write_new(rel, text):
    p = B / rel
    if p.exists():
        print(f"  SKIP (exists)   {rel}")
        return 0
    print(f"  APPLIED (new)   {rel}")
    if APPLY:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return 1


def replace_function(rel, name, new_src, marker, label):
    """Replace a whole top-level function (up to the next top-level line) with new_src."""
    p = B / rel
    if not p.exists():
        print(f"  MISSING   {rel}")
        return 0
    s, crlf = _read(p)
    if marker in s.split(f"def {name}(", 1)[-1][:900] and f"def {name}(" in s:
        print(f"  ALREADY   {label}")
        return 0
    m = re.search(r"^def %s\(.*?(?=^\S|\Z)" % re.escape(name), s, re.M | re.S)
    if not m:
        print(f"  NO MATCH  {label}")
        return 0
    old = m.group(0)
    trailing = old[len(old.rstrip()):]
    print(f"  APPLIED   {label}")
    if APPLY:
        _write(p, s[:m.start()] + new_src.rstrip() + trailing + s[m.end():], crlf)
    return 1


OPEN_RISK = '''def open_portfolio_risk_pct(db, user_id: int, capital: float) -> float:
    """Sum risk-at-stop across the user's OPEN positions, as a percent of capital.

    Uses app.models.trade_execution.Position (exec_positions). A position with no
    stop on file is treated as full notional at risk (fail closed).
    """
    if capital <= 0:
        return 0.0
    try:
        from app.models.trade_execution import Position
        positions = (db.query(Position)
                       .filter(Position.user_id == user_id, Position.status == "OPEN")
                       .all())
        total_risk = 0.0
        for p in positions:
            entry = p.avg_entry_price or 0.0
            qty = abs(p.net_quantity or 0)
            sl = p.current_sl
            sl_dist = abs(entry - sl) if sl else entry
            total_risk += sl_dist * qty
        return round(total_risk / capital * 100, 3)
    except Exception as e:
        logger.warning("open_portfolio_risk_pct failed - portfolio-risk check SKIPPED: {}", e)
        return 0.0
'''

RECENT_LOSS = '''def recent_loss_count(db, user_id: int, lookback_days: int = LOSS_LOOKBACK_DAYS) -> int:
    """Count closed-losing positions for the user in the lookback window."""
    try:
        from app.models.trade_execution import Position
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        rows = (db.query(Position)
                  .filter(Position.user_id == user_id,
                          Position.status == "CLOSED",
                          Position.closed_at >= cutoff,
                          Position.realized_pnl < 0)
                  .count())
        return int(rows)
    except Exception as e:
        logger.warning("recent_loss_count failed - loss-streak check SKIPPED: {}", e)
        return 0
'''

TEST_RISK = '''from types import SimpleNamespace
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
'''

n = 0

# MEDIUM: fallback path also divides by entry
n += patch(
    "app/engines/stop_loss_engine.py",
    "round(fallback_distance / entry * 100, 3)",
    "(round(fallback_distance / entry * 100, 3) if entry > 0 else 0.0)",
    "stop_loss_engine: guard entry<=0 in fallback distance_pct",
)

# HIGH: risk_guard imported a non-existent model, so both guards silently returned 0
n += replace_function("app/services/risk_guard.py", "open_portfolio_risk_pct", OPEN_RISK,
                      "trade_execution import Position", "risk_guard: open_portfolio_risk_pct -> exec_positions")
n += replace_function("app/services/risk_guard.py", "recent_loss_count", RECENT_LOSS,
                      "trade_execution import Position", "risk_guard: recent_loss_count -> exec_positions")
n += write_new("tests/test_risk_guard_portfolio.py", TEST_RISK)

# LOW: test sat on the iv<18 boundary (iv=18 now selects a spread, which uses an ATR-only stop).
# Point it at the directional branch it documents.
n += patch(
    "tests/test_strategy_entry.py",
    'atr=2.0, iv_pct=18.0,\n            horizon="SWING", capital=100_000,\n            gann_support=104.0, gann_resistance=120.0,',
    'atr=2.0, iv_pct=16.0,\n            horizon="SWING", capital=100_000,\n            gann_support=104.0, gann_resistance=120.0,',
    "test_strategy_entry: use low IV so the structural-stop branch is exercised",
)

print(f"\n{'Wrote' if APPLY else 'DRY RUN -'} {n} change(s)." + ("" if APPLY else " Re-run with --apply."))
