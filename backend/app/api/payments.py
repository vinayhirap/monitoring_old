"""Payment processor endpoints — Razorpay webhook + diagnostic + checkout.

Endpoints:
  POST /api/payments/razorpay/webhook              — Razorpay webhook receiver
  GET  /api/payments/razorpay/diagnose             — admin self-check
  GET  /api/payments/razorpay/config               — public-ish checkout config
  POST /api/payments/razorpay/start-subscription   — authed; creates a Razorpay
                                                     subscription for the user

Why public webhook (no auth)?
  Webhooks come from Razorpay's servers, not the user. Authentication is
  via HMAC signature verification on the body — see
  `razorpay_handler.verify_signature`. A request with a valid signature
  IS Razorpay; without it, the endpoint refuses (HTTP 400).
"""
from __future__ import annotations

import base64
import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_admin, get_current_user
from app.models.subscription import SUBSCRIPTION_TIERS, TIER_PRICING_INR
from app.models.user import User
from app.services import razorpay_handler

router = APIRouter()


@router.post("/razorpay/webhook",
              summary="Receive Razorpay webhook (signature-verified, no auth)")
async def razorpay_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """Receive a Razorpay webhook event.

    Flow:
      1. Read raw body (required for signature verification — must NOT be
         parsed as JSON first; that re-serializes and changes byte content).
      2. Extract X-Razorpay-Signature header.
      3. HMAC-SHA256 verify.
      4. Parse JSON body, dispatch to handler.
      5. Return 200 with a summary so Razorpay marks the delivery as
         successful.

    Returns 503 if Razorpay isn't configured (env vars missing) so
    Razorpay's retry queue keeps trying until you flip the switch.
    """
    if not razorpay_handler.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Razorpay integration not configured on this server",
        )

    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not razorpay_handler.verify_signature(raw_body, signature):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Invalid Razorpay signature — request rejected",
        )

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed JSON body")

    result = razorpay_handler.handle_event(db, payload)
    # Always return 200 — Razorpay's retry behavior is based on response
    # status. We don't want to retry on handler errors (we've already logged
    # them); a 200 with `handled: false` lets us mark delivered and debug
    # later via the audit log.
    return result


@router.get("/razorpay/diagnose",
             summary="Razorpay integration self-check (admin)")
def razorpay_diagnose(_: Annotated[User, Depends(get_current_admin)]):
    """Reports which env vars are set and what's missing. Use to debug
    why webhook is returning 503."""
    return razorpay_handler.diagnose()


# ---------------------------------------------------------------------------
# Frontend checkout helpers
# ---------------------------------------------------------------------------

@router.get("/razorpay/config",
             summary="Public Razorpay checkout config (auth optional)")
def razorpay_config():
    """Returns the bits the frontend needs to render the tier card + open
    Razorpay Checkout. Only exposes the PUBLIC key (KEY_ID), never the secret.

    When `configured` is false, the frontend falls back to a "contact admin"
    CTA instead of trying to start a checkout.
    """
    return {
        "configured":  razorpay_handler.is_configured(),
        "key_id":      razorpay_handler.RAZORPAY_KEY_ID or None,
        "plans": {
            tier: {
                "plan_id":   plan_id,
                "price_inr": TIER_PRICING_INR.get(tier, 0),
            }
            for plan_id, tier in razorpay_handler.TIER_FOR_PLAN.items()
        },
        "currency": "INR",
    }


class StartSubscriptionRequest(BaseModel):
    tier: str = Field(..., description=f"One of {SUBSCRIPTION_TIERS[1:]} (not FREE)")
    total_count: int = Field(12, ge=1, le=120,
                              description="Number of billing cycles (months) before auto-cancel.")


@router.post("/razorpay/start-subscription",
              summary="Create a Razorpay subscription for the current user")
def start_subscription(req: StartSubscriptionRequest,
                        user: Annotated[User, Depends(get_current_user)]):
    """Server-side create a Razorpay Subscription tied to the user's email.

    Flow:
      1. Validate tier + look up plan_id from env mapping.
      2. POST to Razorpay /v1/subscriptions with HTTP Basic auth (KEY_ID:SECRET).
      3. Return `subscription_id` + `short_url` to the frontend.
      4. Frontend opens Razorpay Checkout with that subscription_id.
      5. When user pays → Razorpay fires `subscription.activated` webhook →
         `razorpay_handler._on_subscription_activated` upserts the tier.

    The `user_email` is included in `notes` so the webhook handler can
    locate the user (see `_find_user_by_email_or_notes`).
    """
    if not razorpay_handler.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Razorpay not configured. Contact admin to enable online payment.",
        )
    if req.tier == "FREE":
        raise HTTPException(400, "FREE tier requires no payment.")
    if req.tier not in SUBSCRIPTION_TIERS:
        raise HTTPException(400, f"Unknown tier {req.tier!r}.")

    # Reverse-lookup plan_id from TIER_FOR_PLAN ({plan_id: tier})
    plan_id = next(
        (pid for pid, t in razorpay_handler.TIER_FOR_PLAN.items() if t == req.tier),
        None,
    )
    if not plan_id:
        raise HTTPException(
            400,
            f"No Razorpay plan mapped for tier {req.tier!r}. "
            f"Set RAZORPAY_PLAN_{req.tier} in backend/.env and restart.",
        )

    auth_token = base64.b64encode(
        f"{razorpay_handler.RAZORPAY_KEY_ID}:{razorpay_handler.RAZORPAY_KEY_SECRET}".encode()
    ).decode()

    payload = {
        "plan_id":          plan_id,
        "total_count":      req.total_count,
        "customer_notify":  1,
        "notes": {
            "user_email": user.email,
            "user_id":    str(user.id),
            "tier":       req.tier,
        },
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                "https://api.razorpay.com/v1/subscriptions",
                headers={"Authorization": f"Basic {auth_token}",
                          "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.exception("Razorpay subscription create failed (network): {}", e)
        raise HTTPException(502, f"Razorpay API unreachable: {e}")

    if resp.status_code >= 400:
        # Razorpay returns a structured error — surface it so the user knows.
        try:
            err = resp.json().get("error", {})
            detail = err.get("description") or resp.text
        except ValueError:
            detail = resp.text
        logger.warning("Razorpay subscription create {} → {}", resp.status_code, detail)
        raise HTTPException(resp.status_code,
                             f"Razorpay rejected the request: {detail}")

    data = resp.json()
    return {
        "subscription_id": data.get("id"),
        "short_url":       data.get("short_url"),
        "status":          data.get("status"),
        "key_id":          razorpay_handler.RAZORPAY_KEY_ID,
        "tier":            req.tier,
        "amount_inr":      TIER_PRICING_INR.get(req.tier, 0),
        "user_email":      user.email,
        "user_name":       user.full_name or user.email.split("@")[0],
    }
