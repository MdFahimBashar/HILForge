from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pulsehunter.core.time import heartbeat_is_fresh


def test_heartbeat_freshness_has_an_exact_stale_boundary() -> None:
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)

    assert heartbeat_is_fresh(now - timedelta(seconds=9.999), now=now, timeout_seconds=10)
    assert not heartbeat_is_fresh(now - timedelta(seconds=10), now=now, timeout_seconds=10)
    assert not heartbeat_is_fresh(None, now=now, timeout_seconds=10)
