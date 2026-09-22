from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pulsehunter.core.config import Settings
from pulsehunter.core.time import utc_now
from pulsehunter.models.domain import JobStatus, TestJob
from pulsehunter.services.devices import mark_stale_devices_offline, release_device
from pulsehunter.services.jobs import transition_job
from pulsehunter.services.runs import recompute_run_status


def maintain_device_liveness(session: Session, settings: Settings) -> int:
    changed = mark_stale_devices_offline(
        session,
        timeout_seconds=settings.heartbeat_timeout_seconds,
    )
    session.commit()
    return changed


def reconcile_dispatchable_jobs(session: Session, settings: Settings) -> list[uuid.UUID]:
    """Recover expired worker leases and return durable jobs that need publishing."""

    now = utc_now()
    expired = list(
        session.scalars(
            select(TestJob)
            .where(
                TestJob.status == JobStatus.RUNNING,
                TestJob.lease_expires_at.is_not(None),
                TestJob.lease_expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    for job in expired:
        if job.attempts >= settings.job_max_attempts:
            transition_job(job, JobStatus.FAILED, now=now)
            job.error_message = "Worker lease expired after the final attempt"
            job.error_details = {"kind": "WorkerLeaseExpired", "retryable": True}
            release_device(
                job.device,
                heartbeat_timeout_seconds=settings.heartbeat_timeout_seconds,
                now=now,
            )
        else:
            transition_job(job, JobStatus.RETRYING, now=now)
            job.next_attempt_at = now
            job.lease_expires_at = None
            job.error_message = "Worker lease expired; scheduling another attempt"
            job.error_details = {"kind": "WorkerLeaseExpired", "retryable": True}
        recompute_run_status(session, job.test_run_id, now=now)

    job_ids = list(
        session.scalars(
            select(TestJob.id)
            .where(
                or_(
                    TestJob.status == JobStatus.QUEUED,
                    (
                        (TestJob.status == JobStatus.RETRYING)
                        & or_(
                            TestJob.next_attempt_at.is_(None),
                            TestJob.next_attempt_at <= now,
                        )
                    ),
                )
            )
            .order_by(TestJob.created_at)
        ).all()
    )
    session.commit()
    return job_ids
