# Project Status

## Current state

The end-to-end local MVP is implemented. PulseHunter can register three standalone
simulated devices, reserve them for a run, dispatch concurrent jobs through
Redis/Celery, persist results in PostgreSQL, retry transient failures, enforce
timeouts, aggregate the run, release devices, and expose the result in REST and
HTML views. An API-based CLI can create a run and gate a CI job on its final
status. A separate Windows process can perform predefined checks on its host.

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
- dashboard fleet metrics, run creation, recent runs, and job detail
- generated Swagger/OpenAPI at `/docs`
- `pulsehunter-ci` run creation, polling, exit codes, per-device summaries, and
  optional caller-supplied source-commit metadata stored with each run
- `pulsehunter-host-agent` registration, heartbeat, job-id idempotency, and
  bounded real host inventory, memory, disk, network, and battery checks

## Verification status

Verified locally on 2026-09-24:

- Python 3.14.5 ran the host suite and Python 3.14.7 ran the Docker suite.
- `ruff check .` passed and `ruff format --check .` confirmed all 66 files were
  formatted.
- Mypy passed across all 41 source files.
- The host test run passed 46 tests and skipped only the opt-in service test.
- The full Compose-backed test run enabled that service test and passed all 47
  tests against PostgreSQL and Redis.
- `docker compose config --quiet` passed. The Python 3.14 image rebuilt, the
  complete stack was recreated, PostgreSQL, Redis, the API, and all three
  agents reported healthy, and the worker and Beat processes remained running.
- Alembic applied the additive run-source migration and reported no new
  upgrade operations from the model metadata.
- The automated mixed-behavior run completed three concurrent jobs: healthy
  passed on attempt 1, unreliable passed on attempt 2, slow timed out on attempt
  3, the aggregate run failed as designed, and all devices returned online.
- The packaged CI client returned exit 0 for the healthy agent and exit 1 for
  the slow agent's bounded timeout; both printed run and device summaries, and
  source metadata was persisted and returned by the API.
- The Windows host-check collector completed bounded memory and temporary-file
  integrity tests on the development desktop. Unit tests cover the host-agent
  HTTP contract, idempotency, suite restriction, cleanup, and timeout budget.
  The physical laptop has **not** yet been tested end to end.

The published CI-client revision passed both GitHub Actions jobs. This Windows
host-agent revision is uncommitted and has not run remotely.

## Known issues and limitations

- Trusted-local-development security model: no users, agent auth, TLS, or RBAC.
- Agent URL registration creates an SSRF risk on an untrusted deployment.
- Agent execution idempotency is in memory and is lost on restart.
- No cancellation, priority queue, capability matching, artifact storage,
  streaming logs, metrics dashboards, or cloud deployment.
- Physical-laptop registration, LAN reachability, and job execution await
  manual verification; CI tests the agent contract, not that laptop.
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

Run the documented physical-laptop E2E check and inspect its persisted result
before claiming laptop validation. Authentication and capability-aware
scheduling remain separate future milestones.
