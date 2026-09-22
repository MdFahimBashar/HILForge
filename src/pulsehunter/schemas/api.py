from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from pulsehunter.models.domain import DeviceStatus, JobStatus, RunStatus


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str


class DeviceRegister(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    device_type: str = Field(min_length=1, max_length=100)
    endpoint_url: HttpUrl
    capabilities: dict[str, Any] = Field(default_factory=dict)


class DeviceHeartbeat(BaseModel):
    capabilities: dict[str, Any] | None = None


class DeviceRead(ApiModel):
    id: uuid.UUID
    name: str
    device_type: str
    status: DeviceStatus
    endpoint_url: str
    last_heartbeat_at: datetime | None
    created_at: datetime
    capabilities: dict[str, Any]


class TestSuiteRead(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    definition: dict[str, Any]
    created_at: datetime


class RunCreate(BaseModel):
    test_suite_id: uuid.UUID
    device_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("device_ids")
    @classmethod
    def unique_device_ids(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("device_ids must not contain duplicates")
        return value


class RunCounts(BaseModel):
    total: int
    queued: int
    running: int
    retrying: int
    passed: int
    failed: int
    timed_out: int


class TestRunRead(ApiModel):
    id: uuid.UUID
    test_suite_id: uuid.UUID
    test_suite_name: str
    status: RunStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    counts: RunCounts


class TestJobRead(ApiModel):
    id: uuid.UUID
    test_run_id: uuid.UUID
    device_id: uuid.UUID
    device_name: str
    status: JobStatus
    attempts: int
    result: dict[str, Any] | None
    logs: list[str] | None
    error_message: str | None
    error_details: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    execution_duration: float | None
