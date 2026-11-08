"""Per-user broker session manager — the heart of the multi-user refactor.

Pre-refactor flow:
    [user request] → trade_executor → broker_instance (singleton) → Angel One
                                              ^
                                  one global session, operator's account

Post-refactor flow:
    [user request] → trade_executor → broker_session_manager.get_for_user(uid)
                                              ↓
                                       per-user broker client
                                              ↓
                                  Angel One (user's own account)

Caching strategy:
  • Per-process in-memory `dict[user_id → AngelOneBroker]` of authenticated clients
  • Each entry has a `session_expires_at` timestamp
  • On hit: return cached client if expires_at > now
  • On miss / expired: rebuild from stored encrypted credentials, persist new
    session token to DB, return new client
  • The cache is process-local; under multiple uvicorn workers each worker
    has its own cache (re-auth costs a few hundred ms once per worker).
    When you scale to multiple HOSTS, swap the cache to Redis.

Failure modes:
  • Encrypted creds missing → `BrokerSessionError("not connected")`
  • Decryption fails (key rotation gone wrong) → `BrokerSessionError("invalid creds")`
  • Broker login API rejects → store last_login_error, set connected=False,
    raise `BrokerSessionError(...)` with the underlying broker message
  • Network failure → raise `BrokerSessionError("network failure")`
    (callers should NOT auto-retry; the user retries the action)

All errors propagate up — `trade_executor` catches them, writes a FAILED
order row, and returns the structured failure to the API.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.brokers.base import BrokerError
from app.models.user_broker_session import UserBrokerSession
from app.services import credential_crypto


# Session lifetime — Angel One tokens live ~24h. We refresh proactively at 23h
# to avoid a race where a request is in-flight when the token expires.
SESSION_REFRESH_BEFORE_EXPIRY_SEC = 60 * 60      # refresh if <1h left
DEFAULT_SESSION_DURATION_HOURS    = 24


class BrokerSessionError(Exception):
    """Raised when a per-user broker session can't be obtained.

    Callers translate this to a structured ExecutionResult failure rather
    than letting it crash the request."""


# ----------------------------------------------------------------------------
# In-memory cache — single process; replace with Redis at scale
# ----------------------------------------------------------------------------

_cache: dict[int, "_CachedSession"] = {}
_cache_lock = threading.Lock()


class _CachedSession:
    """Wraps an authenticated broker client + its expiry. Not exposed —
    callers only see the broker client via get_for_user()."""
    def __init__(self, broker_client, expires_at: datetime):
        self.broker_client = broker_client
        self.expires_at = expires_at


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def connect(db: Session, user_id: int, *, api_key: str, client_code: str,
            totp_secret: str, password: str = "") -> dict:
    """Establish a broker connection for a user.

    1. Encrypt the credentials with Fernet
    2. Attempt a login with those creds — proves they actually work
    3. On success: persist encrypted creds + initial session token to DB,
       cache the authenticated client in memory
    4. On failure: persist last_login_error, return structured failure

    The user only does this ONCE per Angel One credential change. After
    that the manager re-authenticates from stored creds when needed.
    """
    if not credential_crypto.is_configured():
        raise BrokerSessionError(
            "BROKER_CRED_KEY not set in environment — ops must configure "
            "Fernet key before users can connect a broker."
        )

    # Build a fresh broker client and try logging in BEFORE we persist
    try:
        client = _new_broker_client(api_key=api_key, client_code=client_code,
                                      totp_secret=totp_secret, password=password)
        client.login(api_key=api_key, client_code=client_code,
                      totp=None,    # client will generate from totp_secret
                      password=password)
        if not client.is_authenticated():
            raise BrokerError("Login completed but client.is_authenticated() returned False")
    except BrokerError as e:
        # Record the failure in DB so user can see it on the connect page
        _store_failure(db, user_id, str(e))
        raise BrokerSessionError(f"Broker login failed: {e}")
    except Exception as e:
        _store_failure(db, user_id, f"{type(e).__name__}: {e}")
        raise BrokerSessionError(f"Broker login crashed: {e}")

    # Persist encrypted credentials + session
    row = (db.query(UserBrokerSession)
             .filter_by(user_id=user_id).one_or_none())
    if row is None:
        row = UserBrokerSession(user_id=user_id, broker="angelone")
        db.add(row)

    row.api_key_ct       = credential_crypto.encrypt(api_key)
    row.client_code_ct   = credential_crypto.encrypt(client_code)
    row.totp_secret_ct   = credential_crypto.encrypt(totp_secret)
    row.password_ct      = credential_crypto.encrypt(password)
    # Pull session tokens out of the client (broker-specific; angelone wraps them)
    session_token = _extract_token(client, "session_token")
    refresh_token = _extract_token(client, "refresh_token")
    feed_token    = _extract_token(client, "feed_token")
    row.session_token_ct  = credential_crypto.encrypt(session_token) if session_token else None
    row.refresh_token_ct  = credential_crypto.encrypt(refresh_token) if refresh_token else None
    row.feed_token_ct     = credential_crypto.encrypt(feed_token)    if feed_token else None
    row.session_issued_at  = datetime.utcnow()
    row.session_expires_at = datetime.utcnow() + timedelta(hours=DEFAULT_SESSION_DURATION_HOURS)
    row.connected = True
    row.last_login_error = None
    row.last_used_at = datetime.utcnow()
    db.commit()

    # Cache the authenticated client
    with _cache_lock:
        _cache[user_id] = _CachedSession(client, row.session_expires_at)

    logger.info("Broker session connected for user {}", user_id)
    return {
        "connected":          True,
        "session_expires_at": row.session_expires_at.isoformat() if row.session_expires_at else None,
        "message":            "Broker connected. You can now place live trades.",
    }


def disconnect(db: Session, user_id: int) -> dict:
    """Revoke the user's stored credentials + invalidate the cache.

    Does NOT call Angel One's logout — we just stop using the credentials.
    The user can also revoke at the broker's end if they want belt-and-suspenders.
    """
    row = db.query(UserBrokerSession).filter_by(user_id=user_id).one_or_none()
    if row:
        row.api_key_ct = None
        row.client_code_ct = None
        row.totp_secret_ct = None
        row.password_ct = None
        row.session_token_ct = None
        row.refresh_token_ct = None
        row.feed_token_ct = None
        row.connected = False
        row.session_expires_at = None
        db.commit()
    with _cache_lock:
        _cache.pop(user_id, None)
    logger.info("Broker session disconnected for user {}", user_id)
    return {"disconnected": True}


def status(db: Session, user_id: int) -> dict:
    """Status read for the /me/broker/status endpoint. Never returns
    credentials — only flags + timestamps."""
    row = db.query(UserBrokerSession).filter_by(user_id=user_id).one_or_none()
    if row is None:
        return {"connected": False, "ever_connected": False}
    return {
        "connected":          bool(row.connected),
        "ever_connected":     row.api_key_ct is not None,
        "session_issued_at":  row.session_issued_at.isoformat() if row.session_issued_at else None,
        "session_expires_at": row.session_expires_at.isoformat() if row.session_expires_at else None,
        "last_used_at":       row.last_used_at.isoformat() if row.last_used_at else None,
        "last_login_error":   row.last_login_error,
    }


def get_for_user(db: Session, user_id: int):
    """Return an authenticated broker client for this user. Raises
    `BrokerSessionError` if no creds stored, or if re-auth fails.

    This is THE function `trade_executor` and `order_status_poller` should
    call. Never use the global `broker_instance` from those code paths."""
    # Cache hit + fresh?
    with _cache_lock:
        cached = _cache.get(user_id)
        if cached and cached.expires_at > datetime.utcnow() + timedelta(seconds=SESSION_REFRESH_BEFORE_EXPIRY_SEC):
            return cached.broker_client

    # Cache miss or expired — rebuild from DB
    row = db.query(UserBrokerSession).filter_by(user_id=user_id).one_or_none()
    if row is None or not row.connected or not row.api_key_ct:
        raise BrokerSessionError(
            "Broker not connected for this user. Go to Profile → Connect Broker."
        )

    try:
        api_key     = credential_crypto.decrypt(row.api_key_ct)
        client_code = credential_crypto.decrypt(row.client_code_ct)
        totp_secret = credential_crypto.decrypt(row.totp_secret_ct)
        password    = credential_crypto.safe_decrypt(row.password_ct) or ""
    except Exception as e:
        _store_failure(db, user_id, f"credential decrypt failed: {e}")
        raise BrokerSessionError(
            "Stored credentials could not be decrypted (key rotation likely). "
            "Disconnect and reconnect the broker."
        )

    client = _new_broker_client(api_key=api_key, client_code=client_code,
                                  totp_secret=totp_secret, password=password)
    try:
        client.login(api_key=api_key, client_code=client_code,
                      totp=None, password=password)
        if not client.is_authenticated():
            raise BrokerError("Re-login completed but not authenticated")
    except BrokerError as e:
        _store_failure(db, user_id, str(e))
        raise BrokerSessionError(f"Broker re-login failed: {e}")

    # Persist refreshed session
    session_token = _extract_token(client, "session_token")
    refresh_token = _extract_token(client, "refresh_token")
    feed_token    = _extract_token(client, "feed_token")
    if session_token:
        row.session_token_ct = credential_crypto.encrypt(session_token)
    if refresh_token:
        row.refresh_token_ct = credential_crypto.encrypt(refresh_token)
    if feed_token:
        row.feed_token_ct = credential_crypto.encrypt(feed_token)
    row.session_issued_at  = datetime.utcnow()
    row.session_expires_at = datetime.utcnow() + timedelta(hours=DEFAULT_SESSION_DURATION_HOURS)
    row.last_used_at = datetime.utcnow()
    row.last_login_error = None
    db.commit()

    with _cache_lock:
        _cache[user_id] = _CachedSession(client, row.session_expires_at)
    return client


def connected_user_ids(db: Session) -> list[int]:
    """Used by the order-status poller to know whose orders to poll."""
    rows = (db.query(UserBrokerSession.user_id)
              .filter(UserBrokerSession.connected == True).all())   # noqa: E712
    return [r[0] for r in rows]


# ----------------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------------

def _new_broker_client(*, api_key: str, client_code: str,
                         totp_secret: str, password: str = ""):
    """Construct a fresh AngelOne broker client. We deliberately do NOT
    reuse the global singleton — each user gets their own object so a
    session-token mutation by user A doesn't poison user B's view.

    The constructor signature matches whatever the AngelOneBroker class
    exposes. If it requires kwargs you don't have, this raises ValueError —
    the connect endpoint surfaces that to the user clearly."""
    from app.brokers.angelone import AngelOneBroker
    return AngelOneBroker(
        api_key=api_key,
        client_code=client_code,
        totp_secret=totp_secret,
        password=password,
    )


def _extract_token(client, name: str) -> Optional[str]:
    """Pull a named token out of the broker client. AngelOneBroker stores
    these on attributes after login; if your wrapper uses different names,
    extend the candidates list."""
    candidates = [name, f"_{name}", f"{name}_str", f"_{name}_str"]
    for c in candidates:
        v = getattr(client, c, None)
        if isinstance(v, str) and v:
            return v
    return None


def _store_failure(db: Session, user_id: int, error: str) -> None:
    """Record a login failure for diagnostics. Never raises."""
    try:
        row = db.query(UserBrokerSession).filter_by(user_id=user_id).one_or_none()
        if row is None:
            row = UserBrokerSession(user_id=user_id, broker="angelone")
            db.add(row)
        row.last_login_error = (error or "")[:500]
        row.connected = False
        db.commit()
    except Exception as e:
        logger.debug("Could not record broker failure for user {}: {}", user_id, e)


def invalidate_cache(user_id: int) -> None:
    """Drop the cached session for a user — used after a disconnect or
    when the broker explicitly returns 'session expired' to our code."""
    with _cache_lock:
        _cache.pop(user_id, None)
