from __future__ import annotations

import uuid

from hilforge.tasks.celery_app import celery_app

EXECUTE_JOB_TASK = "hilforge.execute_job"


def enqueue_job(job_id: uuid.UUID, *, countdown: float = 0) -> str:
    """Publish only an identifier; PostgreSQL holds the durable job state and payload."""

    result = celery_app.send_task(
        EXECUTE_JOB_TASK,
        args=[str(job_id)],
        countdown=max(0, countdown),
        ignore_result=True,
    )
    return str(result.id)


def enqueue_jobs(job_ids: list[uuid.UUID]) -> list[str]:
    return [enqueue_job(job_id) for job_id in job_ids]
