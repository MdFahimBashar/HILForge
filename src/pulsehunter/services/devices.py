from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from pulsehunter.core.time import heartbeat_is_fresh, utc_now
from pulsehunter.models.domain import (
    ACTIVE_JOB_STATUSES,
    Device,
    DeviceStatus,
    TestJob,
)
from pulsehunter.schemas.api import DeviceHeartbeat, DeviceRegister


class DeviceNotFoundError(LookupError):
    pass


def _has_active_job(session: Session, device_id: uuid.UUID) -> bool:
    active_job = session.scalar(
        select(TestJob.id)
        .where(
            TestJob.device_id == device_id,
            TestJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .limit(1)
    )
    return active_job is not None


def register_device(
    session: Session,
    registration: DeviceRegister,
    *,
    now: datetime | None = None,
) -> Device:
    received_at = now or utc_now()
    device = session.scalar(
        select(Device).where(Device.name == registration.name).with_for_update()
    )
    if device is None:
        device = Device(
            name=registration.name,
            device_type=registration.device_type,
            endpoint_url=str(registration.endpoint_url).rstrip("/"),
            capabilities=registration.capabilities,
            status=DeviceStatus.ONLINE,
            last_heartbeat_at=received_at,
        )
        session.add(device)
        session.flush()
    else:
        device.device_type = registration.device_type
        device.endpoint_url = str(registration.endpoint_url).rstrip("/")
        device.capabilities = registration.capabilities
        device.last_heartbeat_at = received_at
        device.status = (
            DeviceStatus.BUSY if _has_active_job(session, device.id) else DeviceStatus.ONLINE
        )
    return device


def record_heartbeat(
    session: Session,
    device_id: uuid.UUID,
    heartbeat: DeviceHeartbeat,
    *,
    now: datetime | None = None,
) -> Device:
    received_at = now or utc_now()
    device = session.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device is None:
        raise DeviceNotFoundError(str(device_id))

    device.last_heartbeat_at = received_at
    if heartbeat.capabilities is not None:
        device.capabilities = heartbeat.capabilities
    device.status = (
        DeviceStatus.BUSY if _has_active_job(session, device.id) else DeviceStatus.ONLINE
    )
    return device


def mark_stale_devices_offline(
    session: Session,
    *,
    timeout_seconds: float,
    now: datetime | None = None,
) -> int:
    current_time = now or utc_now()
    cutoff = current_time - timedelta(seconds=timeout_seconds)
    result = session.execute(
        update(Device)
        .where(
            Device.status.in_((DeviceStatus.ONLINE, DeviceStatus.BUSY)),
            (Device.last_heartbeat_at.is_(None)) | (Device.last_heartbeat_at <= cutoff),
        )
        .values(status=DeviceStatus.OFFLINE)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def available_devices_query(
    *,
    heartbeat_timeout_seconds: float,
    now: datetime,
) -> Select[tuple[Device]]:
    cutoff = now - timedelta(seconds=heartbeat_timeout_seconds)
    return select(Device).where(
        Device.status == DeviceStatus.ONLINE,
        Device.last_heartbeat_at.is_not(None),
        Device.last_heartbeat_at > cutoff,
    )


def release_device(
    device: Device,
    *,
    heartbeat_timeout_seconds: float,
    now: datetime,
) -> None:
    device.status = (
        DeviceStatus.ONLINE
        if heartbeat_is_fresh(
            device.last_heartbeat_at,
            now=now,
            timeout_seconds=heartbeat_timeout_seconds,
        )
        else DeviceStatus.OFFLINE
    )
