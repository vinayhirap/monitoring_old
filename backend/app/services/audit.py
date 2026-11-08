"""Audit-log helper — call from any admin endpoint to record an action.

Failures are swallowed so audit logging never breaks the calling endpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from loguru import logger

from app.database import SessionLocal
from app.models.audit_log import AuditEntry
from app.models.user import User


def record(
    actor: User | None,
    action: str,
    summary: str,
    target: User | None = None,
    details_before: Any = None,
    details_after: Any = None,
    ip_address: str | None = None,
) -> int | None:
    """Persist one audit log entry. Returns row id or None on failure."""
    try:
        with SessionLocal() as sess:
            row = AuditEntry(
                occurred_at=datetime.utcnow(),
                actor_user_id=actor.id if actor else None,
                actor_email=actor.email if actor else "system",
                actor_role=actor.role if actor else "SYSTEM",
                target_user_id=target.id if target else None,
                target_email=target.email if target else None,
                action=action,
                summary=summary,
                details_before=details_before,
                details_after=details_after,
                ip_address=ip_address,
            )
            sess.add(row)
            sess.commit()
            return row.id
    except Exception as e:
        logger.warning("audit.record failed: {}", e)
        return None


def recent(limit: int = 100, action_filter: str | None = None,
            target_user_id: int | None = None) -> list[dict]:
    """Return recent audit entries (newest first)."""
    try:
        with SessionLocal() as sess:
            q = sess.query(AuditEntry).order_by(AuditEntry.occurred_at.desc())
            if action_filter:
                q = q.filter(AuditEntry.action.like(f"{action_filter}%"))
            if target_user_id is not None:
                q = q.filter(AuditEntry.target_user_id == target_user_id)
            rows = q.limit(limit).all()
        return [{
            "id": r.id,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            "actor": {
                "user_id": r.actor_user_id,
                "email":   r.actor_email,
                "role":    r.actor_role,
            },
            "target": {
                "user_id": r.target_user_id,
                "email":   r.target_email,
            } if r.target_user_id else None,
            "action":  r.action,
            "summary": r.summary,
            "details_before": r.details_before,
            "details_after":  r.details_after,
            "ip_address": r.ip_address,
        } for r in rows]
    except Exception as e:
        logger.warning("audit.recent failed: {}", e)
        return []
