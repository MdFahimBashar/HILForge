from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from pulsehunter.db.session import SessionLocal
from pulsehunter.models.domain import TestSuite

DEFAULT_SUITE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_SUITE_SLUG = "smoke"
DEFAULT_SUITE_DEFINITION = {
    "checks": ["connectivity", "self_test", "timing"],
    "version": 1,
}


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


def main() -> None:
    with SessionLocal.begin() as session:
        suite = seed_default_suite(session)
        suite_id = suite.id
    print(f"Seeded test suite {DEFAULT_SUITE_SLUG} ({suite_id})")


if __name__ == "__main__":
    main()
