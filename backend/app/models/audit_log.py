"""Audit log — every admin action recorded with actor + target + payload.

One row per administrative action. Stays forever (no auto-purge) — admin
actions need a clean trail for accountability and compliance.
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, JSON, Index

from app.database import Base


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    occurred_at  = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    actor_user_id   = Column(Integer, index=True)          # who did it
    actor_email     = Column(String(255))
    actor_role      = Column(String(16))
    target_user_id  = Column(Integer, index=True, nullable=True)  # who/what was affected
    target_email    = Column(String(255), nullable=True)
    action          = Column(String(64), index=True)       # e.g. "user.role.change"
    summary         = Column(String(512))                  # one-line human description
    details_before  = Column(JSON, nullable=True)
    details_after   = Column(JSON, nullable=True)
    ip_address      = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_audit_action_occurred", "action", "occurred_at"),
    )
