"""Celery app + scheduled tasks.

Activates only when CELERY_BROKER_URL is set. Without it, all "scheduled"
work is no-op'd (the app still serves API requests synchronously).

To run the worker in production:
    celery -A app.celery_app worker --loglevel=info
    celery -A app.celery_app beat --loglevel=info     # scheduler
"""
from __future__ import annotations

from datetime import timedelta
from loguru import logger

from app.config import settings


_CELERY_ACTIVE = bool(settings.celery_broker_url)

if _CELERY_ACTIVE:
    from celery import Celery

    celery = Celery(
        "marketlens",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend or settings.celery_broker_url,
    )
    celery.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Kolkata",
        enable_utc=True,
        beat_schedule={
            "outcome-tracker-hourly": {
                "task": "app.celery_app.task_mark_outcomes",
                "schedule": timedelta(hours=1),
            },
            "stable-signals-cleanup": {
                "task": "app.celery_app.task_cleanup_stale_signals",
                "schedule": timedelta(days=1),
            },
            "scrip-master-refresh": {
                "task": "app.celery_app.task_refresh_scrip_master",
                "schedule": timedelta(days=1),
            },
        },
    )

    @celery.task(bind=True, max_retries=3, default_retry_delay=300)
    def task_mark_outcomes(self):
        from app.services.outcome_tracker import mark_due_outcomes
        try:
            return mark_due_outcomes()
        except Exception as exc:
            raise self.retry(exc=exc)

    @celery.task
    def task_cleanup_stale_signals():
        from app.engines.signal_stability import cleanup_older_than
        return {"removed": cleanup_older_than(days=30)}

    @celery.task
    def task_refresh_scrip_master():
        from app.services import instruments
        instruments.load(force=True)
        return {"refreshed": True}

else:
    celery = None
    logger.info("Celery disabled (CELERY_BROKER_URL not set) — using in-process synchronous execution")

    def task_mark_outcomes():
        from app.services.outcome_tracker import mark_due_outcomes
        return mark_due_outcomes()

    def task_cleanup_stale_signals():
        from app.engines.signal_stability import cleanup_older_than
        return {"removed": cleanup_older_than(days=30)}
