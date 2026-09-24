from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration shared by the API and Celery processes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PULSEHUNTER_",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "PulseHunter"
    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://pulsehunter:pulsehunter@postgres:5432/pulsehunter"
    redis_url: str = "redis://redis:6379/0"
    log_level: str = "INFO"

    job_timeout_seconds: float = Field(default=4.0, gt=0)
    host_job_timeout_seconds: float = Field(default=10.0, gt=0)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=1.0, gt=0)
    retry_backoff_max_seconds: float = Field(default=10.0, gt=0)
    job_lease_grace_seconds: float = Field(default=5.0, ge=1)

    heartbeat_timeout_seconds: float = Field(default=10.0, gt=1)
    heartbeat_scan_interval_seconds: float = Field(default=3.0, gt=0)
    reconcile_interval_seconds: float = Field(default=2.0, gt=0)

    @model_validator(mode="after")
    def validate_intervals(self) -> Settings:
        if self.heartbeat_scan_interval_seconds >= self.heartbeat_timeout_seconds:
            raise ValueError(
                "heartbeat_scan_interval_seconds must be less than heartbeat_timeout_seconds"
            )
        if self.retry_backoff_max_seconds < self.retry_backoff_seconds:
            raise ValueError(
                "retry_backoff_max_seconds must be greater than or equal to retry_backoff_seconds"
            )
        return self

    @property
    def worker_hard_time_limit_seconds(self) -> int:
        return max(
            10,
            int(
                max(self.job_timeout_seconds, self.host_job_timeout_seconds)
                + self.job_lease_grace_seconds
                + 5
            ),
        )

    @property
    def broker_visibility_timeout_seconds(self) -> int:
        # A task must not be redelivered while a live worker can still own it.
        return max(60, self.worker_hard_time_limit_seconds * 3)


@lru_cache
def get_settings() -> Settings:
    return Settings()
