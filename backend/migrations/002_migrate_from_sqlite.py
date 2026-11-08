#!/usr/bin/env python3
"""One-shot data migration: SQLite → Postgres (+TimescaleDB).

Use this when:
  • You've outgrown SQLite (>500 users or >5GB of ohlcv_bars rows)
  • You want compressed time-series storage + continuous aggregates
  • You're scaling to multi-worker deployment where SQLite's single-writer
    lock becomes a bottleneck

How to use:

  1. Provision Postgres + TimescaleDB. Locally:
        docker run -d --name marketlens-tsdb \\
            -e POSTGRES_PASSWORD=changeme \\
            -p 5432:5432 \\
            timescale/timescaledb:latest-pg16

  2. Create the database:
        psql postgresql://postgres:changeme@localhost:5432/postgres \\
            -c "CREATE DATABASE marketlens;"

  3. Set the new DATABASE_URL in .env:
        DATABASE_URL=postgresql+psycopg2://postgres:changeme@localhost:5432/marketlens

  4. Run the SQLAlchemy migrations against the NEW Postgres DB (creates
     the base tables):
        cd backend
        python -c "from app.database import Base, engine; Base.metadata.create_all(engine)"

  5. Run this script — copies data from the OLD SQLite into the NEW Postgres:
        python migrations/002_migrate_from_sqlite.py \\
            --sqlite=marketlens.db \\
            --postgres="$DATABASE_URL"

  6. After it finishes, apply the TimescaleDB hypertable conversion:
        psql "$DATABASE_URL" -f migrations/001_timescaledb_setup.sql

  7. Restart the backend with the new DATABASE_URL.

Notes:
  • This script is idempotent — running twice is safe (rows are upserted).
  • Tables migrated: users, subscriptions, signals_journal, ohlcv_bars,
    watchlist_items, audit_log_entries, live_picks_snapshots.
  • If your tables list differs (you've added more), extend `TABLES_TO_COPY`.
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from sqlalchemy import create_engine, inspect, MetaData, Table, select


# Tables copied in order (preserves FK integrity — users before subscriptions etc.)
TABLES_TO_COPY = [
    "users",
    "subscriptions",
    "watchlist_items",
    "signals_journal",
    "ohlcv_bars",
    "audit_log_entries",
    "live_picks_snapshots",
]


def _table_exists(engine, name: str) -> bool:
    inspector = inspect(engine)
    return name in inspector.get_table_names()


def _copy_table(src_engine, dst_engine, table_name: str, batch_size: int = 5000) -> dict:
    """Copy all rows from `table_name` in src to dst. Uses INSERT ... ON
    CONFLICT DO NOTHING semantics where supported, so rerunning is safe."""
    if not _table_exists(src_engine, table_name):
        return {"table": table_name, "skipped": True, "reason": "not in source"}
    if not _table_exists(dst_engine, table_name):
        return {"table": table_name, "skipped": True, "reason": "not in destination"}

    src_meta = MetaData()
    src_table = Table(table_name, src_meta, autoload_with=src_engine)
    dst_meta = MetaData()
    dst_table = Table(table_name, dst_meta, autoload_with=dst_engine)

    copied = 0
    with src_engine.connect() as src_conn, dst_engine.begin() as dst_conn:
        rows = src_conn.execute(select(src_table))
        batch = []
        for r in rows:
            batch.append(dict(r._mapping))
            if len(batch) >= batch_size:
                _flush(dst_conn, dst_table, batch)
                copied += len(batch)
                batch = []
                print(f"  ... {table_name}: {copied} rows copied", end="\r")
        if batch:
            _flush(dst_conn, dst_table, batch)
            copied += len(batch)

    return {"table": table_name, "copied": copied}


def _flush(conn, table: Table, batch: list[dict]) -> None:
    """Insert a batch, ignoring rows that violate unique constraints
    (so the script can be re-run safely)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    if conn.dialect.name == "postgresql":
        # Postgres: ON CONFLICT DO NOTHING — proper idempotency
        stmt = pg_insert(table).values(batch).on_conflict_do_nothing()
        conn.execute(stmt)
    else:
        # Other dialects — fall back to row-by-row try/except
        for row in batch:
            try:
                conn.execute(table.insert().values(**row))
            except Exception:
                continue    # likely duplicate; skip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", default="marketlens.db",
                     help="Path to source SQLite file")
    ap.add_argument("--postgres", required=True,
                     help="Destination Postgres URL (postgresql+psycopg2://...)")
    args = ap.parse_args()

    src_url = f"sqlite:///{args.sqlite}"
    print(f"Source:      {src_url}")
    print(f"Destination: {args.postgres}")
    print()

    src_engine = create_engine(src_url, future=True)
    dst_engine = create_engine(args.postgres, future=True)

    results = []
    for table in TABLES_TO_COPY:
        print(f"==> {table}")
        result = _copy_table(src_engine, dst_engine, table)
        results.append(result)
        if result.get("skipped"):
            print(f"    SKIPPED ({result['reason']})")
        else:
            print(f"    OK ({result['copied']} rows)                    ")

    print()
    print("Migration complete. Next step: apply the TimescaleDB hypertable conversion:")
    print(f"  psql \"{args.postgres}\" -f migrations/001_timescaledb_setup.sql")
    return 0


if __name__ == "__main__":
    sys.exit(main())
