"""CSRF protection — double-submit cookie pattern, opt-in via env.

When and why to enable:

Right now, MarketLens authenticates with `Authorization: Bearer <jwt>` tokens
stored in `localStorage`. **CSRF is not a real threat in this model** because
the token is only sent by JavaScript that explicitly attaches it to the
Authorization header — a malicious cross-origin page cannot trigger that.

CSRF becomes a real threat the moment you switch to **cookie-based** auth.
When the JWT lives in an HttpOnly cookie, the browser auto-attaches it to
every same-domain request, including those triggered by other origins.
That's the classic CSRF vector.

Two situations where you'd switch to cookie auth:
  1. iOS Safari ITP / 7-day localStorage expiry forces it
  2. You add SSE or WebSocket auth (the EventSource API can't set headers)
  3. You go full SSR with Next.js server actions

When that day comes:

  1. Set `CSRF_PROTECTION_ENABLED=true` in backend/.env
  2. Set `CSRF_SECRET=<32-char random>` for token signing
  3. Restart backend — the middleware activates
  4. Update the frontend's `lib/auth.ts`:
        - On login, read the `csrftoken` cookie set by the backend
        - On every mutating request (POST/PATCH/PUT/DELETE) send the
          token back as an `X-CSRF-Token` header
  5. Switch your auth from Bearer headers to HttpOnly cookies

How double-submit cookie works:
  • Server sets a random `csrftoken` cookie (NOT HttpOnly, so JS can read it)
  • Client reads cookie value and sends it as `X-CSRF-Token` header
  • Server compares — if they match, request is from the legitimate origin
    (a cross-origin attacker can't read the cookie value to copy into header)

This module implements the pattern but is **disabled by default**. With
`CSRF_PROTECTION_ENABLED=false` (default), the middleware is a no-op pass-through.
"""
from __future__ import annotations

import hmac
import os
import secrets
from typing import Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# Config — opt-in via env vars
CSRF_ENABLED      = os.getenv("CSRF_PROTECTION_ENABLED", "false").lower() == "true"
CSRF_SECRET       = os.getenv("CSRF_SECRET", secrets.token_hex(32)).strip()
CSRF_COOKIE_NAME  = "csrftoken"
CSRF_HEADER_NAME  = "X-CSRF-Token"
CSRF_COOKIE_PATH  = "/"
CSRF_COOKIE_SAMESITE = "Lax"

# Methods that are SAFE per RFC 7231 — they don't change state, no CSRF risk
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths that bypass CSRF checks entirely — primarily the auth endpoints
# (login itself can't have a token; that's where we mint it) and webhook
# receivers (third parties don't know our CSRF token; they use HMAC instead).
CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/signup",
    "/api/payments/razorpay/webhook",
}


def _generate_token() -> str:
    """Generate a fresh CSRF token. Random 32 bytes, hex-encoded."""
    return secrets.token_hex(32)


def _tokens_equal(cookie_token: str, header_token: str) -> bool:
    """Constant-time comparison so failed attempts don't leak timing info."""
    if not cookie_token or not header_token:
        return False
    return hmac.compare_digest(cookie_token, header_token)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    When disabled (CSRF_PROTECTION_ENABLED=false): pass through. The
    middleware does nothing, adding only a single env-var check to the
    request path.

    When enabled:
      • SAFE methods (GET/HEAD/OPTIONS): pass through. Set the cookie if
        missing so the next mutating request will have a token to send.
      • UNSAFE methods (POST/PUT/PATCH/DELETE): require cookie + header
        match. Reject with 403 if missing or mismatched.
      • Exempt paths (login, signup, webhooks): pass through unconditionally.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        # Fast path — middleware is opt-in
        if not CSRF_ENABLED:
            return await call_next(request)

        # Read existing cookie (if any) before processing
        existing_cookie = request.cookies.get(CSRF_COOKIE_NAME, "")

        # Safe methods → no check, but mint a token if missing
        if request.method in SAFE_METHODS:
            response = await call_next(request)
            if not existing_cookie:
                # First visit — set the cookie so future mutations have a token
                response.set_cookie(
                    key=CSRF_COOKIE_NAME,
                    value=_generate_token(),
                    httponly=False,      # JS MUST read this; double-submit pattern
                    samesite=CSRF_COOKIE_SAMESITE,
                    path=CSRF_COOKIE_PATH,
                    secure=request.url.scheme == "https",
                )
            return response

        # Exempt paths
        if request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Unsafe method on a protected path — enforce double-submit match
        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        if not _tokens_equal(existing_cookie, header_token):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": "CSRF check failed",
                    "hint": (
                        "Read the csrftoken cookie and resubmit with the "
                        "X-CSRF-Token header set to the same value."
                    ),
                },
            )
        return await call_next(request)


def install(app) -> None:
    """Install the middleware on a FastAPI app. Called from app.main."""
    app.add_middleware(CSRFMiddleware)
