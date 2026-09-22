from __future__ import annotations

import os

import pytest
from redis import Redis
from sqlalchemy import inspect, text

from pulsehunter.core.config import get_settings
from pulsehunter.db.session import engine

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("PULSEHUNTER_RUN_SERVICE_TESTS") != "1",
    reason="set PULSEHUNTER_RUN_SERVICE_TESTS=1 with PostgreSQL and Redis available",
)
def test_real_postgres_schema_and_redis_are_ready() -> None:
    settings = get_settings()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
        tables = set(inspect(connection).get_table_names())
    assert {"devices", "test_suites", "test_runs", "test_jobs"} <= tables

    client: Redis = Redis.from_url(settings.redis_url)
    try:
        assert client.ping() is True
    finally:
        client.close()
