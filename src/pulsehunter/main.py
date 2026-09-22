from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pulsehunter import __version__
from pulsehunter.core.config import get_settings
from pulsehunter.core.logging import configure_logging
from pulsehunter.db.session import get_db
from pulsehunter.models.domain import Device, TestSuite
from pulsehunter.schemas.api import DeviceRead, HealthResponse, TestSuiteRead
from pulsehunter.services.devices import mark_stale_devices_offline
from pulsehunter.services.health import redis_is_available
from pulsehunter.web import router

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PulseHunter",
    version=__version__,
    description="Distributed Device Validation Platform",
)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


@app.get("/health", response_model=HealthResponse)
def health(session: Session = Depends(get_db)) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("Database health check failed", extra={"event": "health_failed"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        ) from exc
    if not redis_is_available(settings.redis_url):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis unavailable",
        )
    return HealthResponse(status="ok", database="ok", redis="ok")


@app.get("/devices", response_model=list[DeviceRead])
def list_devices(session: Session = Depends(get_db)) -> list[Device]:
    mark_stale_devices_offline(
        session,
        timeout_seconds=settings.heartbeat_timeout_seconds,
    )
    devices = list(session.scalars(select(Device).order_by(Device.name)).all())
    session.commit()
    return devices


@app.get("/test-suites", response_model=list[TestSuiteRead])
def list_test_suites(session: Session = Depends(get_db)) -> list[TestSuite]:
    return list(session.scalars(select(TestSuite).order_by(TestSuite.name)).all())


app.include_router(router)
