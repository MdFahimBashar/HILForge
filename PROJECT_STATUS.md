# Project Status

## Current state

The end-to-end local MVP is implemented. PulseHunter can register three standalone
simulated devices, reserve them for a run, dispatch concurrent jobs through
Redis/Celery, persist results in PostgreSQL, retry transient failures, enforce
timeouts, aggregate the run, release devices, and expose the result in REST and
HTML views.

Target runtime: Python 3.14. Release-candidate verification: 2026-09-22.

## Implemented architecture

- FastAPI control plane and server-rendered Jinja dashboard.
- PostgreSQL source of truth with SQLAlchemy 2 and Alembic migration
  `20260917_0001`.
- Redis as Celery broker only; no Celery result backend.
- Celery worker with concurrency 4 and Celery Beat maintenance scheduler.
- Database-backed claims, attempt ownership, leases, reconciliation, retries,
  exponential backoff, timeouts, terminal persistence, aggregation, and release.
- Separate healthy, slow, and unreliable HTTP device-agent processes.
- Docker Compose topology, automated tests, and GitHub Actions quality plus
  Docker end-to-end jobs.

## Implemented features

- meaningful `/health` for PostgreSQL and Redis
- device registration, idempotent re-registration, heartbeats, and stale cutoff
- device list/detail with online, offline, and busy state
- predefined idempotently seeded smoke suite
- run creation/list/detail and per-job result APIs
- all-available or explicit-device reservation
- passing results, validation failures, transient failures, and timeouts
- bounded attempts and capped exponential backoff
- persisted structured result, logs, error details, and duration
- automatic durable-job and expired-worker-lease reconciliation
- dashboard fleet metrics, run creation, recent runs, and job detail
- generated Swagger/OpenAPI at `/docs`

## Verification status

Verified locally on 2026-09-22:

- Python 3.14.5 loaded the installed package and `pip check` found no broken
  requirements.
- `ruff check .` passed and `ruff format --check .` confirmed all 53 files were
  formatted.
- Mypy passed across all 33 source files.
- The host test run passed 26 tests and skipped only the opt-in service test.
- The full Compose-backed test run enabled that service test and passed all 27
  tests against PostgreSQL and Redis.
- `docker compose config --quiet` passed. The Python 3.14 image rebuilt, the
  complete stack was force-recreated, PostgreSQL, Redis, the API, and all three
  agents reported healthy, and the worker and Beat processes remained running.
- Alembic reported no new upgrade operations from the model metadata.
- The automated mixed-behavior run completed three concurrent jobs: healthy
  passed on attempt 1, unreliable passed on attempt 2, slow timed out on attempt
  3, the aggregate run failed as designed, and all devices returned online.

GitHub Actions has passed both the `quality-and-tests` and `docker-e2e` jobs on
the public `main` branch.

## Known issues and limitations

- Trusted-local-development security model: no users, agent auth, TLS, or RBAC.
- Agent URL registration creates an SSRF risk on an untrusted deployment.
- Agent execution idempotency is in memory and is lost on restart.
- No cancellation, priority queue, capability matching, artifact storage,
  streaming logs, metrics dashboards, cloud deployment, or physical hardware.
- The slow simulator intentionally makes an all-device run fail with a timeout.
- Exactly one Celery Beat process should run.

## Commands

```bash
docker compose up --build --detach --wait
python scripts/verify_e2e.py --timeout 90
```

```bash
ruff check .
ruff format --check .
mypy src
pytest -W error
docker compose run --rm migrate alembic check
docker compose run --rm migrate python -m pulsehunter.db.seed
```

## Next recommended milestone

Add authenticated agent enrollment and a capability-aware scheduler before
attempting physical hardware. Those changes strengthen the
existing boundary without adding Kubernetes, cloud deployment, or a second
application architecture.
