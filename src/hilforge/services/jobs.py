from __future__ import annotations

from datetime import datetime

from hilforge.core.time import utc_now
from hilforge.models.domain import TERMINAL_JOB_STATUSES, JobStatus, TestJob


class InvalidJobTransitionError(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.RETRYING,
            JobStatus.PASSED,
            JobStatus.FAILED,
            JobStatus.TIMED_OUT,
        }
    ),
    JobStatus.RETRYING: frozenset({JobStatus.RUNNING}),
    JobStatus.PASSED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.TIMED_OUT: frozenset(),
}


def transition_job(
    job: TestJob,
    target: JobStatus,
    *,
    now: datetime | None = None,
) -> TestJob:
    """Apply one legal job transition while keeping terminal updates idempotent."""

    current_time = now or utc_now()
    if job.status == target:
        return job
    if target not in _ALLOWED_TRANSITIONS[job.status]:
        raise InvalidJobTransitionError(
            f"Cannot transition job from {job.status.value} to {target.value}"
        )

    job.status = target
    if target == JobStatus.RUNNING:
        if job.started_at is None:
            job.started_at = current_time
        job.completed_at = None
    elif target == JobStatus.RETRYING:
        job.completed_at = None
    elif target in TERMINAL_JOB_STATUSES:
        job.completed_at = current_time
        job.lease_expires_at = None
        job.next_attempt_at = None
    return job
