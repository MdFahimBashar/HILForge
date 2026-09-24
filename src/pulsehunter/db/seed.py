from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from pulsehunter.db.session import SessionLocal
from pulsehunter.host_agent.constants import HOST_SUITE_DEFINITION, HOST_SUITE_SLUG
from pulsehunter.models.domain import TestSuite

DEFAULT_SUITE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_SUITE_SLUG = "smoke"
DEFAULT_SUITE_DEFINITION = {
    "checks": ["connectivity", "self_test", "timing"],
    "version": 1,
}
HOST_SUITE_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


def seed_default_suite(session: Session) -> TestSuite:
    suite = session.scalar(select(TestSuite).where(TestSuite.slug == DEFAULT_SUITE_SLUG))
    if suite is None:
        suite = TestSuite(id=DEFAULT_SUITE_ID, slug=DEFAULT_SUITE_SLUG)
        session.add(suite)

    suite.name = "Simulated Device Smoke Test"
    suite.description = (
        "Predefined connectivity, self-test, and timing checks for simulated devices."
    )
    suite.definition = DEFAULT_SUITE_DEFINITION
    session.flush()
    return suite


def seed_host_suite(session: Session) -> TestSuite:
    suite = session.scalar(select(TestSuite).where(TestSuite.slug == HOST_SUITE_SLUG))
    if suite is None:
        suite = TestSuite(id=HOST_SUITE_ID, slug=HOST_SUITE_SLUG)
        session.add(suite)

    suite.name = "Windows Host Health Check"
    suite.description = "Bounded, read-only inventory and integrity checks on a Windows host."
    suite.definition = HOST_SUITE_DEFINITION
    session.flush()
    return suite


def main() -> None:
    with SessionLocal.begin() as session:
        suite = seed_default_suite(session)
        suite_id = suite.id
        host_suite = seed_host_suite(session)
        host_suite_id = host_suite.id
    print(
        f"Seeded test suites {DEFAULT_SUITE_SLUG} ({suite_id}) and "
        f"{HOST_SUITE_SLUG} ({host_suite_id})"
    )


if __name__ == "__main__":
    main()
