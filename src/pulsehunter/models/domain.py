from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pulsehunter.db.base import Base


def enum_values(enum_type: type[enum.Enum]) -> list[str]:
    return [str(member.value) for member in enum_type]


class DeviceStatus(enum.StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class RunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.PASSED, JobStatus.FAILED, JobStatus.TIMED_OUT})
ACTIVE_JOB_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING})
TERMINAL_RUN_STATUSES = frozenset({RunStatus.PASSED, RunStatus.FAILED, RunStatus.CANCELLED})


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Device(TimestampMixin, Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    device_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(
            DeviceStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            length=16,
            name="device_status",
        ),
        default=DeviceStatus.OFFLINE,
        nullable=False,
        index=True,
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    jobs: Mapped[list[TestJob]] = relationship(back_populates="device")


class TestSuite(TimestampMixin, Base):
    __tablename__ = "test_suites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    runs: Mapped[list[TestRun]] = relationship(back_populates="test_suite")


class TestRun(TimestampMixin, Base):
    __tablename__ = "test_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_suite_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("test_suites.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(
            RunStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            length=16,
            name="run_status",
        ),
        default=RunStatus.QUEUED,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[dict[str, str] | None] = mapped_column(JSON)

    test_suite: Mapped[TestSuite] = relationship(back_populates="runs")
    jobs: Mapped[list[TestJob]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )


class TestJob(TimestampMixin, Base):
    __tablename__ = "test_jobs"
    __table_args__ = (
        UniqueConstraint("test_run_id", "device_id", name="uq_test_jobs_run_device"),
        Index("ix_test_jobs_dispatchable", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("test_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("devices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            values_callable=enum_values,
            native_enum=False,
            create_constraint=True,
            length=16,
            name="job_status",
        ),
        default=JobStatus.QUEUED,
        nullable=False,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    logs: Mapped[list[str] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_duration: Mapped[float | None] = mapped_column(Float)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker_task_id: Mapped[str | None] = mapped_column(String(64))

    test_run: Mapped[TestRun] = relationship(back_populates="jobs")
    device: Mapped[Device] = relationship(back_populates="jobs")
