from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from hilforge.core.config import get_settings
from hilforge.db.session import get_db
from hilforge.models.domain import Device, DeviceStatus, JobStatus, TestSuite
from hilforge.queueing import enqueue_jobs
from hilforge.schemas.api import (
    DeviceHeartbeat,
    DeviceRead,
    DeviceRegister,
    RunCreate,
    TestJobRead,
    TestRunRead,
)
from hilforge.services.devices import (
    DeviceNotFoundError,
    record_heartbeat,
    register_device,
)
from hilforge.services.runs import (
    NoAvailableDevicesError,
    TestRunNotFoundError,
    TestSuiteNotFoundError,
    create_run,
    job_read_model,
    list_runs,
    load_run,
    run_read_model,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@router.post(
    "/internal/devices/register",
    response_model=DeviceRead,
    tags=["device agents"],
)
def register_device_endpoint(
    registration: DeviceRegister,
    session: Session = Depends(get_db),
) -> Device:
    device = register_device(session, registration)
    session.commit()
    session.refresh(device)
    return device


@router.post(
    "/internal/devices/{device_id}/heartbeat",
    response_model=DeviceRead,
    tags=["device agents"],
)
def heartbeat_endpoint(
    device_id: uuid.UUID,
    heartbeat: DeviceHeartbeat | None = None,
    session: Session = Depends(get_db),
) -> Device:
    try:
        device = record_heartbeat(session, device_id, heartbeat or DeviceHeartbeat())
    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Device not found"
        ) from exc
    session.commit()
    session.refresh(device)
    return device


@router.get("/devices/{device_id}", response_model=DeviceRead, tags=["devices"])
def get_device(device_id: uuid.UUID, session: Session = Depends(get_db)) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.get("/runs", response_model=list[TestRunRead], tags=["runs"])
def get_runs(session: Session = Depends(get_db)) -> list[TestRunRead]:
    return [run_read_model(test_run) for test_run in list_runs(session)]


@router.post(
    "/runs",
    response_model=TestRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["runs"],
)
def post_run(request: RunCreate, session: Session = Depends(get_db)) -> TestRunRead:
    try:
        test_run, job_ids = create_run(
            session,
            request,
            heartbeat_timeout_seconds=settings.heartbeat_timeout_seconds,
        )
        run_id = test_run.id
        session.commit()
    except TestSuiteNotFoundError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test suite not found",
        ) from exc
    except NoAvailableDevicesError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    try:
        enqueue_jobs(job_ids)
    except Exception:
        logger.exception(
            "Initial queue publication failed; the reconciler will recover the run",
            extra={"run_id": str(run_id)},
        )
    return run_read_model(load_run(session, run_id))


@router.get("/runs/{run_id}", response_model=TestRunRead, tags=["runs"])
def get_run(run_id: uuid.UUID, session: Session = Depends(get_db)) -> TestRunRead:
    try:
        return run_read_model(load_run(session, run_id))
    except TestRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc


@router.get("/runs/{run_id}/jobs", response_model=list[TestJobRead], tags=["runs"])
def get_run_jobs(run_id: uuid.UUID, session: Session = Depends(get_db)) -> list[TestJobRead]:
    try:
        test_run = load_run(session, run_id)
    except TestRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc
    return [job_read_model(job) for job in sorted(test_run.jobs, key=lambda item: item.created_at)]


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, session: Session = Depends(get_db)) -> HTMLResponse:
    devices = list(session.scalars(select(Device).order_by(Device.name)).all())
    runs = list_runs(session, limit=20)
    suites = list(session.scalars(select(TestSuite).order_by(TestSuite.name)).all())
    device_counts = {
        "total": len(devices),
        "online": sum(device.status == DeviceStatus.ONLINE for device in devices),
        "offline": sum(device.status == DeviceStatus.OFFLINE for device in devices),
        "busy": sum(device.status == DeviceStatus.BUSY for device in devices),
    }
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "devices": devices,
            "runs": [run_read_model(test_run) for test_run in runs],
            "suites": suites,
            "device_counts": device_counts,
            "available_devices": [
                device for device in devices if device.status == DeviceStatus.ONLINE
            ],
        },
    )


@router.get("/runs/{run_id}/view", response_class=HTMLResponse, include_in_schema=False)
def run_detail(
    request: Request,
    run_id: uuid.UUID,
    session: Session = Depends(get_db),
) -> HTMLResponse:
    try:
        test_run = load_run(session, run_id)
    except TestRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc
    jobs = [job_read_model(job) for job in sorted(test_run.jobs, key=lambda item: item.created_at)]
    retry_count = sum(max(job.attempts - 1, 0) for job in jobs)
    active_count = sum(job.status in {JobStatus.RUNNING, JobStatus.RETRYING} for job in jobs)
    return templates.TemplateResponse(
        request=request,
        name="run_detail.html",
        context={
            "run": run_read_model(test_run),
            "jobs": jobs,
            "retry_count": retry_count,
            "active_count": active_count,
        },
    )
