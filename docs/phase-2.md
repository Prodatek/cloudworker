# Phase 2 Report: Authentication + Job Domain + Postgres Queue

## What was built

- **Domain layer** (`backend/app/domain/entities.py`, `repositories.py`): pure `User`, `ApiKey`,
  `Job` dataclasses, `JobStatus`/`JobType` enums, and `Protocol` repository interfaces — no
  SQLAlchemy or FastAPI imports, so business rules (e.g. "a job is only cancellable while queued")
  are independent of how they're persisted or exposed.
- **Schema**: `users`, `api_keys`, `jobs` tables via a new Alembic migration
  (`0001_create_users_api_keys_jobs.py`), configured for **async** migrations against the existing
  `asyncpg` engine — no second DB driver needed.
- **Auth**: `POST /api/v1/auth/register` (email + password → user + one-time API key). API keys
  are `cw_live_<random>`, stored as a `sha256` hash (fast lookup, appropriate for already-
  high-entropy tokens); passwords are hashed with `bcrypt`. `get_current_user`
  (`backend/app/api/v1/deps.py`) enforces `Authorization: Bearer <key>` on every job endpoint;
  `/healthz`/`/readyz`/`/metrics` stay open.
- **Jobs API**: `POST /api/v1/jobs`, `GET /api/v1/jobs` (paginated), `GET /api/v1/jobs/{id}`,
  `POST /api/v1/jobs/{id}/cancel` — all scoped to the calling user; another user's job id returns
  `404` (not `403`, to avoid confirming it exists), cancelling a non-queued job returns `409`.
- **Postgres-backed queue**: `JobRepository.claim_next_job()` runs
  `SELECT ... FOR UPDATE SKIP LOCKED` to atomically hand the oldest queued job to exactly one
  caller — this is what the Worker Manager (Phase 4) will call in a loop. Nothing consumes it yet;
  Phase 2 proves it's correct in isolation.
- **Request-scoped unit of work**: `infrastructure/database.py`'s `get_db_session` now
  commits on success / rolls back on exception, so every request's writes are atomic.
- Unit tests for password/API-key hashing and Pydantic schema validation; integration tests for
  the full register → create → list → get → cancel flow, auth failure cases (401/404/409), and a
  concurrency test that fires more concurrent claimers than there are queued jobs and asserts no
  job is ever claimed twice.
- CI: added an `alembic upgrade head` step before `pytest` in the `test` job.
- Docs: `docs/api-examples.md` gained register/job examples; `docs/architecture.md` and
  `README.md` roadmaps updated to mark Phases 1–2 shipped.

## Why it was designed this way

- **Protocol-based repositories** keep the `api/` layer's imports pointed at `domain/`, not
  `infrastructure/db/`, so swapping the queue backend later (per `docs/architecture.md`'s
  documented trade-off) touches one layer, not every endpoint.
- **404, not 403, for other users' jobs** avoids leaking which job ids exist to callers who don't
  own them — standard practice for multi-tenant resource access.
- **`claim_next_job()` commits its own transaction** (unlike the other repository methods, which
  rely on the request-scoped commit) because it's designed to be called directly by a worker loop
  outside any HTTP request — Phase 4 will call it in a `while True` polling loop, each iteration
  its own short transaction so the row lock is released the instant a job is claimed.
- **Varchar + Python enum instead of Postgres native `ENUM`** for `job_type`/`status` — as
  documented in the Phase 1 architecture notes, native Postgres enums require `ALTER TYPE` to add
  values, which is more migration friction than adding a Python enum member; validated instead at
  the Pydantic boundary.
- **API keys hashed with `sha256`, passwords with `bcrypt`** — different threat models: passwords
  are (relatively) low-entropy and need a slow, salted hash to resist offline brute-forcing;
  API keys are generated with `secrets.token_urlsafe(32)` (256 bits of randomness) and don't need
  a slow hash, so a fast one keeps auth-check latency low on every request.

## Trade-offs

- **Open self-serve registration** (user's choice) means anyone who finds the endpoint can create
  an account — acceptable pre-launch, but needs rate-limiting/CAPTCHA/email verification before
  this is exposed publicly. Tracked below.
- **API keys only, no password login/JWT** (user's choice) keeps this phase focused, but means the
  `hashed_password` column has no consumer yet — it exists purely for Phase 7's future login flow.
  If Phase 7 ends up not needing password login (e.g. SSO-only), this column becomes dead weight.
- **`claim_next_job()` is unauthenticated/unexposed over HTTP by design** — correct for Phase 2's
  scope, but means the only proof it works is the direct-repository concurrency test; the first
  real end-to-end proof arrives with the Phase 4 Worker Manager actually calling it.
- **No pagination cursor, just limit/offset** on `GET /api/v1/jobs` — fine at beta scale; will
  degrade if a customer accumulates a very large job history (offset pagination gets slower with
  depth). Cheap to swap for keyset pagination later if it becomes a problem.

## Tests run

```
ruff check backend/app backend/tests          -> All checks passed!
ruff format --check backend/app backend/tests -> clean
mypy backend/app                               -> Success: no issues found in 29 source files
pytest backend/tests/unit                      -> 15 passed
```

**Integration tests and the Alembic migration were not run against a real Postgres in this
session.** This sandbox has no Docker daemon (same limitation as Phase 1). A real local
PostgreSQL 18 service was discovered running on this machine, and creating a `cloudworker`
role/database in it would have let these be verified for real — **the user was asked and declined
that option**, so the integration suite (`test_auth_integration.py`, `test_jobs_integration.py`,
`test_job_queue_claim_concurrency.py`) and the migration remain unverified against a live database
in this environment.

**Action for the user, before treating Phase 2 as fully proven**:
```bash
docker compose up -d db
cd backend
alembic upgrade head
pytest
```
All of `test_auth_integration.py`, `test_jobs_integration.py`, `test_readyz_integration.py`, and
`test_job_queue_claim_concurrency.py` should pass. If anything fails, it needs to be fixed before
Phase 3 builds on top of this schema.

## Technical debt

1. **Integration tests and migration unverified in this sandbox** (see above) — highest-priority
   item to close before continuing.
2. No rate-limiting/CAPTCHA/email verification on `POST /api/v1/auth/register` — fine for a closed
   beta, not for public launch.
3. `hashed_password` column has no consumer yet (API-key-only auth this phase) — either gets used
   by Phase 7's login flow or should be reconsidered if that flow changes shape.
4. No API key revocation endpoint yet — `revoked_at` exists on the model/schema but nothing sets
   it. Needed before Phase 7 (a user must be able to rotate/revoke a leaked key from the
   dashboard).
5. Offset-based pagination on job listing — acceptable now, revisit if job history grows large.
6. `claim_next_job()` has no test coverage from a real worker process yet — only proven via direct
   repository calls until Phase 4 builds the Worker Manager around it.

## Proposed Phase 3: AWS Infrastructure via Terraform

Scope proposal (not yet implemented):
- `networking` module: VPC, public/private subnets, security groups (workers get no inbound
  access at all — SSM is outbound-only, which is the whole point of not needing SSH).
- `iam` module: instance role/profile granting `AmazonSSMManagedInstanceCore` plus scoped S3
  read/write to the artifacts bucket — least privilege, no wildcard resource ARNs.
- `storage` module: S3 buckets for logs/artifacts with lifecycle rules (e.g. expire after N days)
  and default encryption.
- `compute` module: an EC2 launch template referencing a prebuilt AMI (Amazon Linux 2023 + SSM
  agent preinstalled; Packer build for the AMI itself is a Phase 3 or Phase 6 decision depending
  on whether Playwright needs to be baked in yet).
- Remote state: bootstrap an S3 bucket + DynamoDB lock table (this is the point where the
  commented-out `backend "s3" {}` block in `providers.tf` gets uncommented and filled in).
- This phase needs real AWS credentials/account access to `terraform apply` against — will ask
  before running `apply` (vs. just `plan`) against any real account, per the project's standing
  rule to confirm before actions with real infrastructure blast radius.

Will present this as a full plan for approval before writing any Phase 3 code, same as Phases 1–2.
