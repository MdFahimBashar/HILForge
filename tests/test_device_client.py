from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest

from pulsehunter.core.time import utc_now
from pulsehunter.schemas.agent import AgentExecutionRequest
from pulsehunter.services.device_client import HttpDeviceClient, TransientDeviceError


def execution_request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        job_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        suite_slug="smoke",
        suite_definition={},
        deadline=utc_now() + timedelta(seconds=1),
    )


def test_http_client_validates_successful_device_result() -> None:
    request = execution_request()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "job_id": str(request.job_id),
                "outcome": "passed",
                "duration_ms": 5,
                "result": {"ok": True},
                "logs": ["done"],
            },
        )

    result = HttpDeviceClient(transport=httpx.MockTransport(handler)).execute(
        "http://agent:9000",
        request,
        timeout_seconds=1,
    )

    assert result.result == {"ok": True}


def test_http_client_classifies_service_unavailable_as_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(TransientDeviceError):
        HttpDeviceClient(transport=httpx.MockTransport(handler)).execute(
            "http://agent:9000",
            execution_request(),
            timeout_seconds=1,
        )
