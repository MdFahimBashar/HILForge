from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AgentOutcome(enum.StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class AgentExecutionRequest(BaseModel):
    job_id: uuid.UUID
    run_id: uuid.UUID
    suite_slug: str
    suite_definition: dict[str, Any]
    deadline: datetime


class AgentExecutionResponse(BaseModel):
    job_id: uuid.UUID
    outcome: AgentOutcome
    duration_ms: float = Field(ge=0)
    result: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list, max_length=500)
    error_message: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def failed_response_has_error(self) -> AgentExecutionResponse:
        if self.outcome == AgentOutcome.FAILED and not self.error_message:
            raise ValueError("failed agent responses require error_message")
        return self
