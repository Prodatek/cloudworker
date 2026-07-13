# CloudWorker

CloudWorker provisions ephemeral Linux workers on AWS, executes shell scripts and Playwright
browser-automation jobs on them via SSM (no SSH), streams logs, stores artifacts in S3, and
automatically tears the workers down when the job finishes.

## Status

**Phase 2 of 8 (Authentication + Job Domain + Queue)** — see
[`docs/architecture.md`](docs/architecture.md) for the full roadmap,
[`docs/phase-1.md`](docs/phase-1.md) and [`docs/phase-2.md`](docs/phase-2.md) for what shipped in
each phase.

## Quickstart

```bash
docker compose up -d db
cd backend && alembic upgrade head && cd ..
docker compose up --build
```

This starts Postgres and the API on `http://localhost:8000`. The migration only needs to be run
once (or after pulling new migrations) — it creates the `users`/`api_keys`/`jobs` tables.

- Swagger UI: <http://localhost:8000/docs>
- OpenAPI schema: <http://localhost:8000/openapi.json>
- Liveness: `GET /healthz`
- Readiness (checks Postgres): `GET /readyz`
- Prometheus metrics: `GET /metrics`
- Register: `POST /api/v1/auth/register`
- Jobs: `POST/GET /api/v1/jobs`, `GET/POST /api/v1/jobs/{id}[/cancel]` (require an API key)

See [`docs/api-examples.md`](docs/api-examples.md) for example `curl` calls.

## Running tests locally (without Docker)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt

# Unit tests only (no Postgres needed):
pytest tests/unit

# Integration tests too (requires Postgres reachable, e.g. `docker compose up db`, with migrations applied):
set DATABASE_URL=postgresql+asyncpg://cloudworker:cloudworker@localhost:5432/cloudworker
alembic upgrade head
pytest
```

## Linting / type-checking

```bash
ruff check backend/app backend/tests
ruff format --check backend/app backend/tests
mypy backend/app
```

## Repository layout

```
backend/            FastAPI application, tests, requirements
infra/terraform/    AWS infrastructure as code (scaffolding only until Phase 3)
docs/               Architecture notes, phase reports, example API calls
.github/workflows/  CI: lint, test, terraform validate
docker-compose.yml  Local dev: Postgres + API
```

## Roadmap

1. **Foundations** *(shipped)* — FastAPI skeleton, Postgres wiring, Docker Compose, CI, health/metrics, OpenAPI docs
2. **Authentication + Job Domain + Queue** *(this phase)* — API key auth, `users`/`jobs` tables, Postgres-backed job queue, CRUD API
3. AWS infrastructure via Terraform (VPC, IAM/SSM, S3, EC2 launch template)
4. Worker Manager (provision/terminate EC2 workers, lifecycle state machine)
5. Shell job execution over SSM + log streaming to S3
6. Playwright browser-automation jobs + Artifact Service
7. React + TypeScript dashboard
8. Hardening: metrics dashboards, auto-cleanup guarantees, deploy pipeline, security review, beta packaging
