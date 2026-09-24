from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from pulsehunter.core.time import utc_now
from pulsehunter.db.seed import seed_default_suite, seed_host_suite
from pulsehunter.db.session import get_db
from pulsehunter.main import app
from pulsehunter.models.domain import Device, DeviceStatus, JobStatus
from pulsehunter.models.domain import TestJob as JobModel
from pulsehunter.services.runs import recompute_run_status
from pulsehunter.web import primary_network_addresses

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
    assert detail.json()["source"] is None
    assert device_detail.json()["status"] == "busy"


def test_ci_source_is_validated_and_persisted(
    api_request: ApiRequest,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = seed_default_suite(db_session)
    db_session.commit()
    device = api_request("POST", "/internal/devices/register", registration_body())
    monkeypatch.setattr("pulsehunter.web.enqueue_jobs", lambda _: None)
    source = {
        "repository": "team/firmware",
        "commit_sha": "a" * 40,
        "ref": "refs/heads/main",
        "build_id": "1234",
    }
    request_body = {
        "test_suite_id": str(suite.id),
        "device_ids": [device.json()["id"]],
        "source": source,
    }
    invalid = api_request("POST", "/runs", {**request_body, "source": {"commit_sha": "bad!"}})
    assert invalid.status_code == 422

    created = api_request("POST", "/runs", request_body)
    assert created.status_code == 202
    assert created.json()["source"] == source
    assert api_request("GET", f"/runs/{created.json()['id']}").json()["source"] == source


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


def test_dashboard_shows_physical_host_suite_and_heartbeat_state(
    api_request: ApiRequest,
    db_session: Session,
) -> None:
    seed_default_suite(db_session)
    seed_host_suite(db_session)
    db_session.commit()
    simulator = api_request("POST", "/internal/devices/register", registration_body("sim-ui"))
    host = api_request(
        "POST",
        "/internal/devices/register",
        {
            "name": "fahim-laptop",
            "device_type": "windows-host",
            "endpoint_url": "http://192.168.30.83:9000",
            "capabilities": {"simulated": False, "supported_suites": ["host-health"]},
        },
    )
    response = api_request("GET", "/")
    assert response.status_code == 200
    assert "fahim-laptop" in response.text
    assert "PHYSICAL" in response.text
    assert "SIMULATOR" in response.text
    assert 'data-supported-suites="host-health"' in response.text
    assert 'data-supported-suites="smoke"' in response.text
    assert 'data-suite-slug="host-health"' in response.text

    device = db_session.get(Device, uuid.UUID(host.json()["id"]))
    assert device is not None
    device.last_heartbeat_at = utc_now() - timedelta(minutes=1)
    db_session.commit()
    assert (
        next(
            item
            for item in api_request("GET", "/devices").json()
            if item["id"] == host.json()["id"]
        )["status"]
        == "offline"
    )
    assert 'data-device-status="offline"' in api_request("GET", "/").text

    heartbeat = api_request("POST", f"/internal/devices/{host.json()['id']}/heartbeat")
    assert heartbeat.json()["status"] == "online"
    db_session.expunge_all()  # SQLite returns naive datetimes; avoid its stale identity-map value.
    assert (
        next(
            item
            for item in api_request("GET", "/devices").json()
            if item["id"] == host.json()["id"]
        )["status"]
        == "online"
    )
    assert simulator.json()["status"] == "online"


def test_primary_network_summary_excludes_noisy_interfaces_and_addresses() -> None:
    interfaces = {
        "Bluetooth Network Connection": ["169.254.137.165"],
        "Loopback Pseudo-Interface 1": ["127.0.0.1", "::1"],
        "vEthernet (Default Switch)": ["172.20.0.1"],
        "Ethernet 2": ["169.254.1.2", "192.168.30.80"],
        "Wi-Fi": ["fe80::f4fc%12", "192.168.30.83", "2607:fa49:6540:3000::fba3"],
    }

    assert primary_network_addresses(interfaces) == [
        ("Wi-Fi", ["192.168.30.83", "2607:fa49:6540:3000::fba3"]),
        ("Ethernet 2", ["192.168.30.80"]),
    ]
    assert primary_network_addresses({"Wi-Fi": ["fe80::1", "169.254.1.2"]}) == []


def test_host_run_detail_renders_readable_results_and_raw_payload(
    api_request: ApiRequest,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suite = seed_host_suite(db_session)
    db_session.commit()
    host = api_request(
        "POST",
        "/internal/devices/register",
        {
            "name": "fahim-laptop",
            "device_type": "windows-host",
            "endpoint_url": "http://192.168.30.83:9000",
            "capabilities": {"simulated": False, "supported_suites": ["host-health"]},
        },
    )
    monkeypatch.setattr("pulsehunter.web.enqueue_jobs", lambda _: None)
    created = api_request(
        "POST",
        "/runs",
        {"test_suite_id": str(suite.id), "device_ids": [host.json()["id"]]},
    )
    assert created.status_code == 202
    job = db_session.query(JobModel).filter_by(test_run_id=uuid.UUID(created.json()["id"])).one()
    job.status = JobStatus.PASSED
    job.result = {
        "checks_total": 9,
        "checks_passed": 9,
        "system": {
            "hostname": "fahim-laptop",
            "os": "Windows",
            "release": "11",
            "architecture": "AMD64",
        },
        "cpu": {"physical_cores": 8, "logical_cores": 16},
        "memory": {
            "total_bytes": 17179869184,
            "available_bytes": 8589934592,
            "integrity": {"sha256_match": True},
        },
        "disk": {
            "total_bytes": 536870912000,
            "free_bytes": 268435456000,
            "integrity": {"sha256_match": True, "duration_ms": 23.4},
        },
        "uptime_seconds": 90061,
        "network": {
            "interfaces": {
                "Bluetooth Network Connection": ["169.254.137.165"],
                "Loopback Pseudo-Interface 1": ["127.0.0.1"],
                "Wi-Fi": ["fe80::1", "192.168.30.83"],
            }
        },
        "battery": {"available": True, "percent": 78, "charging": True},
    }
    recompute_run_status(db_session, uuid.UUID(created.json()["id"]))
    db_session.commit()

    detail = api_request("GET", f"/runs/{created.json()['id']}/view")
    assert detail.status_code == 200
    assert "Passed" in detail.text
    for expected in (
        "Physical host health",
        "Windows 11",
        "8 physical / 16 logical",
        "16.0 GiB total",
        "8.0 GiB available",
        "integrity passed",
        "23.4 ms",
        "1d 1h 1m",
        "Wi-Fi",
        "192.168.30.83",
        "Primary network addresses",
        "All network interfaces",
        "Bluetooth Network Connection",
        "Loopback Pseudo-Interface 1",
        "78%",
        "Charging",
        "Raw result payload",
    ):
        assert expected in detail.text
    primary = detail.text.split('<div class="host-network">', 1)[1].split("</section>", 1)[0]
    assert "192.168.30.83" in primary
    assert "Bluetooth" not in primary
    assert "Loopback" not in primary
    assert "fe80::1" not in primary
