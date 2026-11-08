"""User model — OptScale-style RBAC.

Roles (in priority order, highest first):
  • OWNER   — the org owner; cannot be deleted/demoted by anyone else.
              First-ever signup gets this role automatically.
  • ADMIN   — can manage all users except OWNER. Sees the admin console.
  • ANALYST — internal researcher; sees admin console (read-only) but
              cannot change other users or subscriptions.
  • USER    — regular customer; portal-only, can manage own profile.

is_superuser is retained for backward compat (= role in {OWNER, ADMIN}).
"""
from datetime import datetime, date
from sqlalchemy import String, DateTime, Boolean, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


VALID_ROLES = ("OWNER", "ADMIN", "ANALYST", "USER")
ADMIN_ROLES = ("OWNER", "ADMIN", "ANALYST")
WRITE_ADMIN_ROLES = ("OWNER", "ADMIN")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    # RBAC role — primary access control field
    role: Mapped[str] = mapped_column(String(16), default="USER", index=True)

    # Activity tracking
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)   # kept for compat
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None]  = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Trading kill switch — when False, /api/trade/place refuses ALL orders.
    # Default False so users must explicitly opt in to live trading. There's
    # no paper-trade mode; every order that goes through is real-money.
    trading_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


    def has_role(self, *required: str) -> bool:
        return self.role in required

    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES

    def can_write(self) -> bool:
        return self.role in WRITE_ADMIN_ROLES
