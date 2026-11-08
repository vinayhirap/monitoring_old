"""Subscription endpoints — user view + admin management.

Public:
  GET  /api/portal/me/subscription           — current user's tier + features
  POST /api/portal/me/telegram               — register Telegram username (for channel add)

Admin (superuser only):
  GET    /api/admin/subscriptions            — list all subscriptions
  PATCH  /api/admin/subscriptions/{user_id}  — change a user's tier
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user, get_current_admin
from app.models.user import User
from app.models.subscription import Subscription, SUBSCRIPTION_TIERS, TIER_FEATURES


user_router = APIRouter()
admin_router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_or_create_subscription(db: Session, user_id: int) -> Subscription:
    sub = db.query(Subscription).filter_by(user_id=user_id).one_or_none()
    if sub is None:
        sub = Subscription(user_id=user_id, tier="FREE", is_active=True)
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub


def get_active_tier(db: Session, user_id: int) -> str:
    """Returns the user's currently-active tier. Falls back to FREE if
    expired or no row."""
    sub = db.query(Subscription).filter_by(user_id=user_id).one_or_none()
    if sub is None or not sub.is_active:
        return "FREE"
    if sub.valid_until and sub.valid_until < datetime.utcnow():
        return "FREE"
    return sub.tier


def features_for_tier(tier: str) -> dict:
    return TIER_FEATURES.get(tier, TIER_FEATURES["FREE"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SubscriptionOut(BaseModel):
    tier: str
    is_active: bool
    valid_until: datetime | None
    started_at: datetime
    telegram_username: str | None
    features: dict


class TelegramRegisterRequest(BaseModel):
    telegram_username: str = Field(..., min_length=3, max_length=64,
                                     description="Your @username on Telegram, without the @")


class TierUpdateRequest(BaseModel):
    tier: str = Field(..., description=f"One of {SUBSCRIPTION_TIERS}")
    duration_days: int | None = Field(30, ge=1, le=3650,
                                       description="How many days the subscription is valid for. None = no expiry.")
    notes: str | None = None


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------

@user_router.get("/me/subscription", response_model=SubscriptionOut,
                  summary="Get my subscription tier and feature flags")
def my_subscription(user: Annotated[User, Depends(get_current_user)],
                     db: Annotated[Session, Depends(get_db)]):
    sub = get_or_create_subscription(db, user.id)
    tier = get_active_tier(db, user.id)
    return SubscriptionOut(
        tier=tier,
        is_active=sub.is_active,
        valid_until=sub.valid_until,
        started_at=sub.started_at,
        telegram_username=sub.telegram_username,
        features=features_for_tier(tier),
    )


@user_router.post("/me/telegram", summary="Register your Telegram username for channel access")
def register_telegram(req: TelegramRegisterRequest,
                       user: Annotated[User, Depends(get_current_user)],
                       db: Annotated[Session, Depends(get_db)]):
    sub = get_or_create_subscription(db, user.id)
    sub.telegram_username = req.telegram_username.lstrip("@").strip()
    db.commit()
    return {
        "telegram_username": sub.telegram_username,
        "message": (
            "Saved. An admin will add you to the corresponding Telegram channel "
            "for your tier after the next payment cycle. Open Telegram and ensure "
            "the username matches exactly."
        ),
    }


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@admin_router.get("/subscriptions",
                   summary="List all subscriptions (admin)",
                   dependencies=[Depends(get_current_admin)])
def list_subscriptions(db: Annotated[Session, Depends(get_db)]):
    rows = (db.query(Subscription, User)
              .join(User, User.id == Subscription.user_id)
              .order_by(Subscription.started_at.desc()).all())
    out = []
    for sub, u in rows:
        out.append({
            "user_id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "tier": sub.tier,
            "is_active": sub.is_active,
            "valid_until": sub.valid_until.isoformat() if sub.valid_until else None,
            "telegram_username": sub.telegram_username,
            "telegram_chat_id": sub.telegram_chat_id,
            "notes": sub.notes,
        })
    return {"count": len(out), "subscriptions": out}


@admin_router.patch("/subscriptions/{user_id}",
                     summary="Update a user's subscription tier (admin)",
                     dependencies=[Depends(get_current_admin)])
def update_subscription(user_id: int, req: TierUpdateRequest,
                         db: Annotated[Session, Depends(get_db)]):
    if req.tier not in SUBSCRIPTION_TIERS:
        raise HTTPException(400, f"tier must be one of {SUBSCRIPTION_TIERS}")
    sub = get_or_create_subscription(db, user_id)
    sub.tier = req.tier
    sub.is_active = True
    sub.started_at = datetime.utcnow()
    sub.valid_until = (datetime.utcnow() + timedelta(days=req.duration_days)
                       if req.duration_days else None)
    if req.notes is not None:
        sub.notes = req.notes
    db.commit()
    db.refresh(sub)
    return {
        "user_id": user_id,
        "tier": sub.tier,
        "valid_until": sub.valid_until.isoformat() if sub.valid_until else None,
        "telegram_channel_to_add": TIER_FEATURES.get(sub.tier, {}).get("telegram_channel"),
        "message": (
            f"Tier set to {sub.tier} for {req.duration_days} days. "
            f"If user gave a Telegram username, admin should add them to channel: "
            f"{TIER_FEATURES.get(sub.tier, {}).get('telegram_channel') or 'NONE'}"
        ),
    }
