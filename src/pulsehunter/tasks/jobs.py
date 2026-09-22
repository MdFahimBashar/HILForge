from __future__ import annotations

import uuid
from typing import Any

from pulsehunter.core.config import get_settings
from pulsehunter.db.session import SessionLocal
from pulsehunter.queueing import enqueue_job
from pulsehunter.services.device_client import HttpDeviceClient
from pulsehunter.services.execution import JobExecutor
from pulsehunter.tasks.celery_app import celery_app


def _publish_retry(job_id: uuid.UUID, delay: float) -> None:
    enqueue_job(job_id, countdown=delay)


@celery_app.task(name="pulsehunter.execute_job", bind=True)
def execute_job(task: Any, job_id: str) -> str:
    request = task.request
    task_id = str(getattr(request, "id", "unknown"))
    executor = JobExecutor(
        SessionLocal,
        HttpDeviceClient(),
        get_settings(),
        _publish_retry,
    )
    return executor.execute(uuid.UUID(job_id), worker_task_id=task_id)
