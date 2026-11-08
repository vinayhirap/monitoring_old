"""FastAPI dependencies — authentication, DB session, etc."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User, ADMIN_ROLES
from app.services import auth_service


_bearer = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: Annotated[str | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    payload = auth_service.decode_token(token)
    if payload is None or payload.get("typ") != "access":
        raise HTTPException(401, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Token missing subject")
    user = db.query(User).filter(User.id == int(user_id)).one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(401, "User inactive or deleted")
    return user


def get_current_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    # Authoritative check is on `role`. The `is_superuser` boolean is a
    # mirror kept for backward-compat and is NOT trusted here — see auth.py
    # for why mass-assigning is_superuser was removed.
    if user.role not in ADMIN_ROLES:
        raise HTTPException(403, "Admin privilege required")
    return user


# ---------------------------------------------------------------------------
# Subscription-tier gating
# ---------------------------------------------------------------------------
#
# The subscription tier ladder (lowest → highest):
#     FREE < BASIC < INTERMEDIATE < ADVANCED
#
# `require_tier(min_tier)` returns a FastAPI dependency that:
#   1. Resolves the current user (re-using get_current_user)
#   2. Looks up their active tier (FREE if expired / no row / inactive)
#   3. ADMIN_ROLES bypass the gate entirely — internal staff always get full
#      access regardless of subscription state
#   4. Returns 403 if user's tier < min_tier
#
# Use:
#     @router.get("/options")
#     def options_endpoint(
#         user: User = Depends(require_tier("INTERMEDIATE")),
#     ):
#         ...

_TIER_RANK = {"FREE": 0, "BASIC": 1, "INTERMEDIATE": 2, "ADVANCED": 3}


def _active_tier(db: Session, user_id: int) -> str:
    """Compute current effective tier — same logic as subscription.get_active_tier
    but kept here to avoid an import cycle with the subscription API."""
    from datetime import datetime
    from app.models.subscription import Subscription
    sub = db.query(Subscription).filter_by(user_id=user_id).one_or_none()
    if sub is None or not sub.is_active:
        return "FREE"
    if sub.valid_until and sub.valid_until < datetime.utcnow():
        return "FREE"
    return sub.tier or "FREE"


def require_tier(min_tier: str):
    """Factory returning a dependency that 403s unless the user's tier ≥ min_tier."""
    if min_tier not in _TIER_RANK:
        raise ValueError(f"min_tier must be one of {list(_TIER_RANK)}")
    min_rank = _TIER_RANK[min_tier]

    def _dep(
        user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        # Admins (OWNER/ADMIN/ANALYST) bypass tier gating — they see everything.
        if user.role in ADMIN_ROLES:
            return user
        tier = _active_tier(db, user.id)
        if _TIER_RANK.get(tier, 0) < min_rank:
            raise HTTPException(
                402,    # 402 Payment Required — semantically the right code
                {
                    "message": f"This feature requires {min_tier} or higher. Your tier: {tier}.",
                    "current_tier": tier,
                    "required_tier": min_tier,
                    "upgrade_url": "/portal/profile",
                },
            )
        return user

    return _dep


def get_user_tier(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> tuple[User, str]:
    """Dependency that returns the user + their effective tier — used by
    endpoints that don't OUTRIGHT block lower tiers but want to apply
    differentiated limits (e.g. /top-picks returns fewer rows for FREE)."""
    if user.role in ADMIN_ROLES:
        return user, "ADVANCED"     # admins see everything
    return user, _active_tier(db, user.id)
