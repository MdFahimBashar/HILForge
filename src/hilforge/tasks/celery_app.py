from __future__ import annotations

from celery import Celery

from hilforge.core.config import get_settings
from hilforge.core.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery(
    "hilforge",
    broker=settings.redis_url,
    include=["hilforge.tasks.jobs", "hilforge.tasks.maintenance"],
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    task_ignore_result=True,
    result_backend=None,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=settings.worker_hard_time_limit_seconds,
    broker_transport_options={
        "visibility_timeout": settings.broker_visibility_timeout_seconds,
    },
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "reconcile-jobs": {
            "task": "hilforge.reconcile_jobs",
            "schedule": settings.reconcile_interval_seconds,
        },
        "mark-stale-devices": {
            "task": "hilforge.mark_stale_devices",
            "schedule": settings.heartbeat_scan_interval_seconds,
        },
    },
)
