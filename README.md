# CloudWorker

CloudWorker provisions ephemeral Linux workers on AWS, executes shell scripts and Playwright
browser-automation jobs on them via SSM (no SSH), streams logs, stores artifacts in S3, and
automatically tears the workers down when the job finishes.

## Status

**Phase 7 of 8 (React + TypeScript Dashboard)** — see
[`docs/architecture.md`](docs/architecture.md) for the full roadmap, and `docs/phase-1.md` through
`docs/phase-7.md` for what shipped in each phase. Phase 3's AWS infra is IaC only (not yet applied
to a real account) and Phase 6's worker AMI (`infra/packer/`) hasn't been built, so Phases 4–6's
worker provisioning/execution are only proven via `moto`-mocked and hand-mocked tests in this
environment. Phase 7 is the first phase with no AWS dependency at all — see
[`docs/phase-7.md`](docs/phase-7.md) for what was (and, for one local-environment-specific
Vitest quirk, wasn't quite) verified directly.

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
- Register: `POST /api/v1/auth/register` · Login: `POST /api/v1/auth/login`
- API keys: `GET/POST /api/v1/api-keys`, `POST /api/v1/api-keys/{id}/revoke`
- Jobs: `POST/GET /api/v1/jobs`, `GET/POST /api/v1/jobs/{id}[/cancel]`, `GET /api/v1/jobs/{id}/artifacts` (require an API key or a JWT from login)

To also run the Worker Manager locally: `docker compose up worker` (or it starts with the rest
of the stack via `docker compose up`). It's inert without `LAUNCH_TEMPLATE_ID`/`WORKER_SUBNET_IDS`
set to real values from an applied Phase 3, and browser jobs additionally need a worker AMI built
from `infra/packer/` (`backend/.env.example` documents all the variables).

Dashboard: `docker compose up frontend` (or `cd frontend && npm install && npm run dev`), then
open <http://localhost:5173>. See [`frontend/README.md`](frontend/README.md).

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
backend/                       FastAPI application, tests, requirements
frontend/                      React + TypeScript dashboard (Vite)
infra/terraform/bootstrap/     One-time remote state backend (S3 bucket + DynamoDB lock table)
infra/terraform/modules/       networking, iam, storage, compute
infra/terraform/environments/  Thin per-environment composition of the modules above
infra/packer/                  Worker AMI build (Playwright + runner harness on top of AL2023)
docs/                          Architecture notes, phase reports, example API calls
.github/workflows/             CI: lint, test, terraform validate
docker-compose.yml             Local dev: Postgres + API + worker + frontend
```

## Roadmap

1. **Foundations** *(shipped)* — FastAPI skeleton, Postgres wiring, Docker Compose, CI, health/metrics, OpenAPI docs
2. **Authentication + Job Domain + Queue** *(shipped)* — API key auth, `users`/`jobs` tables, Postgres-backed job queue, CRUD API
3. **AWS Infrastructure via Terraform** *(shipped, IaC only)* — VPC (private-only, SSM/S3 VPC endpoints), IAM/SSM role, S3 buckets, EC2 launch template
4. **Worker Manager** *(shipped)* — provisions/terminates EC2 workers, lifecycle state machine, `moto`-tested
5. **Shell Job Execution over SSM** *(shipped)* — SSM SendCommand dispatch, full output to S3, concurrent job processing, payload validation
6. **Playwright Browser Automation + Artifact Service** *(shipped)* — browser jobs via a shared JobExecutor protocol, one universal AMI (Packer), presigned-URL artifact retrieval
7. **React + TypeScript Dashboard** *(this phase)* — login/register, JWT + API-key auth on the same endpoints, job submission/status/artifacts, API key management
8. Hardening: metrics dashboards, auto-cleanup guarantees, deploy pipeline, security review, beta packaging
