"""The only suite accepted by the physical Windows host agent."""

HOST_SUITE_SLUG = "host-health"
HOST_SUITE_CHECKS = [
    "system",
    "cpu",
    "memory",
    "memory_integrity",
    "disk",
    "storage_integrity",
    "uptime",
    "network",
    "battery",
]
HOST_SUITE_DEFINITION = {"checks": HOST_SUITE_CHECKS, "version": 1}
