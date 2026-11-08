"""Auth helpers — JWT signing/verification + bcrypt password hashing.

Uses python-jose for JWT and passlib[bcrypt] for hashing — both already
in requirements.txt.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings


# bcrypt context — passlib auto-picks the right backend
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALG = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24             # 24 hours
REFRESH_TOKEN_EXPIRE_DAYS = 14


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789",
    "qwerty", "qwerty123", "letmein", "admin", "admin123", "iloveyou",
    "welcome", "welcome1", "monkey", "abc12345", "111111", "1234567890",
}


def validate_password_strength(password: str) -> None:
    """Raise ValueError if `password` doesn't meet policy.

    Policy (intentionally simple — no exotic special-char requirement that
    pushes users to weaker reused passwords):
      • length ≥ 8
      • contains at least one letter AND at least one digit
      • not in the common-password blacklist

    Callers should catch ValueError and surface as HTTP 400.
    """
    if password is None or len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if len(password) > 128:
        raise ValueError("Password cannot exceed 128 characters.")
    if not any(c.isalpha() for c in password):
        raise ValueError("Password must contain at least one letter.")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must contain at least one digit.")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError(
            "That password is on the common-password blacklist — pick something less guessable."
        )


# ---------------------------------------------------------------------------
# Login rate limiter — in-memory by default, Redis when REDIS_URL is set
# ---------------------------------------------------------------------------
#
# Architecture: an abstract _LimiterBackend interface with two implementations:
#   • InMemoryBackend — threadsafe dict, used when REDIS_URL is unset
#   • RedisBackend    — uses sorted-sets, activates when REDIS_URL is set
#
# Public API (check_login_lockout, record_login_failure, clear_login_failures)
# is identical regardless of backend. Swap happens at import time based on env.
# This means horizontal scaling beyond one process becomes a single config
# change with no code rewrite.

import os
import threading as _threading
import time as _time
from abc import ABC, abstractmethod
from typing import Optional

_LOGIN_LOCKOUT_THRESHOLD = 5            # failures before lockout
_LOGIN_LOCKOUT_WINDOW_SEC = 15 * 60     # rolling window for counting failures
_LOGIN_LOCKOUT_DURATION_SEC = 15 * 60   # how long lockout persists


def _bucket_key(email: Optional[str], ip: Optional[str]) -> str:
    """Combine email + IP into a single bucket key. Hits either dimension
    are tracked, but lockout is per-bucket to avoid one bad actor on a
    shared IP locking out an entire office."""
    return f"{(email or '?').lower().strip()}|{ip or '?'}"


class _LimiterBackend(ABC):
    @abstractmethod
    def record_failure(self, key: str) -> None: ...
    @abstractmethod
    def lockout_seconds_remaining(self, key: str) -> Optional[int]: ...
    @abstractmethod
    def clear(self, key: str) -> None: ...


class InMemoryBackend(_LimiterBackend):
    """Single-process, threadsafe. Default for dev + small deploys.

    Trade-off: state evaporates on restart. Acceptable since restart
    clears legitimate users' frustration too. Not safe for >1 uvicorn
    worker — use RedisBackend in that scenario.
    """
    def __init__(self):
        self._failures: dict[str, list[float]] = {}
        self._lock = _threading.Lock()

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures.setdefault(key, []).append(_time.time())
            if len(self._failures[key]) > 50:
                self._failures[key] = self._failures[key][-50:]

    def lockout_seconds_remaining(self, key: str) -> Optional[int]:
        now = _time.time()
        with self._lock:
            timestamps = self._failures.get(key, [])
            timestamps = [t for t in timestamps if now - t < _LOGIN_LOCKOUT_WINDOW_SEC]
            self._failures[key] = timestamps
            if len(timestamps) < _LOGIN_LOCKOUT_THRESHOLD:
                return None
            oldest_recent = timestamps[-_LOGIN_LOCKOUT_THRESHOLD]
            unlock_at = oldest_recent + _LOGIN_LOCKOUT_DURATION_SEC
            return max(0, int(unlock_at - now)) or None

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class RedisBackend(_LimiterBackend):
    """Multi-process / multi-replica safe. Activates when REDIS_URL is set.

    Storage model: one Redis sorted-set per bucket, score = timestamp,
    member = unique id (timestamp + random). ZREMRANGEBYSCORE evicts
    expired entries. ZCARD gives current count. ZRANGEBYSCORE used to
    find the Nth-most-recent failure for lockout math.

    All keys have prefix `auth:login_failures:` for namespacing.
    """
    KEY_PREFIX = "auth:login_failures:"

    def __init__(self, redis_url: str):
        import redis
        self._client = redis.from_url(redis_url, decode_responses=True)
        # Eagerly ping so misconfigured URLs error at startup, not first login
        self._client.ping()

    def _full_key(self, bucket: str) -> str:
        return f"{self.KEY_PREFIX}{bucket}"

    def record_failure(self, key: str) -> None:
        now = _time.time()
        full = self._full_key(key)
        # Add with unique member; trim old entries opportunistically
        self._client.zadd(full, {f"{now}-{os.urandom(4).hex()}": now})
        self._client.zremrangebyscore(full, 0, now - _LOGIN_LOCKOUT_WINDOW_SEC)
        self._client.expire(full, _LOGIN_LOCKOUT_WINDOW_SEC * 2)

    def lockout_seconds_remaining(self, key: str) -> Optional[int]:
        now = _time.time()
        full = self._full_key(key)
        self._client.zremrangebyscore(full, 0, now - _LOGIN_LOCKOUT_WINDOW_SEC)
        count = self._client.zcard(full)
        if count < _LOGIN_LOCKOUT_THRESHOLD:
            return None
        # Get the Nth-most-recent failure's timestamp (newest first)
        result = self._client.zrange(full, -_LOGIN_LOCKOUT_THRESHOLD,
                                       -_LOGIN_LOCKOUT_THRESHOLD, withscores=True)
        if not result:
            return None
        _, oldest_recent_ts = result[0]
        unlock_at = float(oldest_recent_ts) + _LOGIN_LOCKOUT_DURATION_SEC
        return max(0, int(unlock_at - now)) or None

    def clear(self, key: str) -> None:
        self._client.delete(self._full_key(key))


def _build_backend() -> _LimiterBackend:
    """Pick backend at import time based on REDIS_URL env var.
    Failing to instantiate Redis falls back to in-memory rather than crashing
    the process — better than blocking all logins because Redis is down."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        return InMemoryBackend()
    try:
        return RedisBackend(redis_url)
    except Exception as e:
        # Logger may not be imported here; print to stderr is acceptable for
        # startup config issues.
        import sys
        print(f"[auth_service] REDIS_URL set but Redis init failed ({e}) "
                f"— falling back to in-memory limiter", file=sys.stderr)
        return InMemoryBackend()


_backend = _build_backend()


# ----- Public API — unchanged signature; backend swap is transparent ------

def check_login_lockout(email: Optional[str], ip: Optional[str]) -> Optional[int]:
    """Returns seconds-remaining if locked out, else None."""
    return _backend.lockout_seconds_remaining(_bucket_key(email, ip))


def record_login_failure(email: Optional[str], ip: Optional[str]) -> None:
    _backend.record_failure(_bucket_key(email, ip))


def clear_login_failures(email: Optional[str], ip: Optional[str]) -> None:
    """Called on successful login to wipe the bucket so a legit user
    isn't carrying past mistakes forward."""
    _backend.clear(_bucket_key(email, ip))


def get_backend_name() -> str:
    """Diagnostic — returns 'redis' or 'in-memory'. Useful for /api/admin
    diagnostic endpoints to confirm which limiter is active."""
    return "redis" if isinstance(_backend, RedisBackend) else "in-memory"


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def _create_token(subject: str, kind: str, expires_delta: timedelta,
                   extra_claims: dict | None = None) -> str:
    now = datetime.utcnow()
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "typ": kind,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALG)


def create_access_token(user_id: int, email: str, is_superuser: bool = False) -> str:
    return _create_token(
        subject=str(user_id), kind="access",
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims={"email": email, "is_superuser": is_superuser},
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        subject=str(user_id), kind="refresh",
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str) -> dict | None:
    """Return payload dict or None on any validation failure."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALG])
    except JWTError:
        return None
