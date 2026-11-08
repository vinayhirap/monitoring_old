#!/usr/bin/env python3
"""Apply schema for per-user broker sessions.

Creates the `user_broker_sessions` table. Idempotent — running twice is safe.

Run after deploying the multi-user broker refactor:
    cd backend
    source venv/bin/activate
    python migrations/004_per_user_broker_sessions.py

Pre-requisites:
  • `cryptography` package installed (already a transitive dep via bcrypt)
  • `BROKER_CRED_KEY` env var set — required for users to actually connect.
    Generate one with:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    Set it in backend/.env before running the backend.
"""
from __future__ import annotations

import sys

from sqlalchemy import inspect


def main() -> int:
    from app.database import Base, engine
    # Importing the model registers it with Base.metadata
    from app.models import user_broker_session    # noqa: F401

    print("=" * 70)
    print("Applying schema migration #004 — per-user broker sessions")
    print(f"Database: {engine.url}")
    print("=" * 70)

    print("\n[1/2] Running Base.metadata.create_all() …")
    try:
        Base.metadata.create_all(engine)
        print("      OK — user_broker_sessions created (or already existed).")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    print("\n[2/2] Verifying schema …")
    try:
        insp = inspect(engine)
        if "user_broker_sessions" not in insp.get_table_names():
            print("      WARNING — table missing after create_all. Check model import.")
            return 1
        cols = {c["name"] for c in insp.get_columns("user_broker_sessions")}
        expected_cols = {
            "id", "user_id", "broker",
            "api_key_ct", "client_code_ct", "totp_secret_ct", "password_ct",
            "session_token_ct", "refresh_token_ct", "feed_token_ct",
            "session_issued_at", "session_expires_at", "last_used_at",
            "connected", "last_login_error", "created_at", "updated_at",
        }
        missing = expected_cols - cols
        if missing:
            print(f"      WARNING — expected columns missing: {missing}")
            return 1
        print(f"      OK — {len(cols)} columns present.")
    except Exception as e:
        print(f"      FAILED: {e}")
        return 1

    print("\n" + "=" * 70)
    print("Migration #004 complete.")
    print()
    print("Next steps:")
    print("  1. Generate a Fernet key:")
    print('       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
    print("  2. Set it in backend/.env as BROKER_CRED_KEY=<the key>")
    print("  3. Restart the backend.")
    print("  4. Users visit /portal/broker to connect their own Angel One accounts.")
    print()
    print("WARNING: changing BROKER_CRED_KEY later will invalidate all stored")
    print("credentials. Either set BROKER_CRED_KEY_OLD to the previous key for")
    print("graceful decryption, or have users reconnect after rotation.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
