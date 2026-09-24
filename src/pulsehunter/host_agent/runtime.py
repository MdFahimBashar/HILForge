from __future__ import annotations

import asyncio
import logging
import uuid
from time import monotonic

import psutil

from pulsehunter.agent.runtime import CachedExecution
from pulsehunter.core.time import utc_now
from pulsehunter.host_agent.checks import HostCheckError, collect_host_checks
from pulsehunter.host_agent.constants import HOST_SUITE_DEFINITION, HOST_SUITE_SLUG
from pulsehunter.schemas.agent import AgentExecutionRequest, AgentExecutionResponse, AgentOutcome

logger = logging.getLogger(__name__)


class HostEngine:
    """Runs only the predefined host checks, once per accepted job ID."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._executions: dict[uuid.UUID, CachedExecution] = {}

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResponse:
        if (
            request.suite_slug != HOST_SUITE_SLUG
            or request.suite_definition != HOST_SUITE_DEFINITION
        ):
            raise ValueError("Unsupported host validation suite")
        fingerprint = request.model_dump_json(exclude={"deadline"})
        async with self._lock:
            cached = self._executions.get(request.job_id)
            if cached is not None:
                if cached.request_fingerprint != fingerprint:
                    raise ValueError("job_id was reused with a different request")
                task = cached.task
            else:
                if request.deadline <= utc_now():
                    raise ValueError("Job deadline has already expired")
                task = asyncio.create_task(self._run(request))
                self._executions[request.job_id] = CachedExecution(fingerprint, task)
        return await asyncio.shield(task)

    async def _run(self, request: AgentExecutionRequest) -> AgentExecutionResponse:
        started = monotonic()
        try:
            result = await asyncio.to_thread(collect_host_checks)
        except (HostCheckError, MemoryError, OSError, psutil.Error, ValueError) as exc:
            logger.exception(
                "Windows host validation failed", extra={"job_id": str(request.job_id)}
            )
            reason = str(exc) if isinstance(exc, HostCheckError) else type(exc).__name__
            return AgentExecutionResponse(
                job_id=request.job_id,
                outcome=AgentOutcome.FAILED,
                duration_ms=(monotonic() - started) * 1000,
                error_message=f"Host check failed: {reason}",
                logs=["Predefined host validation failed; see agent log on the laptop"],
            )
        return AgentExecutionResponse(
            job_id=request.job_id,
            outcome=AgentOutcome.PASSED,
            duration_ms=(monotonic() - started) * 1000,
            result=result,
            logs=["Completed predefined read-only Windows host checks"],
        )
