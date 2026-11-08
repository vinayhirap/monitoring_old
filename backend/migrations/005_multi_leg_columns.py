#!/usr/bin/env python3
"""Add multi_leg_group_id + leg_index columns to exec_orders.

These columns enable atomic placement of option spreads, condors, and
straddles — the trade_executor.execute_multi_leg() function tags every
leg of a basket with the same group_id so:

  • Partial-failure rollback can find the placed legs and reverse them
  • The UI can render N broker rows as a single "trade basket" card
  • Reports can aggregate P&L across the whole strategy

Both columns are nullable. Single-leg orders leave them NULL — fully
backward compatible. Index added for efficient leg lookup.

Idempotent — safe to run multiple times. Logs every step.

How to run (on EC2 after a deploy):

    cd backend
    source .venv/bin/activate
    python migrations/005_multi_leg_columns.py
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect, text


def main() -> int:
    from app.database import engine
    # Importing the models so we can verify the column appears in the metadata
    from app.models import trade_execution                          # noqa: F401

    print("=" * 70)
    print("Applying schema migration #005 — multi-leg order columns")
    print(f"Database: {engine.url}")
    print("=" * 70)

    insp = inspect(engine)
    if "exec_orders" not in set(insp.get_table_names()):
        print("ERROR: table `exec_orders` does not exist.")
        print("       Run migration 003 first.")
        return 1

    existing_cols = {c["name"] for c in insp.get_columns("exec_orders")}
    dialect = engine.dialect.name

    # ----- Add multi_leg_group_id column -----
    print("\n[1/3] Checking exec_orders.multi_leg_group_id ...")
    if "multi_leg_group_id" in existing_cols:
        print("      OK — column already present.")
    else:
        print("      Adding column ...")
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE exec_orders ADD COLUMN multi_leg_group_id VARCHAR(64)"
            ))
        print("      OK — column added.")

    # ----- Add leg_index column -----
    print("\n[2/3] Checking exec_orders.leg_index ...")
    if "leg_index" in existing_cols:
        print("      OK — column already present.")
    else:
        print("      Adding column ...")
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE exec_orders ADD COLUMN leg_index INTEGER"
            ))
        print("      OK — column added.")

    # ----- Add index on multi_leg_group_id -----
    print("\n[3/3] Checking index ix_exec_orders_multi_leg ...")
    existing_idx = {ix["name"] for ix in insp.get_indexes("exec_orders")}
    if "ix_exec_orders_multi_leg" in existing_idx:
        print("      OK — index already present.")
    else:
        print("      Creating index ...")
        try:
            with engine.begin() as conn:
                # IF NOT EXISTS is supported on Postgres + SQLite, not MySQL.
                if dialect in ("postgresql", "sqlite"):
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_exec_orders_multi_leg "
                        "ON exec_orders (multi_leg_group_id)"
                    ))
                else:
                    conn.execute(text(
                        "CREATE INDEX ix_exec_orders_multi_leg "
                        "ON exec_orders (multi_leg_group_id)"
                    ))
            print("      OK — index created.")
        except Exception as e:
            print(f"      WARNING — could not create index: {e}")
            print("      Continuing — column-only adds are still valid.")

    print("\n" + "=" * 70)
    print("Migration #005 complete.")
    print()
    print("Next steps:")
    print("  • Restart backend so SQLAlchemy picks up the new columns.")
    print("  • POST /api/trade/place-multi-leg is now available.")
    print("  • Existing single-leg orders are unaffected (NULL group_id).")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
