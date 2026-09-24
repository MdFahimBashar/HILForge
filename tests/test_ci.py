from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pulsehunter import ci

SUITE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
RUN_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
DEVICE_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
JOB_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
COMMIT_SHA = "a" * 40


def _run(status: str, source: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "id": str(RUN_ID),
        "test_suite_id": str(SUITE_ID),
        "test_suite_name": "Smoke validation",
        "status": status,
        "created_at": "2026-09-24T12:00:00Z",
        "started_at": "2026-09-24T12:00:01Z" if status != "queued" else None,
        "completed_at": "2026-09-24T12:00:03Z" if status in {"passed", "failed"} else None,
        "counts": {
            "total": 1,
            "queued": 1 if status == "queued" else 0,
            "running": 0,
            "retrying": 0,
            "passed": 1 if status == "passed" else 0,
            "failed": 1 if status == "failed" else 0,
            "timed_out": 0,
        },
        "source": source,
    }


def _job(status: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "id": str(JOB_ID),
        "test_run_id": str(RUN_ID),
        "device_id": str(DEVICE_ID),
        "device_name": "sim-healthy",
        "status": status,
        "attempts": 2 if status == "failed" else 1,
        "result": {"checks_passed": 1} if status == "passed" else None,
        "logs": [],
        "error_message": reason,
        "error_details": None,
        "created_at": "2026-09-24T12:00:00Z",
        "started_at": "2026-09-24T12:00:01Z",
        "completed_at": "2026-09-24T12:00:03Z",
        "execution_duration": 2.0,
    }


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver/")


def _args(*extra: str) -> argparse.Namespace:
    return ci._parser().parse_args(
        ["run", "--server", "http://testserver", "--suite", "smoke", "--wait", *extra]
    )


@pytest.mark.parametrize(
    ("final_status", "job_status", "expected_exit", "reason"),
    [
        ("passed", "passed", ci.EXIT_PASSED, None),
        ("failed", "failed", ci.EXIT_VALIDATION_FAILED, "validation failed"),
        ("failed", "timed_out", ci.EXIT_VALIDATION_FAILED, "device timed out"),
    ],
)
def test_ci_waits_and_gates_on_final_result(
    final_status: str,
    job_status: str,
    expected_exit: int,
    reason: str | None,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    source = {"commit_sha": COMMIT_SHA, "repository": "team/firmware"}

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if request.url.path == "/test-suites":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(SUITE_ID),
                        "slug": "smoke",
                        "name": "Smoke validation",
                        "description": "smoke",
                        "definition": {},
                        "created_at": "2026-09-24T12:00:00Z",
                    }
                ],
            )
        if request.url.path == "/runs" and request.method == "POST":
            body = json.loads(request.content)
            assert body["device_ids"] == [str(DEVICE_ID)]
            assert body["source"] == source
            return httpx.Response(202, json=_run("queued", source))
        if request.url.path == f"/runs/{RUN_ID}":
            polls = seen.count(f"GET /runs/{RUN_ID}")
            return httpx.Response(200, json=_run("queued" if polls == 1 else final_status, source))
        if request.url.path == f"/runs/{RUN_ID}/jobs":
            return httpx.Response(200, json=[_job(job_status, reason)])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(ci.time, "sleep", lambda _: None)
    with _client(respond) as client:
        outcome = ci.run(
            _args(
                "--device-id",
                str(DEVICE_ID),
                "--repository",
                "team/firmware",
                "--commit",
                COMMIT_SHA,
            ),
            client,
        )

    assert outcome == expected_exit
    assert seen.count(f"GET /runs/{RUN_ID}") == 2
    output = capsys.readouterr().out
    assert str(RUN_ID) in output
    assert "Suite: smoke" in output
    assert f"Final status: {final_status}" in output
    assert "sim-healthy" in output
    assert "attempts=" in output and "duration=2.00s" in output
    if reason is not None:
        assert reason in output


def test_ci_wait_deadline_returns_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/test-suites":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(SUITE_ID),
                        "slug": "smoke",
                        "name": "Smoke validation",
                        "description": "smoke",
                        "definition": {},
                        "created_at": "2026-09-24T12:00:00Z",
                    }
                ],
            )
        return httpx.Response(202 if request.method == "POST" else 200, json=_run("queued"))

    with _client(respond) as client:
        outcome = ci.run(_args("--timeout", "0.01", "--poll-interval", "0.001"), client)
    assert outcome == ci.EXIT_WAIT_TIMEOUT
    assert "timed out" in capsys.readouterr().err


def test_ci_server_failure_returns_nonzero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = _client(offline)
    monkeypatch.setattr(ci.httpx, "Client", lambda **_: client)
    outcome = ci.main(["run", "--server", "http://testserver", "--suite", "smoke", "--wait"])
    assert outcome == ci.EXIT_CLIENT_ERROR
    assert "server unavailable" in capsys.readouterr().err


def test_ci_run_creation_failure_returns_nonzero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/test-suites":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(SUITE_ID),
                        "slug": "smoke",
                        "name": "Smoke validation",
                        "description": "smoke",
                        "definition": {},
                        "created_at": "2026-09-24T12:00:00Z",
                    }
                ],
            )
        return httpx.Response(409, json={"detail": "requested device is busy"})

    client = _client(respond)
    monkeypatch.setattr(ci.httpx, "Client", lambda **_: client)
    outcome = ci.main(["run", "--server", "http://testserver", "--suite", "smoke", "--wait"])
    assert outcome == ci.EXIT_CLIENT_ERROR
    assert "HTTP 409: requested device is busy" in capsys.readouterr().err
