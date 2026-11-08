#!/usr/bin/env python3
"""Migration verifier — inspects the live DB and reports which migrations
have been applied vs. which still need to run.

Designed for the EC2 deployment workflow:

    cd backend
    source .venv/bin/activate
    python scripts/verify_migrations.py

The script does NOT modify the database. It just connects, looks at the
schema, and prints a clear "applied / pending" report so you know what to
run next.

Each migration in `backend/migrations/` is identified by checking for a
*signature* — a table, column, or index it should have added. If the
signature exists, the migration is "applied". If not, the migration is
"pending" and you need to run it.

Exit codes:
  0 → all migrations applied (DB is up-to-date)
  1 → one or more migrations pending (DB needs work)
  2 → could not connect to database
"""
from __future__ import annotations

import sys
from typing import Callable

# Add backend root to import path so this script works from anywhere
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _check_table(insp, table: str) -> bool:
    try:
        return table in set(insp.get_table_names())
    except Exception:
        return False


def _check_column(insp, table: str, column: str) -> bool:
    try:
        cols = {c["name"] for c in insp.get_columns(table)}
        return column in cols
    except Exception:
        return False


def _check_index(insp, table: str, index_name: str) -> bool:
    try:
        idx = {ix["name"] for ix in insp.get_indexes(table)}
        return index_name in idx
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Migration registry
# Each entry: (id, description, list of (signature_label, check_fn) tuples)
# A migration is "applied" iff ALL its signatures pass.
# ----------------------------------------------------------------------------

def _migrations(insp) -> list[dict]:
    return [
        {
            "id": "002_migrate_from_sqlite",
            "desc": "Initial postgres schema (users, subscriptions, etc.)",
            "signatures": [
                ("users table",         lambda: _check_table(insp, "users")),
                ("subscriptions table", lambda: _check_table(insp, "subscriptions")),
                ("watchlist_items table", lambda: _check_table(insp, "watchlist_items")),
            ],
        },
        {
            "id": "003_apply_recent_schema",
            "desc": "Trade execution tables + per-user trading kill switch",
            "signatures": [
                ("exec_orders table",        lambda: _check_table(insp, "exec_orders")),
                ("exec_positions table",     lambda: _check_table(insp, "exec_positions")),
                ("exec_trade_fills table",   lambda: _check_table(insp, "exec_trade_fills")),
                ("users.trading_enabled",    lambda: _check_column(insp, "users", "trading_enabled")),
                ("live_picks_snapshots table", lambda: _check_table(insp, "live_picks_snapshots")),
            ],
        },
        {
            "id": "004_per_user_broker_sessions",
            "desc": "Per-user encrypted broker credentials",
            "signatures": [
                ("broker_sessions table", lambda: _check_table(insp, "broker_sessions")),
            ],
        },
        {
            "id": "005_multi_leg_columns",
            "desc": "Multi-leg order grouping (option spreads, condors)",
            "signatures": [
                ("exec_orders.multi_leg_group_id", lambda: _check_column(insp, "exec_orders", "multi_leg_group_id")),
                ("exec_orders.leg_index",          lambda: _check_column(insp, "exec_orders", "leg_index")),
            ],
        },
    ]


def main() -> int:
    print("=" * 70)
    print("MarketLens — Migration Verifier")
    print("=" * 70)

    try:
        from sqlalchemy import inspect
        from app.database import engine
        # Import the models so SQLAlchemy knows about every table
        from app.models import (                                    # noqa: F401
            user, subscription, watchlist, signals_journal, audit_log,
            live_picks, trade_execution,
        )
    except Exception as e:
        print(f"\nERROR: could not import app modules — {e}")
        print("Tip: run from the `backend/` directory with the venv activated.")
        return 2

    try:
        insp = inspect(engine)
        # Trigger a connection to surface DB connectivity issues early
        engine.connect().close()
    except Exception as e:
        print(f"\nERROR: could not connect to database — {e}")
        print(f"DATABASE_URL is: {engine.url}")
        return 2

    print(f"\nDatabase: {engine.url}")
    print(f"Tables found: {len(insp.get_table_names())}")
    print()

    migrations = _migrations(insp)
    applied_count = 0
    pending: list[tuple[str, list[str]]] = []

    for m in migrations:
        results = [(label, fn()) for label, fn in m["signatures"]]
        all_ok = all(ok for _, ok in results)
        missing = [label for label, ok in results if not ok]

        if all_ok:
            status = "✓ APPLIED"
            color  = "\033[32m"          # green
            applied_count += 1
        else:
            status = "✗ PENDING"
            color  = "\033[31m"          # red
            pending.append((m["id"], missing))

        reset = "\033[0m"
        print(f"  {color}{status}{reset}  {m['id']}")
        print(f"            {m['desc']}")
        for label, ok in results:
            mark = "✓" if ok else "·"
            print(f"              {mark}  {label}")
        print()

    print("=" * 70)
    print(f"Summary: {applied_count}/{len(migrations)} migrations applied")
    print("=" * 70)

    if pending:
        print("\nPending migrations — run each in order:")
        for mid, _ in pending:
            print(f"  python migrations/{mid}.py")
        print()
        print("After running, re-run this script to confirm.")
        return 1

    print("\nAll migrations applied. Schema is up-to-date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
