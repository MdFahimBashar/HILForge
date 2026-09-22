from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from pulsehunter.core.config import Settings
from pulsehunter.core.time import utc_now
from pulsehunter.db.seed import seed_default_suite
from pulsehunter.models.domain import DeviceStatus, JobStatus
from pulsehunter.schemas.api import DeviceRegister, RunCreate
from pulsehunter.services.devices import register_device
from pulsehunter.services.maintenance import reconcile_dispatchable_jobs
from pulsehunter.services.runs import create_run


def test_reconciler_recovers_an_expired_worker_lease(db_session: Session) -> None:
    suite = seed_default_suite(db_session)
    device = register_device(
        db_session,
        DeviceRegister(
            name="lost-worker-device",
            device_type="simulator",
            endpoint_url="http://lost-worker-device:9000",
        ),
    )
    test_run, _ = create_run(
        db_session,
        RunCreate(test_suite_id=suite.id, device_ids=[device.id]),
        heartbeat_timeout_seconds=30,
    )
    job = test_run.jobs[0]
    job.status = JobStatus.RUNNING
    job.attempts = 1
    job.lease_expires_at = utc_now() - timedelta(seconds=1)
    db_session.flush()
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        redis_url="redis://unused:6379/0",
        job_max_attempts=3,
        heartbeat_timeout_seconds=30,
        heartbeat_scan_interval_seconds=2,
    )

    dispatchable = reconcile_dispatchable_jobs(db_session, settings)

    assert dispatchable == [job.id]
    assert job.status == JobStatus.RETRYING
    assert job.error_details == {"kind": "WorkerLeaseExpired", "retryable": True}
    assert device.status == DeviceStatus.BUSY
