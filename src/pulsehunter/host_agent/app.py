from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from pulsehunter.agent.runtime import AgentControlLoop
from pulsehunter.host_agent.config import HostAgentSettings
from pulsehunter.host_agent.runtime import HostEngine
from pulsehunter.schemas.agent import AgentExecutionRequest, AgentExecutionResponse


def create_app(settings: HostAgentSettings) -> FastAPI:
    engine = HostEngine()
    control_loop = AgentControlLoop(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(control_loop.run())
        try:
            yield
        finally:
            control_loop.stop()
            await task

    app = FastAPI(title=f"PulseHunter Windows host agent: {settings.name}", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "agent": settings.name, "device_type": settings.device_type}

    @app.post("/v1/jobs/{job_id}/execute", response_model=AgentExecutionResponse)
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
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return app
