"""Small, bounded checks of the machine actually running the host agent."""

from __future__ import annotations

import hashlib
import os
import platform
import socket
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

MEMORY_TEST_BYTES = 4 * 1024 * 1024
STORAGE_TEST_BYTES = 1024 * 1024
PATTERN = bytes(range(256))


class HostCheckError(RuntimeError):
    """A predefined host integrity check failed."""


def validate_memory() -> dict[str, Any]:
    started = time.monotonic()
    expected = PATTERN * (MEMORY_TEST_BYTES // len(PATTERN))
    candidate = bytearray(expected)
    if hashlib.sha256(candidate).digest() != hashlib.sha256(expected).digest():
        raise HostCheckError("Bounded memory integrity check failed")
    return {
        "bytes_tested": MEMORY_TEST_BYTES,
        "sha256_match": True,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    }


def validate_storage() -> tuple[dict[str, Any], dict[str, Any]]:
    payload = PATTERN * (STORAGE_TEST_BYTES // len(PATTERN))
    expected_hash = hashlib.sha256(payload).hexdigest()
    with tempfile.TemporaryDirectory(prefix="pulsehunter-host-") as directory:
        usage = psutil.disk_usage(directory)
        path = Path(directory) / "integrity.bin"
        started = time.monotonic()
        with path.open("wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        actual = path.read_bytes()
        if actual != payload or hashlib.sha256(actual).hexdigest() != expected_hash:
            raise HostCheckError("Temporary-file storage integrity check failed")
        validation = {
            "bytes_tested": STORAGE_TEST_BYTES,
            "sha256_match": True,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
        disk = {
            "volume": Path(directory).anchor,
            "total_bytes": usage.total,
            "free_bytes": usage.free,
        }
    return disk, validation


def network_addresses() -> dict[str, list[str]]:
    interfaces: dict[str, list[str]] = {}
    for name, addresses in sorted(psutil.net_if_addrs().items()):
        ip_addresses = [
            item.address for item in addresses if item.family in {socket.AF_INET, socket.AF_INET6}
        ]
        if ip_addresses:
            interfaces[name] = ip_addresses
    return interfaces


def collect_host_checks() -> dict[str, Any]:
    physical = psutil.cpu_count(logical=False)
    logical = psutil.cpu_count(logical=True)
    if physical is None or logical is None or physical < 1 or logical < 1:
        raise HostCheckError("CPU core counts are unavailable")
    memory = psutil.virtual_memory()
    if memory.total < 1 or memory.available < 0:
        raise HostCheckError("System memory information is unavailable")
    boot_time = psutil.boot_time()
    uptime_seconds = max(0.0, time.time() - boot_time)
    try:
        battery = psutil.sensors_battery()
    except OSError, psutil.Error, NotImplementedError:
        battery = None
    disk, storage_validation = validate_storage()
    memory_validation = validate_memory()
    interfaces = network_addresses()
    if not interfaces:
        raise HostCheckError("No IP network addresses are available")

    checks_total = 9 if battery is not None else 8
    return {
        "checks_total": checks_total,
        "checks_passed": checks_total,
        "system": {
            "os": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "hostname": socket.gethostname(),
            "architecture": platform.machine(),
        },
        "cpu": {"physical_cores": physical, "logical_cores": logical},
        "memory": {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "integrity": memory_validation,
        },
        "disk": {**disk, "integrity": storage_validation},
        "uptime_seconds": round(uptime_seconds, 2),
        "network": {"interfaces": interfaces},
        "battery": (
            {"available": False, "percent": None, "charging": None}
            if battery is None
            else {
                "available": True,
                "percent": battery.percent,
                "charging": battery.power_plugged,
            }
        ),
    }
