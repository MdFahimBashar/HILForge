"""Verify the packaged CI client against the running Docker Compose stack."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import uuid
from typing import Any

SOURCE_SHA = "a" * 40


def request_json(base_url: str, path: str) -> Any:
    with urllib.request.urlopen(f"{base_url.rstrip('/')}{path}", timeout=5) as response:
        return json.load(response)


def wait_for_agents(base_url: str, timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            devices = request_json(base_url, "/devices")
            online = {item["name"]: item["id"] for item in devices if item["status"] == "online"}
            if {"sim-healthy", "sim-slow"} <= online.keys():
                return online
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("Healthy and slow agents did not become available")


def verify_case(base_url: str, device_id: str, expected_code: int, expected_job: str) -> None:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "api",
        "pulsehunter-ci",
        "run",
        "--server",
        "http://127.0.0.1:8000",
        "--suite",
        "smoke",
        "--device-id",
        device_id,
        "--repository",
        "example/firmware",
        "--commit",
        SOURCE_SHA,
        "--wait",
        "--timeout",
        "90",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != expected_code:
        raise AssertionError(f"Expected exit {expected_code}, received {result.returncode}")
    if f": {expected_job}," not in result.stdout:
        raise AssertionError(f"Expected device job status {expected_job} in CI summary")
    run_lines = [line for line in result.stdout.splitlines() if line.startswith("Run ID: ")]
    if not run_lines:
        raise AssertionError("CI client did not report a run ID")
    run_id = uuid.UUID(run_lines[0].partition(": ")[2])
    run = request_json(base_url, f"/runs/{run_id}")
    if not run["source"] or (
        run["source"]["repository"] != "example/firmware"
        or run["source"]["commit_sha"] != SOURCE_SHA
    ):
        raise AssertionError("CI source metadata was not persisted")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CI build gating through Docker Compose")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    try:
        agents = wait_for_agents(args.base_url, args.timeout)
        verify_case(args.base_url, agents["sim-healthy"], 0, "passed")
        verify_case(args.base_url, agents["sim-slow"], 1, "timed_out")
    except (AssertionError, OSError, RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"CI E2E verification failed: {exc}", file=sys.stderr)
        return 1
    print("CI build gating verified: healthy passed; slow timed out and failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
