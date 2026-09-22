from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import ValidationError

from pulsehunter.schemas.agent import AgentExecutionRequest, AgentExecutionResponse


class DeviceExecutionError(RuntimeError):
    """Base class for failures while communicating with a device agent."""


class DeviceTimeoutError(DeviceExecutionError):
    pass


class TransientDeviceError(DeviceExecutionError):
    pass


class PermanentDeviceError(DeviceExecutionError):
    pass


class InvalidDeviceResponseError(PermanentDeviceError):
    pass


class DeviceClient(Protocol):
    def execute(
        self,
        endpoint_url: str,
        request: AgentExecutionRequest,
        *,
        timeout_seconds: float,
    ) -> AgentExecutionResponse: ...


class HttpDeviceClient:
    """HTTP adapter that keeps device transport concerns out of job orchestration."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def execute(
        self,
        endpoint_url: str,
        request: AgentExecutionRequest,
        *,
        timeout_seconds: float,
    ) -> AgentExecutionResponse:
        url = f"{endpoint_url.rstrip('/')}/v1/jobs/{request.job_id}/execute"
        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout_seconds),
                transport=self._transport,
            ) as client:
                response = client.post(
                    url,
                    json=request.model_dump(mode="json"),
                    headers={"Idempotency-Key": str(request.job_id)},
                )
        except httpx.TimeoutException as exc:
            raise DeviceTimeoutError(f"Device did not respond within {timeout_seconds:g}s") from exc
        except httpx.RequestError as exc:
            raise TransientDeviceError(f"Device connection failed: {exc}") from exc

        if response.status_code in {408, 425, 429, 502, 503, 504}:
            raise TransientDeviceError(f"Device returned retryable HTTP {response.status_code}")
        if response.is_error:
            raise PermanentDeviceError(f"Device returned HTTP {response.status_code}")

        try:
            result = AgentExecutionResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise InvalidDeviceResponseError("Device returned an invalid result document") from exc
        if result.job_id != request.job_id:
            raise InvalidDeviceResponseError("Device result job_id does not match the request")
        return result
