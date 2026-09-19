from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator

import httpx
import pytest
from sqlalchemy.orm import Session

from hilforge.core.time import utc_now
from hilforge.db.seed import seed_default_suite
from hilforge.db.session import get_db
from hilforge.main import app
from hilforge.schemas.api import DeviceRegister
from hilforge.services.devices import register_device

ApiGet = Callable[[str], httpx.Response]


@pytest.fixture
def api_get(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[ApiGet]:
    monkeypatch.setattr("hilforge.main.redis_is_available", lambda _: True)

    def override_get_db() -> Iterator[Session]:
        yield db_session

    def get(path: str) -> httpx.Response:
        async def request() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                return await client.get(path)

        return asyncio.run(request())

    app.dependency_overrides[get_db] = override_get_db
    yield get
    app.dependency_overrides.clear()


def test_health_reports_database_ready(api_get: ApiGet) -> None:
    response = api_get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "redis": "ok"}


def test_devices_returns_registered_devices(api_get: ApiGet, db_session: Session) -> None:
    register_device(
        db_session,
        DeviceRegister(
            name="bench-a",
            device_type="simulated",
            endpoint_url="http://bench-a:9000",
            capabilities={"board": "virtual-v1"},
        ),
        now=utc_now(),
    )
    db_session.commit()

    response = api_get("/devices")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "bench-a"
    assert response.json()[0]["status"] == "online"


def test_test_suites_returns_seeded_suite(api_get: ApiGet, db_session: Session) -> None:
    seed_default_suite(db_session)
    db_session.commit()

    response = api_get("/test-suites")

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "smoke"
