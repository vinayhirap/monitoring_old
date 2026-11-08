"""Auth API — signup, login, refresh, me, admin user management.

Routes:
    POST /api/auth/signup            create a new user
    POST /api/auth/login             OAuth2 password flow → access + refresh
    POST /api/auth/refresh           swap refresh token for new access
    GET  /api/auth/me                current user profile
    GET  /api/admin/users            list all users (admin only)
    PATCH /api/admin/users/{id}      update user (admin only)
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from datetime import datetime
from fastapi import Request

from app.dependencies import get_db, get_current_user, get_current_admin
from app.models.user import User, VALID_ROLES, ADMIN_ROLES
from app.services import auth_service, audit


router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login_at: datetime | None = None
    last_seen_at: datetime | None = None

    class Config:
        from_attributes = True


class UserUpdateRequest(BaseModel):
    is_active: bool | None = None
    full_name: str | None = None
    role: str | None = None
    # NOTE: `is_superuser` is intentionally NOT exposed here. It is a derived
    # mirror of `role` and is set automatically when role changes. Allowing it
    # as a direct input opened a privilege-escalation vector where an admin
    # could set is_superuser=True while leaving role=USER, bypassing the
    # role-based audit trail.


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.post("/signup", response_model=UserOut, status_code=201,
              summary="Create a new user account")
def signup(req: SignupRequest, db: Annotated[Session, Depends(get_db)]):
    # Password policy — checked here (not at schema layer) so the error
    # message can be specific. The min_length=8 in the schema is a coarse
    # filter; this is the load-bearing check.
    try:
        auth_service.validate_password_strength(req.password)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Normalize email — login lower-cases the input, so signup must store
    # the canonical form too. Without this, a user who signs up as
    # "Foo@Bar.com" cannot log in (login looks up "foo@bar.com" which won't
    # match the as-stored mixed case under case-sensitive DB collation).
    email = req.email.lower().strip()
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing:
        raise HTTPException(409, "An account with that email already exists")

    # First user ever becomes OWNER automatically — bootstrap admin
    is_first = db.query(User).count() == 0
    role = "OWNER" if is_first else "USER"

    user = User(
        email=email,
        hashed_password=auth_service.hash_password(req.password),
        full_name=req.full_name,
        role=role,
        is_active=True,
        is_superuser=(role in ADMIN_ROLES),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Audit
    audit.record(
        actor=user, action="user.signup",
        summary=f"New {role.lower()} signed up: {user.email}",
        target=user,
        details_after={"role": role, "email": user.email},
    )
    return user


@router.post("/login", response_model=LoginResponse,
              summary="Log in via OAuth2 password flow")
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
    request: Request,
):
    email = form.username.lower().strip()
    ip = request.client.host if request.client else None

    # Rate-limit: refuse if (email, ip) is currently locked out from too many
    # recent failures. Lockout is bucketed by (email + ip) — see auth_service.
    remaining = auth_service.check_login_lockout(email, ip)
    if remaining:
        raise HTTPException(
            429,
            f"Too many failed login attempts. Try again in {remaining // 60 + 1} minute(s).",
            headers={"Retry-After": str(remaining)},
        )

    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not auth_service.verify_password(form.password, user.hashed_password):
        # Record the failure under the bucket BEFORE raising — this is what
        # actually drives the rate-limit threshold.
        auth_service.record_login_failure(email, ip)
        raise HTTPException(401, "Incorrect email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        # Don't record this as a "failure" — the credentials were correct;
        # the account is disabled. Counting it would let an attacker DoS a
        # disabled user further by stacking failures.
        raise HTTPException(403, "Account disabled — contact admin")

    # Success — wipe the failure bucket so future attempts start clean.
    auth_service.clear_login_failures(email, ip)

    # Record login activity
    user.last_login_at = datetime.utcnow()
    user.last_seen_at  = datetime.utcnow()
    user.last_login_ip = ip
    db.commit()

    audit.record(
        actor=user, action="auth.login",
        summary=f"Login: {user.email}", target=user,
        ip_address=user.last_login_ip,
    )

    return LoginResponse(
        access_token=auth_service.create_access_token(
            user.id, user.email, user.is_superuser),
        refresh_token=auth_service.create_refresh_token(user.id),
        user={
            "id": user.id, "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_superuser": user.is_superuser,
        },
    )


@router.post("/refresh", response_model=LoginResponse,
              summary="Get new access token from refresh token")
def refresh(req: RefreshRequest, db: Annotated[Session, Depends(get_db)]):
    payload = auth_service.decode_token(req.refresh_token)
    if payload is None or payload.get("typ") != "refresh":
        raise HTTPException(401, "Invalid refresh token")
    user = db.query(User).filter(User.id == int(payload["sub"])).one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(401, "User inactive or deleted")
    return LoginResponse(
        access_token=auth_service.create_access_token(
            user.id, user.email, user.is_superuser),
        refresh_token=auth_service.create_refresh_token(user.id),
        user={
            "id": user.id, "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_superuser": user.is_superuser,
        },
    )


@router.get("/me", response_model=UserOut, summary="Current authenticated user")
def me(user: Annotated[User, Depends(get_current_user)]):
    return user


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

admin_router = APIRouter()


# ---------------------------------------------------------------------------
# List with search + filter + pagination
# ---------------------------------------------------------------------------

@admin_router.get("/users",
                   summary="List users — search, filter, paginate (admin only)")
def list_users(
    actor: Annotated[User, Depends(get_current_admin)],
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
    role: str | None = None,
    active: bool | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """OptScale-style: search by email/name, filter by role and active state,
    paginate. Returns rich user payload + total count for the UI."""
    query = db.query(User)
    if q:
        like = f"%{q.lower().strip()}%"
        from sqlalchemy import or_, func
        query = query.filter(or_(
            func.lower(User.email).like(like),
            func.lower(User.full_name).like(like),
        ))
    if role:
        if role not in VALID_ROLES:
            raise HTTPException(400, f"role must be one of {VALID_ROLES}")
        query = query.filter(User.role == role)
    if active is not None:
        query = query.filter(User.is_active == active)

    total = query.count()
    rows = (query.order_by(User.created_at.desc())
                  .offset(offset).limit(limit).all())

    # Attach subscription tier per user — single query, then dict lookup
    from app.models.subscription import Subscription
    sub_rows = db.query(Subscription).filter(
        Subscription.user_id.in_([r.id for r in rows])
    ).all() if rows else []
    sub_by_user = {s.user_id: s for s in sub_rows}

    users = []
    for u in rows:
        sub = sub_by_user.get(u.id)
        users.append({
            "id": u.id, "email": u.email, "full_name": u.full_name,
            "role": u.role, "is_active": u.is_active,
            "is_superuser": u.is_superuser,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            "last_seen_at":  u.last_seen_at.isoformat()  if u.last_seen_at  else None,
            "last_login_ip": u.last_login_ip,
            "subscription": {
                "tier":        sub.tier if sub else "FREE",
                "is_active":   sub.is_active if sub else True,
                "valid_until": sub.valid_until.isoformat() if (sub and sub.valid_until) else None,
                "telegram_username": sub.telegram_username if sub else None,
            } if sub else {"tier": "FREE", "is_active": True, "valid_until": None, "telegram_username": None},
        })

    return {"total": total, "count": len(users), "offset": offset, "users": users}


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

@admin_router.get("/users/{user_id}",
                   summary="Full detail for one user — includes audit history")
def user_detail(user_id: int,
                 actor: Annotated[User, Depends(get_current_admin)],
                 db: Annotated[Session, Depends(get_db)]):
    u = db.query(User).filter(User.id == user_id).one_or_none()
    if u is None:
        raise HTTPException(404, "User not found")
    from app.models.subscription import Subscription
    sub = db.query(Subscription).filter_by(user_id=u.id).one_or_none()
    history = audit.recent(limit=20, target_user_id=u.id)
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role, "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "last_seen_at":  u.last_seen_at.isoformat()  if u.last_seen_at  else None,
        "last_login_ip": u.last_login_ip,
        "subscription": {
            "tier":        sub.tier if sub else "FREE",
            "is_active":   sub.is_active if sub else True,
            "valid_until": sub.valid_until.isoformat() if (sub and sub.valid_until) else None,
            "telegram_username": sub.telegram_username if sub else None,
        } if sub else None,
        "audit_history": history,
    }


# ---------------------------------------------------------------------------
# Update (role / active / name)
# ---------------------------------------------------------------------------

@admin_router.patch("/users/{user_id}",
                     summary="Update a user — role / status / name (audited)")
def update_user(user_id: int, req: UserUpdateRequest,
                 actor: Annotated[User, Depends(get_current_admin)],
                 db: Annotated[Session, Depends(get_db)]):
    if not actor.can_write():
        raise HTTPException(403, "Read-only admin role cannot modify users")
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")

    # Protect the OWNER role
    if user.role == "OWNER" and actor.role != "OWNER":
        raise HTTPException(403, "Only an OWNER can modify another OWNER")
    if req.role == "OWNER" and actor.role != "OWNER":
        raise HTTPException(403, "Only an existing OWNER can promote to OWNER")

    before = {"role": user.role, "is_active": user.is_active, "full_name": user.full_name}

    if req.is_active is not None:    user.is_active = req.is_active
    if req.full_name is not None:    user.full_name = req.full_name
    if req.role is not None:
        if req.role not in VALID_ROLES:
            raise HTTPException(400, f"role must be one of {VALID_ROLES}")
        # Last-OWNER guard — refuse to demote the only remaining OWNER, which
        # would leave the system with no full-privilege admin. Promotion to
        # OWNER is already gated above; this catches the reverse direction.
        if user.role == "OWNER" and req.role != "OWNER":
            other_owners = (db.query(User)
                            .filter(User.role == "OWNER", User.id != user.id)
                            .count())
            if other_owners == 0:
                raise HTTPException(
                    400,
                    "Refusing to demote the last remaining OWNER — promote "
                    "another user to OWNER first, then demote.",
                )
        user.role = req.role
        user.is_superuser = (req.role in ADMIN_ROLES)

    db.commit()
    db.refresh(user)

    after = {"role": user.role, "is_active": user.is_active, "full_name": user.full_name}
    audit.record(
        actor=actor, action="user.update",
        summary=f"{actor.email} updated {user.email}",
        target=user, details_before=before, details_after=after,
    )
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name,
        "role": user.role, "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "last_seen_at":  user.last_seen_at.isoformat()  if user.last_seen_at  else None,
    }


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------

class BulkOpRequest(BaseModel):
    user_ids: list[int] = Field(..., min_length=1, max_length=100)
    action: str = Field(..., description="activate / deactivate / delete / set_role")
    role: str | None = None


@admin_router.post("/users/bulk",
                    summary="Bulk operations on multiple users")
def bulk_op(req: BulkOpRequest,
             actor: Annotated[User, Depends(get_current_admin)],
             db: Annotated[Session, Depends(get_db)]):
    if not actor.can_write():
        raise HTTPException(403, "Read-only admin role cannot modify users")
    if req.action not in ("activate", "deactivate", "delete", "set_role"):
        raise HTTPException(400, "action must be activate/deactivate/delete/set_role")
    if req.action == "set_role" and req.role not in VALID_ROLES:
        raise HTTPException(400, f"role must be one of {VALID_ROLES}")

    users = db.query(User).filter(User.id.in_(req.user_ids)).all()
    # never let actor lock themselves out
    users = [u for u in users if u.id != actor.id]
    # OWNER protection — applies to ALL mutating bulk actions, not just delete.
    # Without this, a non-OWNER admin could bulk-demote OWNER to USER via
    # set_role, or deactivate them — both equivalent to the single-PATCH
    # protection at update_user but were missing here.
    if req.action in ("delete", "deactivate") or (
        req.action == "set_role" and req.role != "OWNER"
    ):
        if actor.role != "OWNER":
            users = [u for u in users if u.role != "OWNER"]
    if req.action == "set_role" and req.role == "OWNER" and actor.role != "OWNER":
        raise HTTPException(403, "Only an existing OWNER can promote to OWNER")

    count = 0
    for u in users:
        before = {"role": u.role, "is_active": u.is_active}
        if req.action == "activate":
            u.is_active = True
        elif req.action == "deactivate":
            u.is_active = False
        elif req.action == "set_role":
            u.role = req.role
            u.is_superuser = (req.role in ADMIN_ROLES)
        elif req.action == "delete":
            db.delete(u)
        count += 1

    db.commit()
    audit.record(
        actor=actor, action=f"user.bulk.{req.action}",
        summary=f"Bulk {req.action} on {count} user(s)",
        details_after={"affected_user_ids": [u.id for u in users][:50],
                        "role": req.role},
    )
    return {"affected": count, "action": req.action}


# ---------------------------------------------------------------------------
# Invite — admin creates an account directly
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    email: EmailStr
    full_name: str | None = None
    role: str = "USER"
    initial_password: str = Field(..., min_length=8, max_length=128)
    tier: str | None = "FREE"


@admin_router.post("/users/invite",
                    summary="Create an account on behalf of a user")
def invite(req: InviteRequest,
            actor: Annotated[User, Depends(get_current_admin)],
            db: Annotated[Session, Depends(get_db)]):
    if not actor.can_write():
        raise HTTPException(403, "Read-only admin role cannot create users")
    if req.role not in VALID_ROLES:
        raise HTTPException(400, f"role must be one of {VALID_ROLES}")
    if req.role == "OWNER" and actor.role != "OWNER":
        raise HTTPException(403, "Only an existing OWNER can invite an OWNER")
    try:
        auth_service.validate_password_strength(req.initial_password)
    except ValueError as e:
        raise HTTPException(400, str(e))

    email = req.email.lower().strip()
    if db.query(User).filter(User.email == email).one_or_none():
        raise HTTPException(409, "That email is already registered")

    user = User(
        email=email,
        hashed_password=auth_service.hash_password(req.initial_password),
        full_name=req.full_name,
        role=req.role,
        is_active=True,
        is_superuser=(req.role in ADMIN_ROLES),
    )
    db.add(user); db.commit(); db.refresh(user)

    # Bootstrap their subscription if requested
    if req.tier and req.tier != "FREE":
        from app.models.subscription import Subscription, SUBSCRIPTION_TIERS
        if req.tier in SUBSCRIPTION_TIERS:
            sub = Subscription(user_id=user.id, tier=req.tier, is_active=True)
            db.add(sub); db.commit()

    audit.record(
        actor=actor, action="user.invite",
        summary=f"{actor.email} invited {user.email} as {req.role}",
        target=user,
        details_after={"email": user.email, "role": req.role, "tier": req.tier},
    )
    return {
        "id": user.id, "email": user.email, "role": user.role,
        "tier": req.tier, "initial_password_set": True,
        "message": (
            f"Account created. Share credentials with {user.email}: "
            f"email={user.email}, password=<the password you set>. "
            f"They can log in immediately at /login."
        ),
    }


# ---------------------------------------------------------------------------
# Delete one user (audit-logged, owner-protected)
# ---------------------------------------------------------------------------

@admin_router.delete("/users/{user_id}", summary="Delete one user (audited)")
def delete_user(user_id: int,
                 actor: Annotated[User, Depends(get_current_admin)],
                 db: Annotated[Session, Depends(get_db)]):
    if not actor.can_write():
        raise HTTPException(403, "Read-only admin role cannot delete users")
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == actor.id:
        raise HTTPException(400, "You cannot delete your own account")
    if user.role == "OWNER":
        raise HTTPException(403, "OWNER role cannot be deleted")
    email = user.email
    db.delete(user); db.commit()
    audit.record(
        actor=actor, action="user.delete",
        summary=f"{actor.email} deleted {email}",
        details_before={"email": email, "user_id": user_id},
    )
    return {"deleted": True, "user_id": user_id, "email": email}


# ---------------------------------------------------------------------------
# Force password reset (audited)
# ---------------------------------------------------------------------------

class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


@admin_router.post("/users/{user_id}/reset-password",
                    summary="Force-set a user's password (admin only)")
def reset_password(user_id: int, req: PasswordResetRequest,
                    actor: Annotated[User, Depends(get_current_admin)],
                    db: Annotated[Session, Depends(get_db)]):
    if not actor.can_write():
        raise HTTPException(403, "Read-only admin role cannot reset passwords")
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if user is None:
        raise HTTPException(404, "User not found")
    if user.role == "OWNER" and actor.role != "OWNER":
        raise HTTPException(403, "Only an OWNER can reset another OWNER's password")
    try:
        auth_service.validate_password_strength(req.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    user.hashed_password = auth_service.hash_password(req.new_password)
    # Clear any active failure bucket on the reset target — admin resetting
    # the password implies "give them a clean slate"
    auth_service.clear_login_failures(user.email, None)
    db.commit()
    audit.record(
        actor=actor, action="user.password_reset",
        summary=f"{actor.email} reset password for {user.email}",
        target=user,
    )
    return {"reset": True, "user_email": user.email,
             "message": f"Share new password with {user.email} via a secure channel."}


# ---------------------------------------------------------------------------
# Audit log query
# ---------------------------------------------------------------------------

@admin_router.get("/audit-log", summary="Recent admin actions")
def audit_log(_: Annotated[User, Depends(get_current_admin)],
               limit: int = Query(100, ge=1, le=500),
               action: str | None = None):
    return {"entries": audit.recent(limit=limit, action_filter=action)}


# ---------------------------------------------------------------------------
# Subscription summary (admin)
# ---------------------------------------------------------------------------

@admin_router.get("/subscription-summary",
                   summary="Subscription counts + revenue projection")
def subscription_summary(_: Annotated[User, Depends(get_current_admin)],
                          db: Annotated[Session, Depends(get_db)]):
    from app.models.subscription import Subscription, SUBSCRIPTION_TIERS
    summary = {tier: 0 for tier in SUBSCRIPTION_TIERS}
    expiring_soon = 0
    from datetime import datetime, timedelta
    soon_cutoff = datetime.utcnow() + timedelta(days=7)
    rows = db.query(Subscription).all()
    for sub in rows:
        if sub.is_active:
            summary[sub.tier] = summary.get(sub.tier, 0) + 1
        if sub.valid_until and sub.valid_until < soon_cutoff and sub.valid_until > datetime.utcnow():
            expiring_soon += 1
    return {
        "active_by_tier": summary,
        "expiring_in_7d": expiring_soon,
        "total_active":   sum(summary.values()),
    }


# ---------------------------------------------------------------------------
# Engine weight refit — data-driven re-tuning of advanced_ta sub-weights
# ---------------------------------------------------------------------------

@admin_router.get("/online-learner/status",
                   summary="Online-learner diagnostic — model state, weights, sample count")
def online_learner_status(_: Annotated[User, Depends(get_current_admin)]):
    """Inspect the online learner. Returns:
      • n_samples_seen     — how many evaluated signals it's trained on
      • in_sample_win_rate — observed win rate over those samples
      • ready              — true once warmup is complete (n >= 30)
      • weights            — current feature coefficients (interpretable)
      • bias               — intercept term
      • last_updated       — unix timestamp of last SGD step

    Negative weights mean an engine ANTI-predicts wins — useful diagnostic
    for an engine that needs retiring or recalibration."""
    from app.services import online_learner
    return online_learner.get_status()


@admin_router.post("/online-learner/reset",
                    summary="Wipe the online-learner state (OWNER only)")
def online_learner_reset(actor: Annotated[User, Depends(get_current_admin)]):
    """Reset the model to zero-weights. Use when:
      • Adding new engines (feature schema changes)
      • Suspecting divergence (hit-rate dropped below baseline)
      • After a corporate-action storm caused stale-data updates

    The disk state file is overwritten. No recovery — but it's just a small
    file; the model rebuilds from the next ~30 evaluated signals."""
    if actor.role != "OWNER":
        raise HTTPException(403, "Reset requires OWNER role")
    from app.services import online_learner
    return online_learner.reset()


class LearnerTuneRequest(BaseModel):
    lr: float | None = Field(None, ge=0.0001, le=1.0,
                                 description="Learning rate — higher = faster adaptation, more variance")
    l2: float | None = Field(None, ge=0.0, le=1.0,
                                 description="L2 regularization — higher = smaller weight magnitudes")


@admin_router.post("/online-learner/tune",
                    summary="Tune the online-learner hyperparameters (OWNER only)")
def online_learner_tune(req: LearnerTuneRequest,
                          actor: Annotated[User, Depends(get_current_admin)]):
    if actor.role != "OWNER":
        raise HTTPException(403, "Tuning requires OWNER role")
    from app.services import online_learner
    return online_learner.set_hyperparams(lr=req.lr, l2=req.l2)


@admin_router.post("/refit-weights",
                    summary="Refit engine weights from journal data (OWNER only)")
def refit_weights(actor: Annotated[User, Depends(get_current_admin)],
                   db: Annotated[Session, Depends(get_db)],
                   min_samples: int = Query(200, ge=50, le=10000),
                   lookback_days: int = Query(180, ge=14, le=730)):
    """Refit the (VWAP, divergence, MTF momentum) composite weights using
    actual evaluated journal data.

    Output:
      • Recommended new weights
      • In-sample hit rate under the new weights
      • Baseline hit rate under the current weights (30/25/45)
      • Improvement in percentage points

    NB: this endpoint does NOT auto-apply the new weights. Apply manually
    by editing app/engines/advanced_ta.py after reviewing the result. Hard-
    coding the weights via API would be a footgun in production.
    """
    if actor.role != "OWNER":
        raise HTTPException(403, "Refitting weights requires OWNER role")
    from app.services import weight_refit
    result = weight_refit.refit_advanced_ta_weights(
        db, min_samples=min_samples, lookback_days=lookback_days,
    )
    return result.to_dict()
