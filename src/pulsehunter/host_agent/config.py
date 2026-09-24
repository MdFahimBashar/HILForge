from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from pulsehunter.host_agent.constants import HOST_SUITE_CHECKS, HOST_SUITE_SLUG


class HostAgentSettings(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    public_url: HttpUrl
    server_url: HttpUrl
    device_type: Literal["windows-host"] = "windows-host"
    heartbeat_interval_seconds: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def validate_public_url(self) -> HostAgentSettings:
        if (
            self.public_url.scheme != "http"
            or self.public_url.port != 9000
            or self.public_url.path not in {"", "/"}
        ):
            raise ValueError("public_url must point to the agent root on port 9000")
        if self.public_url.host in {"0.0.0.0", "127.0.0.1", "localhost"}:
            raise ValueError("public_url must advertise a LAN-reachable host, not a bind address")
        return self

    @property
    def registration_capabilities(self) -> dict[str, Any]:
        return {
            "simulated": False,
            "platform": "windows",
            "supported_suites": [HOST_SUITE_SLUG],
            "checks": HOST_SUITE_CHECKS,
        }
