from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from hilforge.models.domain import (
    Device,
    DeviceStatus,
    JobStatus,
    RunStatus,
)
from hilforge.models.domain import (
    TestJob as JobModel,
)
from hilforge.models.domain import (
    TestRun as RunModel,
)
from hilforge.models.domain import (
    TestSuite as SuiteModel,
)
from hilforge.schemas.api import RunCreate
from hilforge.services.jobs import InvalidJobTransitionError, transition_job
from hilforge.services.runs import create_run, recompute_run_status


def add_suite(db_session: Session) -> SuiteModel:
    suite = SuiteModel(
        slug="smoke",
        name="Smoke",
        description="Smoke checks",
        definition={"checks": ["self_test"]},
    )
    db_session.add(suite)
    db_session.flush()
    return suite


def add_device(
    db_session: Session,
    *,
    name: str,
    status: DeviceStatus,
    heartbeat_at: datetime,
) -> Device:
    device = Device(
        name=name,
        device_type="simulated",
        status=status,
        last_heartbeat_at=heartbeat_at,
        endpoint_url=f"http://{name}:9000",
        capabilities={},
    )
    db_session.add(device)
    db_session.flush()
    return device


def test_run_creation_reserves_only_fresh_online_devices(
    db_session: Session,
) -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    suite = add_suite(db_session)
    available = add_device(
        db_session,
        name="available",
        status=DeviceStatus.ONLINE,
        heartbeat_at=now,
    )
    add_device(
        db_session,
        name="offline",
        status=DeviceStatus.OFFLINE,
        heartbeat_at=now,
    )
    add_device(
        db_session,
        name="stale",
        status=DeviceStatus.ONLINE,
        heartbeat_at=now - timedelta(seconds=10),
    )
    add_device(
        db_session,
        name="busy",
        status=DeviceStatus.BUSY,
        heartbeat_at=now,
    )

    test_run, job_ids = create_run(
        db_session,
        RunCreate(test_suite_id=suite.id),
        heartbeat_timeout_seconds=10,
        now=now,
    )

    assert test_run.status == RunStatus.QUEUED
    assert len(job_ids) == 1
    assert available.status == DeviceStatus.BUSY
    assert test_run.jobs[0].device_id == available.id


def test_run_status_aggregates_jobs_and_remains_terminal(
    db_session: Session,
) -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    suite = add_suite(db_session)
    devices = [
        add_device(
            db_session,
            name=f"device-{index}",
            status=DeviceStatus.BUSY,
            heartbeat_at=now,
        )
        for index in range(2)
    ]
    test_run = RunModel(test_suite=suite, status=RunStatus.QUEUED)
    jobs = [
        JobModel(
            test_run=test_run,
            device=device,
            status=JobStatus.QUEUED,
            attempts=0,
        )
        for device in devices
    ]
    db_session.add_all([test_run, *jobs])
    db_session.flush()

    transition_job(jobs[0], JobStatus.RUNNING, now=now)
    recompute_run_status(db_session, test_run.id, now=now)
    assert test_run.status == RunStatus.RUNNING

    transition_job(jobs[0], JobStatus.PASSED, now=now + timedelta(seconds=1))
    transition_job(jobs[1], JobStatus.RUNNING, now=now + timedelta(seconds=1))
    transition_job(jobs[1], JobStatus.PASSED, now=now + timedelta(seconds=2))
    recompute_run_status(db_session, test_run.id, now=now + timedelta(seconds=2))
    completed_at = test_run.completed_at

    assert test_run.status == RunStatus.PASSED
    assert completed_at == now + timedelta(seconds=2)

    recompute_run_status(db_session, test_run.id, now=now + timedelta(seconds=20))
    assert test_run.status == RunStatus.PASSED
    assert test_run.completed_at == completed_at


def test_terminal_job_transition_is_idempotent_but_immutable() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    job = JobModel(status=JobStatus.RUNNING, attempts=1)

    transition_job(job, JobStatus.PASSED, now=now)
    transition_job(job, JobStatus.PASSED, now=now + timedelta(seconds=1))

    assert job.completed_at == now
    with pytest.raises(InvalidJobTransitionError):
        transition_job(job, JobStatus.FAILED, now=now + timedelta(seconds=2))
