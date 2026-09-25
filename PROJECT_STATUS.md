# Project Status

## Current state

The end-to-end MVP is implemented with three standalone simulators and a
physical Windows host agent. PulseHunter reserves networked devices, dispatches
concurrent jobs through Redis/Celery, persists results in PostgreSQL, recovers
from transient failures, and exposes runs through REST, a dashboard, and a
build-gating CI client. The Windows laptop workflow has been verified manually
end to end on real hardware.

Target runtime: Python 3.14. Local verification: 2026-09-24.

## Implemented architecture

- FastAPI control plane and server-rendered Jinja dashboard.
- PostgreSQL source of truth with SQLAlchemy 2 and Alembic migration
  `20260917_0001`, plus additive run-source migration `20260924_0002`.
- Redis as Celery broker only; no Celery result backend.
- Celery worker with concurrency 4 and Celery Beat maintenance scheduler.
- Database-backed claims, attempt ownership, leases, reconciliation, retries,
  exponential backoff, timeouts, terminal persistence, aggregation, and release.
- Separate healthy, slow, and unreliable HTTP device-agent processes.
- Optional non-containerized Windows host agent using the same HTTP contract.
- Docker Compose topology, automated tests, and GitHub Actions quality plus
  Docker end-to-end jobs, including CI-client pass/fail gating.

## Implemented features

- meaningful `/health` for PostgreSQL and Redis
- device registration, idempotent re-registration, heartbeats, and stale cutoff
- device list/detail with online, offline, and busy state
- predefined idempotently seeded simulator and Windows-host suites
- run creation/list/detail and per-job result APIs
- all-available or explicit-device reservation
- passing results, validation failures, transient failures, and timeouts
- bounded attempts and capped exponential backoff
- persisted structured result, logs, error details, and duration
- automatic durable-job and expired-worker-lease reconciliation
- dashboard fleet metrics, compatible-device selection, run creation, recent
  runs, readable physical-host results, and raw technical detail
- generated Swagger/OpenAPI at `/docs`
- `pulsehunter-ci` run creation, polling, exit codes, per-device summaries, and
  optional caller-supplied source-commit metadata stored with each run
- `pulsehunter-host-agent` registration, heartbeat, job-id idempotency, and
  bounded real host inventory, memory, disk, network, and battery checks

## Verification status

Verified on 2026-09-24:

- On a physical Windows laptop, the agent registered as `windows-host` with
  `simulated=false`, sent heartbeats over the LAN, and accepted an HTTP job from
  the desktop worker. Run `8f990ccc-c1c7-4ad2-9c63-4af627e19758` passed
  `host-health` on attempt 1. Real CPU, memory, storage, network, battery,
  uptime, and system results were persisted; memory and storage integrity
  checks passed. The dashboard rendered the saved result, and heartbeat-driven
  online/offline/reconnect behavior was observed.
- Locally, Python 3.14.5 passed Ruff, Ruff format (66 files), Mypy (41 source
  files), JavaScript syntax, and 49 pytest tests; the service-only test was
  skipped. A disposable Python 3.14.7 container passed all 50 tests against
  real PostgreSQL and Redis.
- Compose config, image build, and startup passed without deleting volumes.
  PostgreSQL, Redis, API, worker, Beat, and three simulators were healthy.
  Alembic reported no schema drift; repeated suite seeding succeeded.
- The Docker simulator E2E run passed healthy on attempt 1 and unreliable on
  attempt 2; slow timed out on attempt 3, so the aggregate failed as designed.
  The CI client returned exit 0 for healthy and exit 1 for slow. `/health`,
  Swagger/OpenAPI, the dashboard, and the saved physical run-detail page loaded.

GitHub Actions covers automated tests and Docker simulator flows; it does not
physically exercise the Windows laptop.

## Known issues and limitations

- Trusted-local-development security model: no users, agent auth, TLS, or RBAC.
- Agent URL registration creates an SSRF risk on an untrusted deployment.
- Agent execution idempotency is in memory and is lost on restart.
- No cancellation, priority queue, capability matching, artifact storage,
  streaming logs, metrics dashboards, or cloud deployment.
- CI tests the host-agent contract, not the physical laptop.
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

## Future work

Authentication, API-level capability-aware scheduling, and additional agent
integrations such as Raspberry Pi or microcontroller gateways are not yet
implemented.
