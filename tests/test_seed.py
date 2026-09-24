from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pulsehunter.db.seed import DEFAULT_SUITE_ID, HOST_SUITE_ID, seed_default_suite, seed_host_suite
from pulsehunter.models.domain import TestSuite as SuiteModel


def test_default_suite_seed_is_idempotent(db_session: Session) -> None:
    first = seed_default_suite(db_session)
    db_session.commit()
    second = seed_default_suite(db_session)
    db_session.commit()

    count = db_session.scalar(select(func.count()).select_from(SuiteModel))
    assert count == 1
    assert first.id == second.id == DEFAULT_SUITE_ID
    assert second.slug == "smoke"


def test_host_suite_seed_is_idempotent(db_session: Session) -> None:
    first = seed_host_suite(db_session)
    db_session.commit()
    second = seed_host_suite(db_session)
    db_session.commit()

    count = db_session.scalar(select(func.count()).select_from(SuiteModel))
    assert count == 1
    assert first.id == second.id == HOST_SUITE_ID
    assert second.slug == "host-health"
