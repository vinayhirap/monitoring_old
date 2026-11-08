"""Broker (Angel One) endpoints.

This module covers TWO distinct concepts:

  1. The **platform-operator's** broker session (the legacy `broker_instance`).
     Used for market data, quotes, scrip-master refresh — anything that's
     a READ against Angel One that doesn't touch user funds.

  2. The **per-user** broker session, introduced in the multi-user refactor.
     Used for placing orders, fetching that user's positions/holdings, and
     anything that would charge or affect the user's money.

The legacy routes (`/status`, `/login`, `/order`, etc.) still operate on the
operator's session. The new `/me/*` routes operate on the calling user's
own session.

Trade execution code MUST use the per-user manager
(`broker_session_manager.get_for_user(db, user_id)`) — never the global
singleton.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.brokers.angelone import broker_instance
from app.brokers.base import BrokerError
from app.config import settings
from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.broker import (
    BrokerLoginRequest, BrokerLoginResponse,
    OrderRequest, OrderResponse,
)
from app.services import broker_session_manager

router = APIRouter()


@router.get("/status", summary="Broker connection status")
async def broker_status():
    is_auth = broker_instance.is_authenticated()
    return {
        "broker": broker_instance.name,
        "authenticated": is_auth,
        "paper_mode": (not is_auth),
        "live_only": settings.live_only,
        "live_blocked": settings.live_only and not is_auth,
        "last_login_error": getattr(broker_instance, "_last_error", None),
    }


@router.get("/totp-now", summary="Show the current 6-digit TOTP code generated from .env secret")
async def totp_now():
    """Confirms the secret in .env actually produces a valid 6-digit code.
    The code regenerates every 30 seconds."""
    secret = settings.angelone_totp_secret
    if not secret:
        raise HTTPException(404, "ANGELONE_TOTP_SECRET not set in .env — login can't work")
    try:
        import pyotp, time
        totp = pyotp.TOTP(secret)
        code = totp.now()
        remaining = 30 - int(time.time()) % 30
        return {
            "current_code": code,
            "valid_for_seconds": remaining,
            "secret_length": len(secret),
            "secret_preview": f"{secret[:4]}…{secret[-4:]}" if len(secret) >= 8 else "(too short)",
            "note": "If you see a 6-digit code that changes every 30s, your secret is valid.",
        }
    except Exception as e:
        raise HTTPException(500,
            f"TOTP generation failed: {e}. Your ANGELONE_TOTP_SECRET is probably not valid base32.")


@router.get("/diagnose", summary="Step-by-step Angel One login diagnostic")
async def broker_diagnose():
    """Walks every login step and reports exactly where (if anywhere) it failed.
    Use this when the badge says 'live blocked' to find the root cause.
    """
    steps: list[dict] = []

    # Step 1 — credentials present?
    creds = {
        "api_key":      bool(settings.angelone_api_key),
        "client_code":  bool(settings.angelone_client_code),
        "totp_secret":  bool(settings.angelone_totp_secret),
        "password":     bool(settings.angelone_password),
    }
    missing = [k for k in ("api_key", "client_code", "totp_secret") if not creds[k]]
    steps.append({
        "step": "1. credentials in .env",
        "ok": not missing,
        "details": creds,
        "fix": f"Add to .env: ANGELONE_{', ANGELONE_'.join(m.upper() for m in missing)}" if missing else None,
    })

    # Step 2 — TOTP secret looks valid (base32)?
    import re
    secret_ok = bool(settings.angelone_totp_secret) and \
                bool(re.fullmatch(r"[A-Z2-7]+=*", settings.angelone_totp_secret.upper()))
    steps.append({
        "step": "2. TOTP secret is base32",
        "ok": secret_ok,
        "fix": "Re-enable TOTP in Angel One mobile app and copy the EXACT base32 secret shown once." if not secret_ok else None,
    })

    # Step 3 — TOTP code generates?
    totp_code = None
    if secret_ok:
        try:
            import pyotp
            totp_code = pyotp.TOTP(settings.angelone_totp_secret).now()
            steps.append({"step": "3. TOTP code generation", "ok": True,
                           "details": f"current code (do not share): {totp_code}"})
        except Exception as e:
            steps.append({"step": "3. TOTP code generation", "ok": False,
                           "fix": f"pyotp failed: {e}"})
    else:
        steps.append({"step": "3. TOTP code generation", "ok": False,
                       "fix": "Cannot generate TOTP — fix Step 2 first."})

    # Step 4 — SmartConnect importable?
    try:
        from SmartApi import SmartConnect    # noqa: F401
        steps.append({"step": "4. smartapi-python installed", "ok": True})
    except ImportError as e:
        steps.append({"step": "4. smartapi-python installed", "ok": False,
                       "fix": f"pip install smartapi-python — {e}"})

    # Step 5 — actually try login
    if all(s["ok"] for s in steps):
        try:
            broker_instance.login()
            if broker_instance.is_authenticated():
                steps.append({"step": "5. SmartAPI login", "ok": True,
                               "details": "Authenticated — LIVE mode active"})
            else:
                steps.append({"step": "5. SmartAPI login", "ok": False,
                               "fix": f"Login fell back to paper: {getattr(broker_instance, '_last_error', 'unknown')}"})
        except BrokerError as e:
            steps.append({"step": "5. SmartAPI login", "ok": False, "fix": str(e)})
        except Exception as e:
            steps.append({"step": "5. SmartAPI login", "ok": False, "fix": f"{type(e).__name__}: {e}"})

    return {
        "live_only": settings.live_only,
        "authenticated": broker_instance.is_authenticated(),
        "steps": steps,
        "summary": "all green → LIVE mode is active" if all(s["ok"] for s in steps)
                    else f"first failure at: {next((s['step'] for s in steps if not s['ok']), '?')}",
    }


@router.post("/login", response_model=BrokerLoginResponse, summary="Angel One SmartAPI login")
async def broker_login(req: BrokerLoginRequest):
    try:
        res = broker_instance.login(
            api_key=req.api_key,
            client_code=req.client_code,
            password=req.password,
            totp=req.totp,
        )
        return BrokerLoginResponse(**res)
    except BrokerError as e:
        raise HTTPException(401, str(e))
    except Exception as e:
        raise HTTPException(500, f"login error: {e}")


@router.post("/order", response_model=OrderResponse, summary="Place an order (paper or live)")
async def place_order(req: OrderRequest):
    try:
        res = broker_instance.place_order(**req.model_dump())
        return OrderResponse(
            order_id=res.get("order_id", ""),
            status=res.get("status", "unknown"),
            paper=res.get("paper", True),
            message=res.get("message", ""),
            raw=res,
        )
    except BrokerError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"order error: {e}")


@router.delete("/order/{order_id}", summary="Cancel an order")
async def cancel_order(order_id: str):
    try:
        return broker_instance.cancel_order(order_id)
    except BrokerError as e:
        raise HTTPException(400, str(e))


@router.get("/positions", summary="Current open positions")
async def positions():
    try:
        return {"positions": broker_instance.positions()}
    except BrokerError as e:
        raise HTTPException(400, str(e))


@router.get("/holdings", summary="Long-term holdings")
async def holdings():
    try:
        return {"holdings": broker_instance.holdings()}
    except BrokerError as e:
        raise HTTPException(400, str(e))


# ============================================================================
# Per-user broker endpoints — the multi-user-trading enabler
# ============================================================================

class ConnectBrokerRequest(BaseModel):
    """The user submits their OWN Angel One credentials. Stored encrypted
    via Fernet (services/credential_crypto.py). Never returned in any
    response — confirmable only by attempting an action."""
    api_key:     str = Field(..., min_length=4, max_length=128)
    client_code: str = Field(..., min_length=4, max_length=64)
    totp_secret: str = Field(..., min_length=8, max_length=128,
                                description="Base32-encoded TOTP secret from Angel One mobile app")
    password:    str = Field("",  max_length=128,
                                description="Required by some Angel One flows; leave empty if your account only uses TOTP")


@router.get("/me/status",
             summary="My broker connection status (per-user, not platform-operator)")
def my_broker_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Returns whether THIS user has a broker connected, when the session
    expires, and the last login error if any. Never includes credentials."""
    return broker_session_manager.status(db, user.id)


@router.post("/me/connect",
              summary="Connect THIS user's Angel One account to the platform")
def my_broker_connect(
    req: ConnectBrokerRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Validates the credentials by attempting a live login, then stores
    them encrypted. Returns the session expiry on success; returns 400 with
    the broker's error message on failure.

    The platform stores enough to re-authenticate when the session token
    expires (~24h). User can revoke any time via DELETE /api/broker/me/disconnect.
    """
    try:
        result = broker_session_manager.connect(
            db, user.id,
            api_key=req.api_key,
            client_code=req.client_code,
            totp_secret=req.totp_secret,
            password=req.password or "",
        )
        return result
    except broker_session_manager.BrokerSessionError as e:
        raise HTTPException(400, str(e))


@router.delete("/me/disconnect",
                summary="Disconnect THIS user's broker — wipe stored credentials")
def my_broker_disconnect(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """Wipes the user's encrypted credentials + invalidates the cached
    session. Idempotent — calling twice is safe.

    This does NOT revoke the user's Angel One API key on the broker's side;
    if the user wants belt-and-suspenders revocation, they should also
    regenerate the API key in their Angel One dashboard."""
    return broker_session_manager.disconnect(db, user.id)
