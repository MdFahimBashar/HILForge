from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from time import monotonic

import httpx

from hilforge.agent.config import AgentMode, AgentSettings
from hilforge.schemas.agent import AgentExecutionRequest, AgentExecutionResponse, AgentOutcome
from hilforge.schemas.api import DeviceRead

logger = logging.getLogger(__name__)


class TransientSimulationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachedExecution:
    request_fingerprint: str
    task: asyncio.Task[AgentExecutionResponse]


class AgentEngine:
    """Deterministic simulator with in-process idempotency by job ID."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()
        self._executions: dict[uuid.UUID, CachedExecution] = {}
        self._attempts: dict[uuid.UUID, int] = {}

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResponse:
        fingerprint = request.model_dump_json(exclude={"deadline"})
        async with self._lock:
            cached = self._executions.get(request.job_id)
            if cached is not None:
                if cached.request_fingerprint != fingerprint:
                    raise ValueError("job_id was reused with a different request")
                task = cached.task
            else:
                outcome = self._next_outcome(request.job_id)
                if outcome in {"transient", "disconnect"}:
                    raise TransientSimulationError(
                        f"Simulated {outcome} failure before job acceptance"
                    )
                task = asyncio.create_task(self._run(request, outcome))
                self._executions[request.job_id] = CachedExecution(fingerprint, task)
        return await asyncio.shield(task)

    def _next_outcome(self, job_id: uuid.UUID) -> str:
        if self.settings.mode != AgentMode.UNRELIABLE:
            return "pass"
        attempt = self._attempts.get(job_id, 0)
        self._attempts[job_id] = attempt + 1
        outcomes = self.settings.scripted_outcomes
        return outcomes[min(attempt, len(outcomes) - 1)]

    async def _run(
        self,
        request: AgentExecutionRequest,
        outcome: str,
    ) -> AgentExecutionResponse:
        started = monotonic()
        await asyncio.sleep(self.settings.execution_seconds)
        duration_ms = (monotonic() - started) * 1000
        common = {
            "job_id": request.job_id,
            "duration_ms": duration_ms,
            "logs": [
                f"agent={self.settings.name} mode={self.settings.mode.value}",
                f"suite={request.suite_slug}",
                f"simulated_duration_ms={duration_ms:.1f}",
            ],
        }
        if outcome == "fail":
            return AgentExecutionResponse(
                **common,
                outcome=AgentOutcome.FAILED,
                error_message="Simulated validation assertion failed",
                result={"checks_total": 3, "checks_passed": 2},
            )
        return AgentExecutionResponse(
            **common,
            outcome=AgentOutcome.PASSED,
            result={
                "checks_total": 3,
                "checks_passed": 3,
                "firmware_booted": True,
                "telemetry_valid": True,
            },
        )


class AgentControlLoop:
    """Registers the process as a device and maintains its heartbeat."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.device_id: uuid.UUID | None = None
        self._stop = asyncio.Event()

    async def run(self) -> None:
        timeout = httpx.Timeout(5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            while not self._stop.is_set():
                try:
                    if self.device_id is None:
                        await self._register(client)
                    else:
                        await self._heartbeat(client)
                except httpx.HTTPError, ValueError:
                    logger.exception(
                        "Agent registration or heartbeat failed",
                        extra={"agent": self.settings.name},
                    )
                    self.device_id = None
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self.settings.heartbeat_interval_seconds,
                    )

    def stop(self) -> None:
        self._stop.set()

    async def _register(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            f"{str(self.settings.server_url).rstrip('/')}/internal/devices/register",
            json={
                "name": self.settings.name,
                "device_type": self.settings.device_type,
                "endpoint_url": str(self.settings.public_url).rstrip("/"),
                "capabilities": {
                    "simulated": True,
                    "mode": self.settings.mode.value,
                },
            },
        )
        response.raise_for_status()
        self.device_id = DeviceRead.model_validate(response.json()).id
        logger.info(
            "Agent registered",
            extra={"agent": self.settings.name, "device_id": str(self.device_id)},
        )

    async def _heartbeat(self, client: httpx.AsyncClient) -> None:
        assert self.device_id is not None
        response = await client.post(
            (
                f"{str(self.settings.server_url).rstrip('/')}"
                f"/internal/devices/{self.device_id}/heartbeat"
            ),
            json=None,
        )
        if response.status_code == 404:
            self.device_id = None
            return
        response.raise_for_status()
