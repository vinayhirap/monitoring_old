"""Razorpay payment processor integration.

Razorpay is the dominant payment processor for Indian SaaS (and was the
right call given MarketLens's Indian retail market). This module:

  1. Verifies webhook signatures (HMAC-SHA256 of body keyed on webhook secret)
  2. Routes events to handlers (subscription created, charged, cancelled, etc.)
  3. Auto-promotes/demotes the corresponding user's subscription tier
  4. Records every payment event in the audit log

How to enable:

  1. Create a Razorpay account: https://razorpay.com/
  2. In dashboard → Settings → API Keys, generate key + secret
  3. In dashboard → Settings → Webhooks, create a webhook pointing at
        https://your-domain.com/api/payments/razorpay/webhook
     Select events:
        subscription.activated
        subscription.charged
        subscription.cancelled
        subscription.completed
        payment.failed
     Set a webhook secret (any random 32+ char string).
  4. In Razorpay → Subscriptions → Plans, create a plan for each tier:
        BASIC        → ₹499/mo  → plan_id e.g. plan_BASIC_123
        INTERMEDIATE → ₹1499/mo → plan_id e.g. plan_INTER_456
        ADVANCED     → ₹2999/mo → plan_id e.g. plan_ADV_789
  5. Set in backend/.env:
        RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxxxx
        RAZORPAY_KEY_SECRET=<api secret>
        RAZORPAY_WEBHOOK_SECRET=<webhook secret>
        RAZORPAY_PLAN_BASIC=plan_BASIC_123
        RAZORPAY_PLAN_INTERMEDIATE=plan_INTER_456
        RAZORPAY_PLAN_ADVANCED=plan_ADV_789
  6. Restart backend. Hit /api/payments/razorpay/diagnose to verify.

When NOT configured:
  • This entire module is a no-op
  • The webhook endpoint returns 503 with a clear "not configured" message
  • The /diagnose endpoint reports which env vars are missing
"""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from app.models.subscription import Subscription, SUBSCRIPTION_TIERS
from app.models.user import User
from app.services import audit


# ----- Config -----
RAZORPAY_KEY_ID         = os.getenv("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET     = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()

# Plan-ID → tier mapping. Tier-to-plan-ID lookup is built from these.
TIER_FOR_PLAN: dict[str, str] = {
    pid: tier
    for tier, pid in [
        ("BASIC",        os.getenv("RAZORPAY_PLAN_BASIC", "").strip()),
        ("INTERMEDIATE", os.getenv("RAZORPAY_PLAN_INTERMEDIATE", "").strip()),
        ("ADVANCED",     os.getenv("RAZORPAY_PLAN_ADVANCED", "").strip()),
    ] if pid
}

# Subscription period mapped from plan name suffixes — Razorpay sends the
# plan_id but not always the period explicitly. Default to 30 days.
DEFAULT_PERIOD_DAYS = 30


def is_configured() -> bool:
    """Active only when KEY_ID + WEBHOOK_SECRET + at least one PLAN are set."""
    return bool(RAZORPAY_KEY_ID and RAZORPAY_WEBHOOK_SECRET and TIER_FOR_PLAN)


# ----------------------------------------------------------------------------
# Signature verification
# ----------------------------------------------------------------------------

def verify_signature(body: bytes, signature: str) -> bool:
    """Verify the X-Razorpay-Signature header against the body using HMAC-SHA256.

    Razorpay's webhook spec: signature = hmac_sha256(body, webhook_secret),
    hex-encoded. We compute the same and compare in constant time.
    """
    if not RAZORPAY_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ----------------------------------------------------------------------------
# Event dispatch
# ----------------------------------------------------------------------------

def handle_event(db: Session, payload: dict) -> dict:
    """Dispatch a verified webhook event to its handler.

    The webhook signature is verified by the endpoint BEFORE this is called —
    callers in app/api/payments.py must ensure that.
    """
    event = payload.get("event", "")
    entity = (payload.get("payload") or {}).get("subscription") or \
              (payload.get("payload") or {}).get("payment") or {}
    entity = entity.get("entity", {})

    handlers = {
        "subscription.activated":   _on_subscription_activated,
        "subscription.charged":     _on_subscription_charged,
        "subscription.cancelled":   _on_subscription_cancelled,
        "subscription.completed":   _on_subscription_cancelled,    # same effect
        "payment.failed":           _on_payment_failed,
    }
    handler = handlers.get(event)
    if not handler:
        logger.info("Razorpay event ignored (no handler): {}", event)
        return {"event": event, "handled": False, "reason": "no handler"}

    try:
        result = handler(db, entity)
        logger.info("Razorpay event handled: {} → {}", event, result)
        return {"event": event, "handled": True, **result}
    except Exception as e:
        logger.exception("Razorpay event handler failed: {}", e)
        return {"event": event, "handled": False, "error": str(e)}


# ----------------------------------------------------------------------------
# Per-event handlers
# ----------------------------------------------------------------------------

def _find_user_by_email_or_notes(db: Session, entity: dict) -> Optional[User]:
    """Locate the user this Razorpay entity belongs to.

    Razorpay subscription objects carry `notes` (key-value pairs set when
    you create the subscription). We require `user_email` in notes so
    every subscription is traceable. Fall back to `customer_email` if
    Razorpay provided it.
    """
    notes = entity.get("notes") or {}
    email = (notes.get("user_email") or
              entity.get("customer_email") or "").strip().lower()
    if not email:
        return None
    return db.query(User).filter(User.email == email).one_or_none()


def _set_tier(db: Session, user: User, tier: str, period_days: int,
                event_label: str, entity: dict) -> dict:
    """Upsert the user's subscription row to the new tier + extend valid_until."""
    if tier not in SUBSCRIPTION_TIERS:
        return {"ok": False, "reason": f"unknown tier {tier!r}"}

    sub = db.query(Subscription).filter_by(user_id=user.id).one_or_none()
    if sub is None:
        sub = Subscription(user_id=user.id, tier=tier, is_active=True,
                            started_at=datetime.utcnow())
        db.add(sub)
    sub.tier = tier
    sub.is_active = True
    # Extend valid_until from now (or from the existing valid_until if
    # it's still in the future — this handles mid-cycle renewals cleanly)
    base = max(sub.valid_until or datetime.utcnow(), datetime.utcnow())
    sub.valid_until = base + timedelta(days=period_days)
    db.commit()
    db.refresh(sub)

    audit.record(
        actor=user, action=f"payment.{event_label}",
        summary=f"Razorpay {event_label}: {user.email} → {tier} for {period_days}d",
        target=user,
        details_after={"tier": tier, "valid_until": sub.valid_until.isoformat(),
                         "razorpay_subscription_id": entity.get("id")},
    )
    return {"ok": True, "user_email": user.email, "tier": tier,
             "valid_until": sub.valid_until.isoformat()}


def _on_subscription_activated(db: Session, entity: dict) -> dict:
    """Called when a user signs up + first payment succeeds."""
    user = _find_user_by_email_or_notes(db, entity)
    if not user:
        return {"ok": False, "reason": "user not found"}
    plan_id = entity.get("plan_id", "")
    tier = TIER_FOR_PLAN.get(plan_id)
    if not tier:
        return {"ok": False, "reason": f"plan_id {plan_id!r} not mapped"}
    return _set_tier(db, user, tier, DEFAULT_PERIOD_DAYS, "activated", entity)


def _on_subscription_charged(db: Session, entity: dict) -> dict:
    """Called on every recurring charge — extend the subscription validity."""
    user = _find_user_by_email_or_notes(db, entity)
    if not user:
        return {"ok": False, "reason": "user not found"}
    plan_id = entity.get("plan_id", "")
    tier = TIER_FOR_PLAN.get(plan_id)
    if not tier:
        return {"ok": False, "reason": f"plan_id {plan_id!r} not mapped"}
    return _set_tier(db, user, tier, DEFAULT_PERIOD_DAYS, "charged", entity)


def _on_subscription_cancelled(db: Session, entity: dict) -> dict:
    """User cancelled — keep them at current tier until valid_until, then
    they auto-fall back to FREE (handled by `get_active_tier` which checks
    valid_until on read)."""
    user = _find_user_by_email_or_notes(db, entity)
    if not user:
        return {"ok": False, "reason": "user not found"}
    sub = db.query(Subscription).filter_by(user_id=user.id).one_or_none()
    if sub:
        # Don't immediately demote — they paid for this cycle. Mark inactive
        # so renewal stops, but valid_until still gates the live tier.
        sub.is_active = False
        db.commit()
    audit.record(
        actor=user, action="payment.cancelled",
        summary=f"Razorpay subscription cancelled: {user.email}",
        target=user,
    )
    return {"ok": True, "user_email": user.email,
             "note": "Tier remains active until valid_until then drops to FREE"}


def _on_payment_failed(db: Session, entity: dict) -> dict:
    """A scheduled charge failed. Log it — but don't auto-demote; Razorpay
    will retry per its own policy."""
    user = _find_user_by_email_or_notes(db, entity)
    if user:
        audit.record(
            actor=user, action="payment.failed",
            summary=f"Razorpay payment failed for {user.email}",
            target=user, details_after={"error_description": entity.get("error_description")},
        )
        return {"ok": True, "user_email": user.email,
                 "note": "Logged. Razorpay will retry."}
    return {"ok": False, "reason": "user not found"}


# ----------------------------------------------------------------------------
# Diagnostic
# ----------------------------------------------------------------------------

def diagnose() -> dict:
    """Self-check for /api/payments/razorpay/diagnose and the detailed
    health endpoint.

    Reports:
      • Which env vars are set vs missing
      • The configured plan-IDs (so admin can cross-check Razorpay dashboard)
      • Whether the Razorpay REST API responds to our key (live auth check)
      • A list of NEXT STEPS so the admin can fix problems without grepping docs
    """
    missing = []
    if not RAZORPAY_KEY_ID:
        missing.append("RAZORPAY_KEY_ID")
    if not RAZORPAY_KEY_SECRET:
        missing.append("RAZORPAY_KEY_SECRET")
    if not RAZORPAY_WEBHOOK_SECRET:
        missing.append("RAZORPAY_WEBHOOK_SECRET")
    if not TIER_FOR_PLAN:
        missing.append("RAZORPAY_PLAN_* (at least one of BASIC/INTERMEDIATE/ADVANCED)")

    # ---- Live API auth check ----
    # Hit GET /v1/plans?count=1 with our basic-auth header — confirms the
    # key+secret combination is valid and Razorpay accepts our requests.
    # Network errors and 401s come back as `api_reachable=false` with the
    # reason — much more actionable than just "configured=false".
    api_status: dict = {"reachable": False, "reason": "not attempted"}
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        try:
            import base64
            import httpx
            token = base64.b64encode(
                f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()
            ).decode()
            with httpx.Client(timeout=5.0) as client:
                r = client.get("https://api.razorpay.com/v1/plans?count=1",
                                headers={"Authorization": f"Basic {token}"})
            if r.status_code == 200:
                payload = r.json()
                api_status = {
                    "reachable": True,
                    "auth_ok":   True,
                    "plan_count_visible": len(payload.get("items", [])),
                    "mode": ("live" if RAZORPAY_KEY_ID.startswith("rzp_live_")
                              else "test" if RAZORPAY_KEY_ID.startswith("rzp_test_")
                              else "unknown"),
                }
            elif r.status_code in (401, 403):
                api_status = {"reachable": True, "auth_ok": False,
                               "reason": f"Auth rejected by Razorpay ({r.status_code}). "
                                          "Check RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET."}
            else:
                api_status = {"reachable": True, "auth_ok": False,
                               "reason": f"Unexpected {r.status_code} from Razorpay: "
                                          f"{r.text[:200]}"}
        except Exception as e:
            api_status = {"reachable": False, "reason": str(e)}

    next_steps: list[str] = []
    if missing:
        next_steps.append(f"Set missing env vars: {', '.join(missing)}")
        next_steps.append("Restart the backend so razorpay_handler re-reads the env")
    if api_status.get("reachable") is False and not missing:
        next_steps.append(f"Razorpay API unreachable: {api_status.get('reason', '?')}")
    if api_status.get("auth_ok") is False:
        next_steps.append("Verify the key_id/secret pair in Razorpay → Settings → API Keys")
    if not next_steps:
        next_steps.append("✓ Configured. Verify Razorpay → Settings → Webhooks points at "
                           "https://<your-domain>/api/payments/razorpay/webhook")
        next_steps.append("✓ Subscribe to events: subscription.activated, subscription.charged, "
                           "subscription.cancelled, subscription.completed, payment.failed")
        next_steps.append("✓ Run a sandbox payment with a test subscription to verify the "
                           "webhook → tier-upgrade flow end-to-end")

    return {
        "configured":      is_configured(),
        "missing_env":     missing,
        "key_mode":        api_status.get("mode", "?"),
        "plans_mapped":    {tier: pid for pid, tier in TIER_FOR_PLAN.items()},
        "api_check":       api_status,
        "webhook_endpoint": "/api/payments/razorpay/webhook",
        "next_steps":      next_steps,
    }
