from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from hilforge.agent.config import AgentSettings
from hilforge.agent.runtime import AgentControlLoop, AgentEngine, TransientSimulationError
from hilforge.core.logging import configure_logging
from hilforge.schemas.agent import AgentExecutionRequest, AgentExecutionResponse

settings = AgentSettings()
configure_logging("INFO")
engine = AgentEngine(settings)
control_loop = AgentControlLoop(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(control_loop.run())
    try:
        yield
    finally:
        control_loop.stop()
        await task


app = FastAPI(
    title=f"HILForge simulated device: {settings.name}",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": settings.name, "mode": settings.mode.value}


@app.post(
    "/v1/jobs/{job_id}/execute",
    response_model=AgentExecutionResponse,
)
async def execute_job(
    job_id: uuid.UUID,
    request: AgentExecutionRequest,
) -> AgentExecutionResponse:
    if job_id != request.job_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Path and body job IDs must match",
        )
    try:
        return await engine.execute(request)
    except TransientSimulationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
