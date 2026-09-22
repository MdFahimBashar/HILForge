from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from pulsehunter.core.config import Settings
from pulsehunter.core.time import utc_now
from pulsehunter.models.domain import JobStatus, TestJob
from pulsehunter.schemas.agent import AgentExecutionRequest, AgentOutcome
from pulsehunter.services.device_client import (
    DeviceClient,
    DeviceTimeoutError,
    PermanentDeviceError,
    TransientDeviceError,
)
from pulsehunter.services.devices import release_device
from pulsehunter.services.jobs import transition_job
from pulsehunter.services.runs import recompute_run_status

logger = logging.getLogger(__name__)
PublishJob = Callable[[uuid.UUID, float], None]


@dataclass(frozen=True)
class ClaimedJob:
    job_id: uuid.UUID
    run_id: uuid.UUID
    endpoint_url: str
    suite_slug: str
    suite_definition: dict[str, Any]
    attempts: int


class JobExecutor:
    """Own database-backed state transitions around one device HTTP call."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        device_client: DeviceClient,
        settings: Settings,
        publish_job: PublishJob,
    ) -> None:
        self._session_factory = session_factory
        self._device_client = device_client
        self._settings = settings
        self._publish_job = publish_job

    def execute(self, job_id: uuid.UUID, *, worker_task_id: str) -> str:
        claim = self._claim(job_id, worker_task_id=worker_task_id)
        if claim is None:
            return "ignored"

        request = AgentExecutionRequest(
            job_id=claim.job_id,
            run_id=claim.run_id,
            suite_slug=claim.suite_slug,
            suite_definition=claim.suite_definition,
            deadline=utc_now() + timedelta(seconds=self._settings.job_timeout_seconds),
        )
        started = monotonic()
        try:
            response = self._device_client.execute(
                claim.endpoint_url,
                request,
                timeout_seconds=self._settings.job_timeout_seconds,
            )
        except DeviceTimeoutError as exc:
            return self._handle_retryable_failure(
                claim,
                worker_task_id=worker_task_id,
                error=exc,
                exhausted_status=JobStatus.TIMED_OUT,
                elapsed=monotonic() - started,
            )
        except TransientDeviceError as exc:
            return self._handle_retryable_failure(
                claim,
                worker_task_id=worker_task_id,
                error=exc,
                exhausted_status=JobStatus.FAILED,
                elapsed=monotonic() - started,
            )
        except PermanentDeviceError as exc:
            self._finish(
                claim.job_id,
                worker_task_id=worker_task_id,
                target=JobStatus.FAILED,
                elapsed=monotonic() - started,
                error_message=str(exc),
                error_details={"kind": type(exc).__name__, "retryable": False},
            )
            return "failed"
        except Exception as exc:  # a worker bug must become visible and bounded
            logger.exception("Unexpected job execution error", extra={"job_id": str(job_id)})
            return self._handle_retryable_failure(
                claim,
                worker_task_id=worker_task_id,
                error=exc,
                exhausted_status=JobStatus.FAILED,
                elapsed=monotonic() - started,
            )

        target = JobStatus.PASSED if response.outcome == AgentOutcome.PASSED else JobStatus.FAILED
        self._finish(
            claim.job_id,
            worker_task_id=worker_task_id,
            target=target,
            elapsed=response.duration_ms / 1000,
            result=response.result,
            logs=response.logs,
            error_message=response.error_message,
        )
        return target.value

    def _claim(self, job_id: uuid.UUID, *, worker_task_id: str) -> ClaimedJob | None:
        now = utc_now()
        with self._session_factory() as session:
            job = session.scalar(select(TestJob).where(TestJob.id == job_id).with_for_update())
            if job is None:
                logger.warning("Ignoring unknown job", extra={"job_id": str(job_id)})
                return None
            if job.status not in {JobStatus.QUEUED, JobStatus.RETRYING}:
                return None
            if job.status == JobStatus.RETRYING and job.next_attempt_at is not None:
                next_attempt = job.next_attempt_at
                if next_attempt.tzinfo is None:
                    next_attempt = next_attempt.replace(tzinfo=now.tzinfo)
                if next_attempt > now:
                    return None

            transition_job(job, JobStatus.RUNNING, now=now)
            job.attempts += 1
            job.next_attempt_at = None
            job.lease_expires_at = now + timedelta(
                seconds=(
                    self._settings.job_timeout_seconds + self._settings.job_lease_grace_seconds
                )
            )
            job.worker_task_id = worker_task_id
            recompute_run_status(session, job.test_run_id, now=now)
            claim = ClaimedJob(
                job_id=job.id,
                run_id=job.test_run_id,
                endpoint_url=job.device.endpoint_url,
                suite_slug=job.test_run.test_suite.slug,
                suite_definition=dict(job.test_run.test_suite.definition),
                attempts=job.attempts,
            )
            session.commit()
            return claim

    def _handle_retryable_failure(
        self,
        claim: ClaimedJob,
        *,
        worker_task_id: str,
        error: Exception,
        exhausted_status: JobStatus,
        elapsed: float,
    ) -> str:
        if claim.attempts >= self._settings.job_max_attempts:
            self._finish(
                claim.job_id,
                worker_task_id=worker_task_id,
                target=exhausted_status,
                elapsed=elapsed,
                error_message=str(error),
                error_details={"kind": type(error).__name__, "retryable": True},
            )
            return exhausted_status.value

        delay = min(
            self._settings.retry_backoff_seconds * (2 ** (claim.attempts - 1)),
            self._settings.retry_backoff_max_seconds,
        )
        now = utc_now()
        with self._session_factory() as session:
            job = session.scalar(
                select(TestJob).where(TestJob.id == claim.job_id).with_for_update()
            )
            if not self._owns_running_attempt(job, worker_task_id):
                return "ignored"
            assert job is not None
            transition_job(job, JobStatus.RETRYING, now=now)
            job.next_attempt_at = now + timedelta(seconds=delay)
            job.lease_expires_at = None
            job.error_message = str(error)
            job.error_details = {
                "kind": type(error).__name__,
                "retryable": True,
                "retry_in_seconds": delay,
            }
            job.execution_duration = elapsed
            recompute_run_status(session, job.test_run_id, now=now)
            session.commit()

        try:
            self._publish_job(claim.job_id, delay)
        except Exception:
            logger.exception(
                "Retry publication failed; reconciler will recover the job",
                extra={"job_id": str(claim.job_id)},
            )
        return "retrying"

    def _finish(
        self,
        job_id: uuid.UUID,
        *,
        worker_task_id: str,
        target: JobStatus,
        elapsed: float,
        result: dict[str, Any] | None = None,
        logs: list[str] | None = None,
        error_message: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self._session_factory() as session:
            job = session.scalar(select(TestJob).where(TestJob.id == job_id).with_for_update())
            if not self._owns_running_attempt(job, worker_task_id):
                return
            assert job is not None
            transition_job(job, target, now=now)
            job.result = result
            job.logs = logs
            job.error_message = error_message
            job.error_details = error_details
            job.execution_duration = elapsed
            release_device(
                job.device,
                heartbeat_timeout_seconds=self._settings.heartbeat_timeout_seconds,
                now=now,
            )
            recompute_run_status(session, job.test_run_id, now=now)
            session.commit()

    @staticmethod
    def _owns_running_attempt(job: TestJob | None, worker_task_id: str) -> bool:
        return (
            job is not None
            and job.status == JobStatus.RUNNING
            and job.worker_task_id == worker_task_id
        )
