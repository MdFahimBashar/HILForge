from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from hilforge.models.domain import (
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
from hilforge.schemas.api import DeviceHeartbeat, DeviceRegister
from hilforge.services.devices import (
    mark_stale_devices_offline,
    record_heartbeat,
    register_device,
)


def registration(name: str = "bench-a") -> DeviceRegister:
    return DeviceRegister(
        name=name,
        device_type="simulated",
        endpoint_url=f"http://{name}:9000",
        capabilities={"board": "virtual-v1"},
    )


def test_registration_is_idempotent_by_device_name(db_session: Session) -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    first = register_device(db_session, registration(), now=now)
    first_id = first.id

    second = register_device(
        db_session,
        DeviceRegister(
            name="bench-a",
            device_type="simulated-v2",
            endpoint_url="http://bench-a:9100",
            capabilities={"board": "virtual-v2"},
        ),
        now=now + timedelta(seconds=1),
    )

    assert second.id == first_id
    assert second.device_type == "simulated-v2"
    assert second.endpoint_url == "http://bench-a:9100"
    assert second.status == DeviceStatus.ONLINE


def test_heartbeat_preserves_busy_state_for_an_active_job(
    db_session: Session,
) -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    device = register_device(db_session, registration(), now=now)
    suite = SuiteModel(
        slug="smoke",
        name="Smoke",
        description="Smoke checks",
        definition={},
    )
    test_run = RunModel(test_suite=suite, status=RunStatus.QUEUED)
    job = JobModel(
        test_run=test_run,
        device=device,
        status=JobStatus.QUEUED,
        attempts=0,
    )
    db_session.add_all([suite, test_run, job])
    db_session.flush()

    updated = record_heartbeat(
        db_session,
        device.id,
        DeviceHeartbeat(),
        now=now + timedelta(seconds=1),
    )

    assert updated.status == DeviceStatus.BUSY


def test_stale_devices_are_marked_offline_at_the_timeout_boundary(
    db_session: Session,
) -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    stale = register_device(db_session, registration("stale"), now=now - timedelta(seconds=10))
    fresh = register_device(db_session, registration("fresh"), now=now - timedelta(seconds=9))

    changed = mark_stale_devices_offline(db_session, timeout_seconds=10, now=now)

    assert changed == 1
    assert stale.status == DeviceStatus.OFFLINE
    assert fresh.status == DeviceStatus.ONLINE
