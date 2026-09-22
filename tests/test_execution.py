from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from pulsehunter.core.config import Settings
from pulsehunter.core.time import utc_now
from pulsehunter.db.base import Base
from pulsehunter.db.seed import seed_default_suite
from pulsehunter.models.domain import DeviceStatus, JobStatus, RunStatus
from pulsehunter.models.domain import TestJob as JobModel
from pulsehunter.schemas.agent import AgentExecutionRequest, AgentExecutionResponse, AgentOutcome
from pulsehunter.schemas.api import DeviceRegister, RunCreate
from pulsehunter.services.device_client import DeviceTimeoutError, TransientDeviceError
from pulsehunter.services.devices import register_device
from pulsehunter.services.execution import JobExecutor
from pulsehunter.services.runs import create_run


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def settings(*, max_attempts: int = 3) -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        redis_url="redis://unused:6379/0",
        job_timeout_seconds=0.1,
        job_max_attempts=max_attempts,
        retry_backoff_seconds=0.01,
        retry_backoff_max_seconds=0.02,
        job_lease_grace_seconds=1,
        heartbeat_timeout_seconds=30,
        heartbeat_scan_interval_seconds=2,
        reconcile_interval_seconds=1,
    )


def queued_job(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory() as session:
        suite = seed_default_suite(session)
        device = register_device(
            session,
            DeviceRegister(
                name="bench-a",
                device_type="simulator",
                endpoint_url="http://bench-a:9000",
                capabilities={},
            ),
        )
        test_run, job_ids = create_run(
            session,
            RunCreate(test_suite_id=suite.id, device_ids=[device.id]),
            heartbeat_timeout_seconds=30,
        )
        assert test_run.status == RunStatus.QUEUED
        session.commit()
        return job_ids[0]


class PassingClient:
    def execute(
        self,
        endpoint_url: str,
        request: AgentExecutionRequest,
        *,
        timeout_seconds: float,
    ) -> AgentExecutionResponse:
        assert endpoint_url == "http://bench-a:9000"
        assert timeout_seconds > 0
        return AgentExecutionResponse(
            job_id=request.job_id,
            outcome=AgentOutcome.PASSED,
            duration_ms=25,
            result={"voltage_ok": True},
            logs=["boot ok", "measurement ok"],
        )


class TimeoutClient:
    def execute(
        self,
        endpoint_url: str,
        request: AgentExecutionRequest,
        *,
        timeout_seconds: float,
    ) -> AgentExecutionResponse:
        raise DeviceTimeoutError("simulated timeout")


class TransientThenPassingClient(PassingClient):
    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        endpoint_url: str,
        request: AgentExecutionRequest,
        *,
        timeout_seconds: float,
    ) -> AgentExecutionResponse:
        self.calls += 1
        if self.calls == 1:
            raise TransientDeviceError("temporary disconnect")
        return super().execute(
            endpoint_url,
            request,
            timeout_seconds=timeout_seconds,
        )


def make_due(factory: sessionmaker[Session], job_id: uuid.UUID) -> None:
    with factory() as session:
        job = session.get(JobModel, job_id)
        assert job is not None
        job.next_attempt_at = utc_now() - timedelta(seconds=1)
        session.commit()


def test_success_persists_result_aggregates_run_and_releases_device(
    session_factory: sessionmaker[Session],
) -> None:
    job_id = queued_job(session_factory)
    published: list[tuple[uuid.UUID, float]] = []
    executor = JobExecutor(
        session_factory,
        PassingClient(),
        settings(),
        lambda item, delay: published.append((item, delay)),
    )

    assert executor.execute(job_id, worker_task_id="task-1") == "passed"

    with session_factory() as session:
        job = session.get(JobModel, job_id)
        assert job is not None
        assert job.status == JobStatus.PASSED
        assert job.attempts == 1
        assert job.result == {"voltage_ok": True}
        assert job.logs == ["boot ok", "measurement ok"]
        assert job.execution_duration == pytest.approx(0.025)
        assert job.device.status == DeviceStatus.ONLINE
        assert job.test_run.status == RunStatus.PASSED
    assert published == []


def test_transient_failure_retries_then_passes(
    session_factory: sessionmaker[Session],
) -> None:
    job_id = queued_job(session_factory)
    client = TransientThenPassingClient()
    published: list[tuple[uuid.UUID, float]] = []
    executor = JobExecutor(
        session_factory,
        client,
        settings(),
        lambda item, delay: published.append((item, delay)),
    )

    assert executor.execute(job_id, worker_task_id="task-1") == "retrying"
    with session_factory() as session:
        job = session.get(JobModel, job_id)
        assert job is not None
        assert job.status == JobStatus.RETRYING
        assert job.attempts == 1
        assert job.device.status == DeviceStatus.BUSY
        assert job.error_details == {
            "kind": "TransientDeviceError",
            "retryable": True,
            "retry_in_seconds": 0.01,
        }
    assert published == [(job_id, 0.01)]

    make_due(session_factory, job_id)
    assert executor.execute(job_id, worker_task_id="task-2") == "passed"
    with session_factory() as session:
        job = session.get(JobModel, job_id)
        assert job is not None
        assert job.status == JobStatus.PASSED
        assert job.attempts == 2
        assert job.error_message is None


def test_timeout_is_bounded_and_becomes_terminal(
    session_factory: sessionmaker[Session],
) -> None:
    job_id = queued_job(session_factory)
    published: list[tuple[uuid.UUID, float]] = []
    executor = JobExecutor(
        session_factory,
        TimeoutClient(),
        settings(max_attempts=2),
        lambda item, delay: published.append((item, delay)),
    )

    assert executor.execute(job_id, worker_task_id="task-1") == "retrying"
    make_due(session_factory, job_id)
    assert executor.execute(job_id, worker_task_id="task-2") == "timed_out"
    assert executor.execute(job_id, worker_task_id="duplicate") == "ignored"

    with session_factory() as session:
        job = session.scalar(select(JobModel).where(JobModel.id == job_id))
        assert job is not None
        assert job.status == JobStatus.TIMED_OUT
        assert job.attempts == 2
        assert job.device.status == DeviceStatus.ONLINE
        assert job.test_run.status == RunStatus.FAILED
        assert job.completed_at is not None
    assert len(published) == 1
