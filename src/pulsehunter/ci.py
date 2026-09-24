"""Small API-only client for gating CI builds on PulseHunter validation runs."""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from pulsehunter.models.domain import RunStatus
from pulsehunter.schemas.api import RunSource, TestJobRead, TestRunRead, TestSuiteRead

EXIT_PASSED = 0
EXIT_VALIDATION_FAILED = 1
EXIT_CLIENT_ERROR = 2
EXIT_WAIT_TIMEOUT = 3


class CiClientError(RuntimeError):
    """The server could not be used to start or inspect a validation run."""


def _positive_float(value: str) -> float:
    number = float(value)
    if not 0 < number < float("inf"):
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pulsehunter-ci")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="create a validation run and optionally gate on it")
    run.add_argument("--server", required=True, help="PulseHunter API base URL")
    run.add_argument("--suite", required=True, help="test-suite slug from GET /test-suites")
    run.add_argument(
        "--device-id",
        action="append",
        type=uuid.UUID,
        default=[],
        help="reserve this device; repeat to select multiple devices",
    )
    run.add_argument("--wait", action="store_true", help="wait and gate on the final run result")
    run.add_argument("--timeout", type=_positive_float, default=120.0, metavar="SECONDS")
    run.add_argument("--poll-interval", type=_positive_float, default=1.0, metavar="SECONDS")
    run.add_argument("--repository", help="source repository name or URL")
    run.add_argument("--commit", help="source commit SHA")
    run.add_argument("--ref", help="source branch or ref")
    run.add_argument("--build-id", help="source CI build/run identifier")
    return parser


def _request_json(client: httpx.Client, method: str, path: str, **kwargs: Any) -> Any:
    try:
        response = client.request(method, path, **kwargs)
    except httpx.TimeoutException as exc:
        raise CiClientError("PulseHunter server request timed out") from exc
    except httpx.RequestError as exc:
        raise CiClientError(f"PulseHunter server unavailable: {exc.__class__.__name__}") from exc

    if response.is_error:
        try:
            body = response.json()
        except ValueError:
            body = None
        detail = body.get("detail") if isinstance(body, dict) else None
        reason = str(detail or response.reason_phrase).replace("\n", " ")[:240]
        raise CiClientError(f"PulseHunter API returned HTTP {response.status_code}: {reason}")
    try:
        return response.json()
    except ValueError as exc:
        raise CiClientError("PulseHunter API returned invalid JSON") from exc


def _source(args: argparse.Namespace) -> dict[str, str] | None:
    if not any((args.repository, args.commit, args.ref, args.build_id)):
        return None
    if args.commit is None:
        raise CiClientError("--commit is required when source metadata is provided")
    try:
        return RunSource(
            repository=args.repository,
            commit_sha=args.commit,
            ref=args.ref,
            build_id=args.build_id,
        ).model_dump(exclude_none=True)
    except ValidationError as exc:
        raise CiClientError(f"Invalid source metadata: {exc.errors()[0]['msg']}") from exc


def _parse_run(data: Any) -> TestRunRead:
    try:
        return TestRunRead.model_validate(data)
    except ValidationError as exc:
        raise CiClientError("PulseHunter API returned an invalid run response") from exc


def _wait_for_terminal(
    client: httpx.Client,
    run_id: uuid.UUID,
    *,
    timeout: float,
    poll_interval: float,
) -> TestRunRead | None:
    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() >= deadline:
            return None
        run = _parse_run(_request_json(client, "GET", f"runs/{run_id}"))
        if run.status in {RunStatus.PASSED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        time.sleep(min(poll_interval, max(deadline - time.monotonic(), 0)))


def _duration(started_at: datetime | None, completed_at: datetime | None) -> str:
    if started_at is None or completed_at is None:
        return "n/a"
    return f"{(completed_at - started_at).total_seconds():.2f}s"


def _print_summary(run: TestRunRead, jobs: list[TestJobRead]) -> None:
    if run.source is not None:
        print(f"Source commit: {run.source.commit_sha}")
    print(f"Final status: {run.status.value}")
    print(f"Run duration: {_duration(run.started_at, run.completed_at)}")
    print("Devices:")
    for job in sorted(jobs, key=lambda item: item.device_name):
        duration = _duration(job.started_at, job.completed_at)
        reason = ""
        if job.error_message:
            concise = " ".join(job.error_message.split())[:160]
            reason = f" reason={concise}"
        print(
            f"  {job.device_name} ({job.device_id}): {job.status.value}, "
            f"attempts={job.attempts}, duration={duration}{reason}"
        )


def run(args: argparse.Namespace, client: httpx.Client) -> int:
    source = _source(args)
    suites_data = _request_json(client, "GET", "test-suites")
    try:
        suites = TypeAdapter(list[TestSuiteRead]).validate_python(suites_data)
    except ValidationError as exc:
        raise CiClientError("PulseHunter API returned an invalid test-suite list") from exc
    suite = next((item for item in suites if item.slug == args.suite), None)
    if suite is None:
        raise CiClientError(f"Test suite slug '{args.suite}' was not found")

    body: dict[str, Any] = {"test_suite_id": str(suite.id)}
    if args.device_id:
        body["device_ids"] = [str(device_id) for device_id in args.device_id]
    if source is not None:
        body["source"] = source
    created = _parse_run(_request_json(client, "POST", "runs", json=body))
    print(f"Run ID: {created.id}", flush=True)
    print(f"Suite: {suite.slug}", flush=True)
    if not args.wait:
        print("Run accepted; --wait is required for CI build gating")
        return EXIT_PASSED

    final = _wait_for_terminal(
        client,
        created.id,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    if final is None:
        print(f"Final status: client wait timed out after {args.timeout:g}s", file=sys.stderr)
        return EXIT_WAIT_TIMEOUT
    jobs_data = _request_json(client, "GET", f"runs/{created.id}/jobs")
    try:
        jobs = TypeAdapter(list[TestJobRead]).validate_python(jobs_data)
    except ValidationError as exc:
        raise CiClientError("PulseHunter API returned an invalid job list") from exc
    _print_summary(final, jobs)
    return EXIT_PASSED if final.status == RunStatus.PASSED else EXIT_VALIDATION_FAILED


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        url = httpx.URL(args.server)
        if url.scheme not in {"http", "https"} or url.host is None:
            raise CiClientError("--server must be an absolute http:// or https:// URL")
        with httpx.Client(base_url=f"{str(url).rstrip('/')}/", timeout=5.0) as client:
            return run(args, client)
    except (httpx.InvalidURL, CiClientError) as exc:
        print(f"pulsehunter-ci: {exc}", file=sys.stderr)
        return EXIT_CLIENT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
