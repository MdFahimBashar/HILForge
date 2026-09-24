from __future__ import annotations

import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from pulsehunter.agent.runtime import AgentControlLoop
from pulsehunter.core.time import utc_now
from pulsehunter.host_agent import checks
from pulsehunter.host_agent.app import create_app
from pulsehunter.host_agent.checks import HostCheckError
from pulsehunter.host_agent.cli import main as host_agent_main
from pulsehunter.host_agent.config import HostAgentSettings
from pulsehunter.host_agent.constants import HOST_SUITE_DEFINITION, HOST_SUITE_SLUG
from pulsehunter.host_agent.runtime import HostEngine
from pulsehunter.models.domain import DeviceStatus
from pulsehunter.schemas.agent import AgentExecutionRequest, AgentOutcome
from pulsehunter.schemas.api import DeviceRegister
from pulsehunter.services.devices import mark_stale_devices_offline, register_device


def settings() -> HostAgentSettings:
    return HostAgentSettings(
        name="test-windows-laptop",
        server_url="http://desktop.local:8000",
        public_url="http://laptop.local:9000",
    )


def request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        job_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        suite_slug=HOST_SUITE_SLUG,
        suite_definition=HOST_SUITE_DEFINITION,
        deadline=utc_now() + timedelta(seconds=10),
    )


def test_bounded_memory_and_storage_integrity_clean_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    memory = checks.validate_memory()
    disk, storage = checks.validate_storage()

    assert memory["bytes_tested"] == 4 * 1024 * 1024
    assert memory["sha256_match"] is True
    assert storage["bytes_tested"] == 1024 * 1024
    assert storage["sha256_match"] is True
    assert disk["total_bytes"] > 0
    assert list(tmp_path.iterdir()) == []


def test_storage_integrity_failure_still_cleans_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"corrupted")

    with pytest.raises(HostCheckError, match="Temporary-file storage integrity"):
        checks.validate_storage()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("battery_available", [False, True])
def test_host_check_result_reports_real_categories_with_optional_battery(
    monkeypatch: pytest.MonkeyPatch,
    battery_available: bool,
) -> None:
    monkeypatch.setattr(checks.psutil, "cpu_count", lambda logical: 8 if logical else 4)
    monkeypatch.setattr(
        checks.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(total=16_000, available=8_000),
    )
    monkeypatch.setattr(checks.psutil, "boot_time", lambda: 1.0)
    battery = SimpleNamespace(percent=73, power_plugged=True) if battery_available else None
    monkeypatch.setattr(checks.psutil, "sensors_battery", lambda: battery)
    monkeypatch.setattr(checks, "network_addresses", lambda: {"Wi-Fi": ["192.0.2.2"]})
    monkeypatch.setattr(
        checks,
        "validate_storage",
        lambda: ({"total_bytes": 100, "free_bytes": 50}, {"sha256_match": True}),
    )
    monkeypatch.setattr(checks, "validate_memory", lambda: {"sha256_match": True})

    result = checks.collect_host_checks()

    expected_count = 9 if battery_available else 8
    assert result["checks_total"] == result["checks_passed"] == expected_count
    assert result["cpu"] == {"physical_cores": 4, "logical_cores": 8}
    assert result["memory"]["available_bytes"] == 8_000
    assert result["network"]["interfaces"] == {"Wi-Fi": ["192.0.2.2"]}
    assert result["battery"] == {
        "available": battery_available,
        "percent": 73 if battery_available else None,
        "charging": True if battery_available else None,
    }


@pytest.mark.asyncio
async def test_host_engine_is_idempotent_and_rejects_other_suites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def collect() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"checks_total": 8, "checks_passed": 8}

    monkeypatch.setattr("pulsehunter.host_agent.runtime.collect_host_checks", collect)
    engine = HostEngine()
    execution = request()
    first = await engine.execute(execution)
    second = await engine.execute(
        execution.model_copy(update={"deadline": execution.deadline + timedelta(seconds=1)})
    )
    assert first == second
    assert first.outcome == AgentOutcome.PASSED
    assert calls == 1

    with pytest.raises(ValueError, match="Unsupported host validation suite"):
        await engine.execute(execution.model_copy(update={"suite_slug": "smoke"}))


@pytest.mark.asyncio
async def test_host_check_failure_returns_protocol_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> dict[str, int]:
        raise HostCheckError("integrity mismatch")

    monkeypatch.setattr("pulsehunter.host_agent.runtime.collect_host_checks", fail)
    response = await HostEngine().execute(request())

    assert response.outcome == AgentOutcome.FAILED
    assert response.error_message == "Host check failed: integrity mismatch"
    assert response.result == {}


@pytest.mark.asyncio
async def test_host_control_loop_registers_and_heartbeats_using_existing_protocol() -> None:
    device_id = uuid.uuid4()
    requests: list[httpx.Request] = []

    def respond(incoming: httpx.Request) -> httpx.Response:
        requests.append(incoming)
        return httpx.Response(
            200,
            json={
                "id": str(device_id),
                "name": "test-windows-laptop",
                "device_type": "windows-host",
                "status": "online",
                "endpoint_url": "http://laptop.local:9000",
                "last_heartbeat_at": "2026-09-24T12:00:00Z",
                "created_at": "2026-09-24T12:00:00Z",
                "capabilities": settings().registration_capabilities,
            },
        )

    control = AgentControlLoop(settings())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await control._register(client)
        await control._heartbeat(client)

    assert control.device_id == device_id
    assert requests[0].url.path == "/internal/devices/register"
    assert b'"simulated":false' in requests[0].content
    assert b'"device_type":"windows-host"' in requests[0].content
    assert requests[1].url.path == f"/internal/devices/{device_id}/heartbeat"


@pytest.mark.asyncio
async def test_host_http_endpoint_uses_same_job_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pulsehunter.host_agent.runtime.collect_host_checks",
        lambda: {"checks_total": 8, "checks_passed": 8},
    )
    app = create_app(settings())
    execution = request()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://laptop.local:9000"
    ) as client:
        health = await client.get("/health")
        response = await client.post(
            f"/v1/jobs/{execution.job_id}/execute", json=execution.model_dump(mode="json")
        )
        mismatch = await client.post(
            f"/v1/jobs/{uuid.uuid4()}/execute", json=execution.model_dump(mode="json")
        )

    assert health.status_code == 200
    assert response.status_code == 200
    assert response.json()["outcome"] == "passed"
    assert mismatch.status_code == 422


def test_host_public_url_must_advertise_lan_port() -> None:
    with pytest.raises(ValidationError):
        HostAgentSettings(
            name="laptop",
            server_url="http://desktop.local:8000",
            public_url="http://127.0.0.1:9000",
        )


def test_host_device_uses_existing_heartbeat_offline_detection(db_session: Session) -> None:
    registered_at = utc_now()
    device = register_device(
        db_session,
        DeviceRegister(
            name="test-windows-laptop",
            device_type="windows-host",
            endpoint_url="http://laptop.local:9000",
            capabilities=settings().registration_capabilities,
        ),
        now=registered_at,
    )
    db_session.commit()

    marked = mark_stale_devices_offline(
        db_session, timeout_seconds=10, now=registered_at + timedelta(seconds=11)
    )
    db_session.refresh(device)
    assert marked == 1
    assert device.status == DeviceStatus.OFFLINE


def test_host_agent_command_rejects_non_windows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("pulsehunter.host_agent.cli.sys.platform", "linux")
    exit_code = host_agent_main(
        [
            "--server",
            "http://desktop.local:8000",
            "--public-url",
            "http://laptop.local:9000",
            "--name",
            "laptop",
        ]
    )
    assert exit_code == 2
    assert "only on Windows" in capsys.readouterr().err
