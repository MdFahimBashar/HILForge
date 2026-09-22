from __future__ import annotations

import pytest
from pydantic import ValidationError

from pulsehunter.core.config import Settings


def test_valid_timing_configuration() -> None:
    settings = Settings(
        _env_file=None,
        heartbeat_timeout_seconds=10,
        heartbeat_scan_interval_seconds=3,
        retry_backoff_seconds=1,
        retry_backoff_max_seconds=8,
    )

    assert settings.heartbeat_timeout_seconds == 10
    assert settings.worker_hard_time_limit_seconds > settings.job_timeout_seconds


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {
                "heartbeat_timeout_seconds": 10,
                "heartbeat_scan_interval_seconds": 10,
            },
            "heartbeat_scan_interval_seconds",
        ),
        (
            {"retry_backoff_seconds": 5, "retry_backoff_max_seconds": 4},
            "retry_backoff_max_seconds",
        ),
    ],
)
def test_invalid_timing_configuration_is_rejected(
    overrides: dict[str, float], expected_message: str
) -> None:
    with pytest.raises(ValidationError, match=expected_message):
        Settings(_env_file=None, **overrides)
