from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize DB timestamps; SQLite can discard timezone information in tests."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def heartbeat_is_fresh(
    last_heartbeat_at: datetime | None,
    *,
    now: datetime,
    timeout_seconds: float,
) -> bool:
    if last_heartbeat_at is None:
        return False
    return ensure_utc(last_heartbeat_at) > ensure_utc(now) - timedelta(seconds=timeout_seconds)
