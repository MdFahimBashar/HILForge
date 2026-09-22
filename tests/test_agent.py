from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from pydantic import ValidationError

from pulsehunter.agent.config import AgentMode, AgentSettings
from pulsehunter.agent.runtime import AgentEngine, TransientSimulationError
from pulsehunter.core.time import utc_now
from pulsehunter.schemas.agent import AgentExecutionRequest, AgentOutcome


def request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        job_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        suite_slug="smoke",
        suite_definition={"checks": ["boot"]},
        deadline=utc_now() + timedelta(seconds=2),
    )


@pytest.mark.asyncio
async def test_healthy_agent_is_idempotent_for_same_job() -> None:
    engine = AgentEngine(AgentSettings(mode=AgentMode.HEALTHY, execution_seconds=0))
    execution = request()

    first = await engine.execute(execution)
    retry = execution.model_copy(update={"deadline": execution.deadline + timedelta(seconds=1)})
    second = await engine.execute(retry)

    assert first == second
    assert first.outcome == AgentOutcome.PASSED
    assert first.result["checks_passed"] == 3


@pytest.mark.asyncio
async def test_unreliable_agent_transiently_fails_then_passes() -> None:
    engine = AgentEngine(
        AgentSettings(
            mode=AgentMode.UNRELIABLE,
            outcome_script="transient,pass",
            execution_seconds=0,
        )
    )
    execution = request()

    with pytest.raises(TransientSimulationError):
        await engine.execute(execution)
    result = await engine.execute(execution)

    assert result.outcome == AgentOutcome.PASSED


def test_agent_rejects_unknown_script_outcomes() -> None:
    with pytest.raises(ValidationError):
        AgentSettings(outcome_script="pass,explode")
