from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from pulsehunter.db.seed import seed_default_suite
from pulsehunter.db.session import get_db
from pulsehunter.main import app
from pulsehunter.models.domain import DeviceStatus

ApiRequest = Callable[[str, str, dict[str, Any] | None], httpx.Response]


@pytest.fixture
def api_request(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[ApiRequest]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    def request(
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, json=body)

        return asyncio.run(send())

    monkeypatch.setattr("pulsehunter.main.redis_is_available", lambda _: True)
    app.dependency_overrides[get_db] = override_get_db
    yield request
    app.dependency_overrides.clear()


def registration_body(name: str = "sim-a") -> dict[str, Any]:
    return {
        "name": name,
        "device_type": "simulator",
        "endpoint_url": f"http://{name}:9000",
        "capabilities": {"mode": "healthy"},
    }


def test_registration_and_heartbeat_endpoints_are_idempotent(api_request: ApiRequest) -> None:
    first = api_request("POST", "/internal/devices/register", registration_body())
    second = api_request("POST", "/internal/devices/register", registration_body())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    heartbeat = api_request(
        "POST",
        f"/internal/devices/{first.json()['id']}/heartbeat",
        {"capabilities": {"mode": "healthy", "temperature": 24}},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == DeviceStatus.ONLINE
    assert heartbeat.json()["capabilities"]["temperature"] == 24


def test_run_api_queues_jobs_and_exposes_run_details(
    api_request: ApiRequest,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = seed_default_suite(db_session)
    db_session.commit()
    device = api_request("POST", "/internal/devices/register", registration_body())
    device_id = device.json()["id"]
    published: list[uuid.UUID] = []
    monkeypatch.setattr("pulsehunter.web.enqueue_jobs", lambda ids: published.extend(ids))

    created = api_request(
        "POST",
        "/runs",
        {"test_suite_id": str(suite.id), "device_ids": [device_id]},
    )

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    assert created.json()["counts"]["total"] == 1
    assert len(published) == 1

    run_id = created.json()["id"]
    runs = api_request("GET", "/runs")
    jobs = api_request("GET", f"/runs/{run_id}/jobs")
    detail = api_request("GET", f"/runs/{run_id}")
    device_detail = api_request("GET", f"/devices/{device_id}")

    assert runs.status_code == 200 and runs.json()[0]["id"] == run_id
    assert jobs.status_code == 200 and jobs.json()[0]["id"] == str(published[0])
    assert detail.status_code == 200 and detail.json()["id"] == run_id
    assert device_detail.json()["status"] == "busy"


def test_dashboard_renders_fleet_and_run_controls(
    api_request: ApiRequest,
    db_session: Session,
) -> None:
    seed_default_suite(db_session)
    db_session.commit()
    api_request("POST", "/internal/devices/register", registration_body("sim-dashboard"))

    response = api_request("GET", "/")

    assert response.status_code == 200
    assert "Validation command center" in response.text
    assert "sim-dashboard" in response.text
    assert "Choose devices" in response.text
    assert 'data-testid="run-submit"' in response.text
    assert "/static/dashboard.js" in response.text
