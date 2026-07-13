# Phase 1 Report: Foundations

## What was built

- A FastAPI backend (`backend/app`) laid out in four layers — `api` (routers), `core`
  (config + logging + middleware), `domain` (empty stub, populated Phase 2), `infrastructure`
  (Postgres engine/session).
- `GET /healthz` (liveness — always 200 if the process is up) and `GET /readyz` (readiness —
  actually round-trips a query to Postgres, returns 503 if it can't).
- `GET /metrics` — Prometheus request-count and latency histograms via a middleware, so every
  future endpoint is instrumented automatically.
- JSON structured logging (stdlib `logging` + a custom formatter) with a per-request id attached
  via middleware and echoed back as `X-Request-Id`.
- Config via `pydantic-settings`, sourced from environment variables / `.env` — nothing
  hard-coded.
- OpenAPI docs at `/docs`/`/redoc`/`/openapi.json`, generated automatically by FastAPI.
- `docker-compose.yml`: Postgres 16 + the API, with a health-checked dependency so the API
  container waits for Postgres to actually accept connections.
- Terraform scaffolding (`infra/terraform/environments/dev`): AWS provider + variables only, no
  resources yet, with a `modules/README.md` documenting what Phase 3 will add.
- GitHub Actions CI (`.github/workflows/ci.yml`): `ruff check`/`ruff format --check`, `mypy`,
  `pytest` (against a real Postgres service container), and `terraform fmt`/`validate` — four
  independent jobs, all required.
- Docs: this report, `docs/architecture.md` (layering + full 8-phase roadmap), and
  `docs/api-examples.md` (curl examples for every endpoint).
- A local git repository at `cloudworker/`, independent of the outer `GOAL` workspace repo.

## Why it was designed this way

- **Health/readiness split** maps directly onto how ALB target groups and ECS/K8s health checks
  are configured in later phases — liveness never depends on Postgres (so a DB blip doesn't kill
  the process), readiness does (so a DB blip takes the instance out of rotation).
- **Metrics from day one** rather than retrofitted later — the middleware pattern means every
  endpoint added in Phases 2–8 is automatically counted/timed with zero extra code at the call
  site.
- **No Alembic yet** — there are no domain tables in Phase 1 (only a `SELECT 1` check), so adding
  migration tooling now would mean an empty scaffold with nothing to migrate. It's explicitly
  deferred to Phase 2, not silently dropped (see Technical Debt below).
- **Terraform is provider-only** — real resources (VPC, IAM/SSM, S3, EC2) need actual design
  decisions (Phase 3) rather than placeholder boilerplate; committing scaffolding now still lets
  CI enforce `fmt`/`validate` on every change from day one, catching syntax drift immediately.
- **Plain `pip` + `requirements.txt`** (user's choice) keeps the dependency surface obvious and
  avoids introducing a second tool (Poetry/uv) the team may not already use.
- **Postgres-backed job queue** (user's choice, implemented Phase 2) shaped this phase indirectly:
  the async SQLAlchemy engine wired up now is the same one the `SELECT ... FOR UPDATE SKIP LOCKED`
  claim query will run through — no rework needed when Phase 2 adds the `jobs` table.

## Trade-offs

- **No Alembic in Phase 1** means the very first schema migration (Phase 2) also has to introduce
  the migration tooling itself — slightly more work in one phase instead of spread across two, in
  exchange for not carrying empty migration scaffolding now.
- **Postgres for the queue, not SQS/Redis**: simpler local dev and fewer moving parts, at the cost
  of a lower theoretical throughput ceiling than a dedicated queue service. Revisit if/when queue
  depth or polling overhead becomes a real bottleneck — documented in `docs/architecture.md`.
- **Custom JSON log formatter instead of `structlog`**: one fewer dependency, but less ergonomic
  contextual binding (e.g. no `logger.bind(job_id=...)`) — acceptable now since there's no job
  context to bind yet; worth revisiting once Worker Manager (Phase 4) needs to correlate logs by
  job/worker id.
- **`/readyz` reports `degraded`/503 for *any* DB failure**, not distinguishing "can't connect" vs
  "connected but query failed" vs "pool exhausted." Fine for a single dependency; will need
  richer status if more downstream checks (S3, SSM) are added to readiness later.

## Tests run

```
ruff check backend/app backend/tests        -> All checks passed!
ruff format --check backend/app backend/tests -> 22 files already formatted
mypy backend/app                              -> Success: no issues found in 15 source files
pytest backend/tests/unit                     -> 6 passed
terraform fmt -check -recursive               -> clean
terraform init -backend=false && validate     -> Success! The configuration is valid.
```

**Integration tests** (`backend/tests/integration`, requiring a real reachable Postgres) were
written and exercised, but this development sandbox has no Docker daemon available, so they could
only be run against whatever was listening on `localhost:5432` — which was not a working
Postgres instance. The result was still informative: `/readyz` correctly returned `503
{"status": "degraded", "database": "unreachable"}` instead of crashing or hanging indefinitely,
confirming the failure path is handled safely. **Action for the user**: run `docker compose up -d
db` (or the full stack) and `pytest` from `backend/` to see the success-path integration test
(`test_readyz_confirms_real_database_connectivity`) go green end-to-end — this hasn't been
verified in this environment and should be checked before treating Phase 1 as fully done.

## Technical debt

1. No Alembic / migrations yet — first real migration lands with the Phase 2 `users`/`jobs`
   tables.
2. No authentication on any endpoint yet (all Phase 1 endpoints are unauthenticated ops
   endpoints, which is fine for `/healthz`/`/readyz`/`/metrics` but must not be the pattern for
   business endpoints starting Phase 2).
3. `/readyz` is binary (ok/degraded) — will likely need per-dependency detail once there's more
   than one thing to check.
4. Integration test success path is unverified in this sandbox (no Docker) — needs confirmation
   in an environment with Docker before considering Phase 1 fully proven end-to-end.
5. No GitHub remote configured yet (local git only, by user's choice) — CI defined in
   `.github/workflows/ci.yml` won't actually run until this repo is pushed to GitHub.

## Proposed Phase 2: Authentication + Job Domain + Queue

Scope proposal (not yet implemented):
- `users` and `api_keys` tables + Alembic migration tooling (introduced here, per the debt above).
- API key authentication (hashed keys, `Authorization: Bearer <key>` header) protecting all
  `/api/v1/*` business endpoints; `/healthz`/`/readyz`/`/metrics` stay open for infra probes.
- `jobs` table: id, type (`shell`/`browser`, though only `shell` is executed until Phase 5/6),
  status, payload, timestamps, owner.
- Postgres-backed queue: a `claim_next_job()` query using `SELECT ... FOR UPDATE SKIP LOCKED`,
  covered by a concurrency test (multiple simulated claimers, no job claimed twice).
- CRUD API: `POST /api/v1/jobs` (enqueue), `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs`, `POST
  /api/v1/jobs/{id}/cancel`.
- Unit tests (domain logic, queue claim semantics) + integration tests (real Postgres, real HTTP
  round-trip) + updated `docs/api-examples.md`.

Will present this as a full plan (files, schema, endpoint contracts) for approval before writing
any Phase 2 code, per the project's operating rules.
