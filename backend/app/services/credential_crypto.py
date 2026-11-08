"""Symmetric encryption for stored broker credentials.

Why Fernet:
  • Authenticated encryption (HMAC + AES-CBC) — tamper-evident
  • Standard library on top of `cryptography` package (already a transitive
    dep via passlib/bcrypt)
  • One key for the whole platform — simple key management

Threat model:
  • DB read attacker (e.g. SQL injection, backup leak) — must not be able to
    recover plaintext credentials WITHOUT also having `BROKER_CRED_KEY`.
  • RAM-dump attacker — game over (decrypted credentials live in memory briefly
    during a login attempt). We do not defend against this; for that you'd
    need a hardware-backed secret store (AWS KMS, HSM, etc.).

Key management:
  • The Fernet key is read from the `BROKER_CRED_KEY` env var (44-char base64).
  • Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  • Rotate by setting `BROKER_CRED_KEY` to the new key + `BROKER_CRED_KEY_OLD`
    to the previous one for graceful decryption fallback (see `decrypt()`).

What gets encrypted:
  • api_key, client_code, totp_secret, password
  • session_token, refresh_token, feed_token
  • Each as a separate ciphertext blob — no JSON serialisation that could
    leak structural metadata.

What does NOT get encrypted:
  • user_id (FK), broker name (string), timestamps, connection status flags.
  These are non-sensitive operational metadata.
"""
from __future__ import annotations

import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


_fernet: Optional[MultiFernet] = None


def _build_fernet() -> Optional[MultiFernet]:
    """Build a MultiFernet using primary + optional old key.

    Returns None when no key is configured — `encrypt`/`decrypt` then raise
    a clear error. We DO NOT silently fall back to plaintext.
    """
    primary = os.getenv("BROKER_CRED_KEY", "").strip()
    if not primary:
        return None
    keys = [Fernet(primary.encode())]
    old = os.getenv("BROKER_CRED_KEY_OLD", "").strip()
    if old:
        # Old key is consulted for decryption only — useful during rotation.
        # MultiFernet uses the first key for encryption, all keys for decryption.
        keys.append(Fernet(old.encode()))
    return MultiFernet(keys)


def _get() -> MultiFernet:
    """Lazy-build the Fernet on first access."""
    global _fernet
    if _fernet is None:
        _fernet = _build_fernet()
    if _fernet is None:
        raise RuntimeError(
            "BROKER_CRED_KEY env var not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return _fernet


def is_configured() -> bool:
    """True iff the encryption key is available. Used by the /broker/connect
    endpoint to refuse cleanly when ops haven't set the env var yet."""
    try:
        _get()
        return True
    except RuntimeError:
        return False


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string. None in → None out (used for optional fields)."""
    if plaintext is None or plaintext == "":
        return None
    return _get().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a string. None in → None out.
    Raises `InvalidToken` if the ciphertext was tampered with or the key
    is wrong — caller should treat that as an auth failure."""
    if ciphertext is None or ciphertext == "":
        return None
    return _get().decrypt(ciphertext.encode("ascii")).decode("utf-8")


def safe_decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Like `decrypt` but returns None on any failure. Use when you'd rather
    treat a corrupted ciphertext as "no value" than crash."""
    if ciphertext is None or ciphertext == "":
        return None
    try:
        return decrypt(ciphertext)
    except (InvalidToken, RuntimeError, Exception):
        return None
