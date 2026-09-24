from __future__ import annotations

import enum

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentMode(enum.StrEnum):
    HEALTHY = "healthy"
    SLOW = "slow"
    UNRELIABLE = "unreliable"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PULSEHUNTER_AGENT_",
        extra="ignore",
        case_sensitive=False,
    )

    name: str = Field(default="sim-healthy", min_length=1, max_length=100)
    device_type: str = Field(default="simulator", min_length=1, max_length=100)
    public_url: HttpUrl = HttpUrl("http://agent-healthy:9000")
    server_url: HttpUrl = HttpUrl("http://api:8000")
    mode: AgentMode = AgentMode.HEALTHY
    heartbeat_interval_seconds: float = Field(default=2.0, gt=0)
    execution_seconds: float = Field(default=0.5, ge=0)
    outcome_script: str = "transient,pass"

    @field_validator("outcome_script")
    @classmethod
    def validate_outcome_script(cls, value: str) -> str:
        supported = {"pass", "fail", "transient", "disconnect"}
        outcomes = [item.strip().lower() for item in value.split(",") if item.strip()]
        if not outcomes or any(item not in supported for item in outcomes):
            raise ValueError(
                "outcome_script must be a comma-separated list of "
                "pass, fail, transient, or disconnect"
            )
        return ",".join(outcomes)

    @property
    def scripted_outcomes(self) -> list[str]:
        return self.outcome_script.split(",")

    @property
    def registration_capabilities(self) -> dict[str, str | bool]:
        return {"simulated": True, "mode": self.mode.value}
