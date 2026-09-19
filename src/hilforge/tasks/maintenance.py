from __future__ import annotations

import logging

from hilforge.core.config import get_settings
from hilforge.db.session import SessionLocal
from hilforge.queueing import enqueue_job
from hilforge.services.maintenance import (
    maintain_device_liveness,
    reconcile_dispatchable_jobs,
)
from hilforge.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="hilforge.mark_stale_devices")
def mark_stale_devices() -> int:
    with SessionLocal() as session:
        return maintain_device_liveness(session, get_settings())


@celery_app.task(name="hilforge.reconcile_jobs")
def reconcile_jobs() -> int:
    with SessionLocal() as session:
        job_ids = reconcile_dispatchable_jobs(session, get_settings())
    published = 0
    for job_id in job_ids:
        try:
            enqueue_job(job_id)
            published += 1
        except Exception:
            logger.exception(
                "Reconciler could not publish a job",
                extra={"job_id": str(job_id)},
            )
    return published
