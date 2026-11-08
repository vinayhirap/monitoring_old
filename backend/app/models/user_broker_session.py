"""Per-user broker credentials + active session.

Why this exists:

Pre-refactor, the platform used a SINGLE `broker_instance` (Angel One client)
authenticated with the operator's own credentials. Every user's trade routed
through that one account. That's:
  • Regulatory disaster (orders placed in operator's name)
  • Operational disaster (one user's bad day blows up everyone's margin)
  • Scaling disaster (Angel One rate-limits one account)

Post-refactor, each user logs into THEIR OWN Angel One account from the app.
We store an encrypted copy of their credentials so we can re-authenticate
when their session token expires. The platform never holds the user's funds —
orders are placed by the user's broker against the user's broker account.

What this table stores per user:

  • Encrypted API key + client code + TOTP secret + password
    (encrypted with Fernet from `services/credential_crypto.py`)
  • Last-known session token (also encrypted — broker tokens are short-lived
    but valuable to attackers while they're alive)
  • Session metadata: when issued, when last refreshed, when last used
  • A "connected" flag — false means the user has revoked OR never connected

Security stance:
  • Credentials are NEVER returned in any API response. They're write-only.
  • Decrypted credentials live in memory only during a single login attempt.
  • The Fernet key lives in env (`BROKER_CRED_KEY`); leaking the DB without
    the env key leaks no usable credentials.
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.sql import func

from app.database import Base


class UserBrokerSession(Base):
    """One row per (user, broker) — currently always Angel One."""
    __tablename__ = "user_broker_sessions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    user_id         = Column(Integer, ForeignKey("users.id"), unique=True,
                                index=True, nullable=False)

    broker          = Column(String(16), default="angelone", nullable=False)

    # Encrypted credentials — ciphertext via Fernet (services/credential_crypto.py)
    api_key_ct          = Column(String(512), nullable=True)
    client_code_ct      = Column(String(512), nullable=True)
    totp_secret_ct      = Column(String(512), nullable=True)
    password_ct         = Column(String(512), nullable=True)

    # Current session — refreshed when expired
    session_token_ct    = Column(String(2048), nullable=True)
    refresh_token_ct    = Column(String(2048), nullable=True)
    feed_token_ct       = Column(String(2048), nullable=True)
    session_issued_at   = Column(DateTime, nullable=True)
    session_expires_at  = Column(DateTime, nullable=True)
    last_used_at        = Column(DateTime, nullable=True)

    # Status
    connected           = Column(Boolean, default=False, index=True)
    last_login_error    = Column(String(512), nullable=True)

    # Audit timestamps
    created_at      = Column(DateTime, server_default=func.now())
    updated_at      = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_broker_sess_user_broker", "user_id", "broker", unique=True),
    )
