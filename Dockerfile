# syntax=docker/dockerfile:1.7

FROM python:3.14-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip wheel --wheel-dir /wheels .


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 pulsehunter \
    && useradd --system --uid 10001 --gid pulsehunter --create-home pulsehunter

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl \
    && rm -rf /wheels

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

USER pulsehunter

EXPOSE 8000 9000

STOPSIGNAL SIGTERM

CMD ["uvicorn", "pulsehunter.main:app", "--host", "0.0.0.0", "--port", "8000"]
