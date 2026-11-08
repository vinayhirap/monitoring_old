#!/usr/bin/env python3
"""Apply schema changes added in recent code: new exec_* tables + new
columns on existing tables.

This script is idempotent — running it twice is safe. It uses
`Base.metadata.create_all()` for new tables (which is a no-op if the
table already exists), and discrete ALTER TABLE statements wrapped in
try/except for column additions.

What this script applies:

  1. **NEW TABLES** (from app.models.trade_execution):
     • exec_orders        — order intents + lifecycle
     • exec_positions     — open positions
     • exec_trade_fills   — atomic fills
  2. **NEW TABLE** (from app.models.live_picks):
     • live_picks_snapshots — scanner cache
  3. **NEW COLUMN**: users.trading_enabled BOOLEAN DEFAULT FALSE
     — per-user kill switch. Defaults to false so existing users start
     with trading OFF and must explicitly enable.

How to run (on EC2 after a deploy):

    cd backend
    source venv/bin/activate
    python migrations/003_apply_recent_schema.py

Safe to run multiple times. Logs every step.
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect, text
from loguru import logger


def main() -> int:
    # Import these inside main so a partial import doesn't crash the script
    from app.database import Base, engine
    # Importing the models registers them with Base.metadata
    from app.models import user, subscription, watchlist, signals_journal, audit_log
    from app.models import live_picks                # NEW
    from app.models import trade_execution           # NEW (exec_orders, exec_positions, exec_trade_fills)

    print("=" * 70)
    print("Applying schema migration #003")
    print(f"Database: {engine.url}")
    print("=" * 70)

    # ----- Step 1. create_all() — idempotent for any new tables -----
    print("\n[1/3] Running Base.metadata.create_all() ...")
    try:
        Base.metadata.create_all(engine)
        print("      OK — new tables created where missing.")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    # ----- Step 2. Check + add users.trading_enabled column -----
    print("\n[2/3] Checking users.trading_enabled column ...")
    try:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("users")}
        if "trading_enabled" in cols:
            print("      OK — column already present.")
        else:
            print("      Adding column ...")
            with engine.begin() as conn:
                dialect = conn.dialect.name
                if dialect == "sqlite":
                    # SQLite needs a default literal, not server_default
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN trading_enabled BOOLEAN DEFAULT 0"
                    ))
                else:
                    conn.execute(text(
                        "ALTER TABLE users ADD COLUMN trading_enabled BOOLEAN DEFAULT FALSE"
                    ))
                # Ensure all existing rows have an explicit false (some DBs leave NULL)
                conn.execute(text(
                    "UPDATE users SET trading_enabled = 0 WHERE trading_enabled IS NULL"
                    if dialect == "sqlite" else
                    "UPDATE users SET trading_enabled = FALSE WHERE trading_enabled IS NULL"
                ))
            print("      OK — column added, existing users default to trading OFF.")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    # ----- Step 3. Verify all expected tables exist -----
    print("\n[3/3] Verifying schema ...")
    expected = [
        "users", "subscriptions", "watchlist_items",
        "signals_journal", "audit_log_entries",
        "exec_orders", "exec_positions", "exec_trade_fills",
        "live_picks_snapshots",
    ]
    try:
        insp = inspect(engine)
        actual = set(insp.get_table_names())
        missing = [t for t in expected if t not in actual]
        if missing:
            print(f"      WARNING — expected tables missing: {missing}")
            print("      Re-run after fixing model imports.")
            return 1
        print(f"      OK — all {len(expected)} expected tables present.")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    print("\n" + "=" * 70)
    print("Migration #003 complete.")
    print()
    print("Next steps:")
    print("  • Restart the backend so SQLAlchemy picks up the new schema.")
    print("  • New users get trading_enabled=False — they must opt in.")
    print("  • Existing live OPEN orders will start being polled every 30s.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
