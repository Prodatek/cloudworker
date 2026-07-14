# Architecture

## Layering (Clean Architecture)

```
api/            Thin HTTP controllers (FastAPI routers). Translate HTTP <-> domain calls.
core/           Cross-cutting concerns: configuration, logging, middleware.
domain/         Pure business entities, rules, and Protocol interfaces. No FastAPI/SQLAlchemy/boto3 imports.
infrastructure/ Adapters to the outside world: Postgres (db/), AWS EC2/SSM/S3 (aws/).
services/       Orchestrates domain repositories + infrastructure adapters (WorkerManager,
                JobExecutor's caller JobProcessor); doesn't belong in api/ (not an HTTP
                concern), domain/ (it performs I/O), or infrastructure/ (it doesn't itself
                adapt to one external system). Each service does one thing: WorkerManager
                only knows about worker lifecycle, JobProcessor only orchestrates
                claim -> provision -> execute -> terminate, SsmJobExecutor only runs one
                command on one instance.
```

Dependencies point inward: `api`/`services` depend on `domain` and `infrastructure`; `domain`
depends on nothing. This keeps business rules (e.g. "a job queue entry can only be claimed once")
testable without a database, and swappable (e.g. moving from a Postgres-backed queue to SQS later
would only touch `infrastructure`, not `domain` or `api`). The same pattern let
`JobProcessor`/`WorkerManager`/`SsmJobExecutor`/`PlaywrightJobExecutor`/`S3ArtifactStore` be
tested entirely against in-memory fakes (`tests/unit/fakes.py`) without a database or AWS
credentials — they depend on
`JobRepository`/`WorkerRepository`/`WorkerProvisioner`/`JobExecutor`/`ArtifactStore` protocols,
never on SQLAlchemy or boto3 directly. `JobProcessor` also depends on a `RepositoryFactory`
protocol (not fixed repository instances) so each concurrently processed job gets its own DB
session, and on `dict[JobType, JobExecutor]` (not a single executor) so it can route each job
to the right one without knowing anything about shell vs. browser payload shapes itself.

## Request flow (current)

```
client -> PrometheusMiddleware -> RequestContextMiddleware -> FastAPI router -> endpoint
                                                                                  |
                                                                                  v
                                                                     infrastructure/database
                                                                          (Postgres, async)
```

## Components (end-state, per the original mission)

- **API** — FastAPI app; this repo's `backend/`.
- **Job Queue** — Postgres table + `SELECT ... FOR UPDATE SKIP LOCKED` claim query (Phase 2).
- **Worker Manager** *(shipped Phase 4)* — `app/services/worker_manager.py`: worker lifecycle only
  (provision a worker for a job, or terminate one). Launches EC2 instances from Phase 3's launch
  template, waits for SSM registration.
- **Job execution** *(shipped Phase 5)* — `app/services/job_processor.py`'s `JobProcessor` claims
  jobs and runs each as its own concurrent `asyncio` task (bounded by `max_concurrent_jobs`, each
  with its own DB session): provision → dispatch the shell command over SSM
  (`app/infrastructure/aws/ssm_job_executor.py`, writing full stdout/stderr to S3) → mark
  succeeded/failed → terminate the worker. Runs as its own process (`app/worker_entrypoint.py`,
  the `worker` docker-compose service), decoupled from the API so EC2 provisioning/execution
  latency (can be minutes) never blocks a request or serializes other jobs.
- **Browser jobs** *(shipped Phase 6)* — `app/infrastructure/aws/playwright_job_executor.py`'s
  `PlaywrightJobExecutor` runs `job_type: browser` the same way `SsmJobExecutor` runs shell jobs
  (same `JobExecutor` protocol, same `JobProcessor` orchestration), by dispatching the job's
  script (base64-embedded in the SSM command) to a runner harness baked into the worker AMI
  (`infra/packer/`) via SSM. The two executors share dispatch/poll mechanics
  (`app/infrastructure/aws/ssm_command_dispatch.py`) since that part is identical — only what
  gets sent and how the result is built differs.
- **Artifact Service** *(shipped Phase 6)* — `app/infrastructure/aws/s3_artifact_store.py`'s
  `S3ArtifactStore` lists a job's objects across the logs/artifacts buckets and generates
  presigned GET URLs, exposed via `GET /api/v1/jobs/{id}/artifacts`. Presigned URL generation is
  pure local signing — no AWS call — which made it possible to get real test coverage of this
  piece without moto or credentials, unlike almost everything else touching AWS in this project.
- **Authentication** *(API keys shipped Phase 2, JWT login shipped Phase 7)* —
  `get_current_user` (`app/api/v1/deps.py`) accepts either an API key or a JWT through the same
  `Authorization: Bearer` header, dispatched by the `cw_live_` prefix API keys carry. API clients
  use keys (`POST /api/v1/auth/register`, managed via `GET/POST /api/v1/api-keys`,
  `POST /api/v1/api-keys/{id}/revoke`); the dashboard uses password login
  (`POST /api/v1/auth/login`) issuing a JWT — both converge on the same `User`, so every endpoint
  is authenticated identically regardless of which credential a caller used.
- **Dashboard** *(shipped Phase 7)* — `frontend/`: React + TypeScript (Vite), typed against the
  backend's OpenAPI schema (`openapi-typescript` + `openapi-fetch`, `frontend/src/api/`) so a
  contract change breaks the frontend build instead of drifting silently. Login/register, job
  submission (shell + browser), status polling, and artifact download via the presigned URLs
  Phase 6's Artifact Service produces.
- **Guaranteed worker cleanup** *(shipped Phase 8)* — `app/services/worker_reaper.py`'s
  `WorkerReaper` runs alongside `JobProcessor` in the same worker process, polling for workers
  stuck in a non-terminal status past `WORKER_STALE_AFTER_SECONDS` (a crash mid-provisioning, or
  an executor that never returned) and force-terminating + failing them — extending the mission's
  "automatically destroys workers" guarantee to crash/hang recovery, not just the happy path.

## 8-Phase Roadmap

1. **Foundations** *(shipped)* — FastAPI skeleton, Postgres wiring, Docker Compose, CI, health/metrics endpoints, OpenAPI docs.
2. **Auth + Job Domain** *(shipped)* — API key auth, `users`/`jobs` tables (Alembic), Postgres-backed job queue, CRUD API.
3. **AWS Infra (Terraform)** *(shipped as IaC — not yet applied to a real AWS account)* — VPC, IAM/SSM role, S3 buckets, EC2 launch template referencing a prebuilt AMI.
4. **Worker Manager** *(shipped)* — boto3-driven EC2 provisioning/termination, worker lifecycle state machine, queue consumer.
5. **Shell Execution** *(shipped)* — SSM SendCommand for shell jobs, full output to S3 (SSM-native), concurrent job processing, cancellation/timeouts.
6. **Browser Automation** *(shipped)* — Playwright jobs (one universal AMI via Packer), screenshot/video capture, Artifact Service, presigned URL downloads.
7. **Dashboard** *(shipped)* — React + TypeScript UI: login, submit jobs, poll status, browse artifacts, manage API keys.
8. **Hardening & Beta** *(shipped)* — guaranteed cleanup (`WorkerReaper`), richer metrics, auth
   rate limiting, security review, CD pipeline, deployment guide, E2E test scaffold.

## Security model

- **Arbitrary code execution is the product, not an oversight.** A CloudWorker job's payload is a
  shell command or a Playwright script that runs with no sandboxing beyond what the worker
  instance itself provides — that's the mission (`POST /api/v1/jobs` exists specifically to run
  arbitrary shell/browser automation). The controls that make this safe are: (1) only an
  authenticated user (API key or JWT) can submit a job at all; (2) each job gets its own
  ephemeral EC2 worker, provisioned fresh and terminated immediately after
  (`app/services/worker_manager.py`, backstopped by `app/services/worker_reaper.py` for
  crash/hang cases — Phase 8), so there's no persistent multi-tenant execution host to escape
  into; (3) the worker's IAM role (`infra/terraform/modules/iam`) grants only
  `AmazonSSMManagedInstanceCore` (required for the SSM agent to function) plus scoped
  `s3:GetObject`/`s3:PutObject`/`s3:ListBucket` on exactly its own logs/artifacts buckets — no
  wildcard resources, no access to any other AWS service; (4) workers launch into a
  private-only subnet reachable solely via VPC interface endpoints for SSM/S3 (`infra/terraform/
  modules/networking`), so a job can't reach the rest of the account's network. A determined
  authenticated user can still use their own job to attack *their own worker* — that's expected
  and unavoidable given the feature; what these controls prevent is a job affecting anything
  outside its own single-use, network-isolated instance.
- **Dual credentials converge on one identity.** API keys and JWTs both resolve to the same
  `User` through `get_current_user` (`app/api/v1/deps.py`) — there's exactly one authorization
  model, not two to keep in sync.
- **Auth endpoints are rate-limited** (`app/core/rate_limit.py`, Phase 8) per client IP —
  in-memory/single-process, a deliberate scope limit (see the module's docstring), not a
  production-scale guarantee.
- **JWTs are decoded with an explicit single algorithm** (`decode_access_token`,
  `app/infrastructure/security.py`) — `algorithms=[settings.jwt_algorithm]`, never inferred from
  the token itself, so a forged token can't downgrade to `alg: none` or swap algorithms.
- **Request logging never includes bodies, headers, or tokens** (`RequestContextMiddleware`,
  `app/core/middleware.py`) — only method, path, status, and duration.

## Why Postgres for the job queue (not SQS/Redis)

A `jobs` table with `SELECT ... FOR UPDATE SKIP LOCKED` gives at-least-once, safe-for-concurrent-
workers dequeuing without adding a second stateful service. Given Postgres is already a hard
dependency (job/user/artifact metadata all live there), this avoids running Redis or requiring
AWS/LocalStack for local development. Trade-off: higher operational ceiling (SQS scales queue
throughput independently of the database) is given up in exchange for operational simplicity —
acceptable for a beta-stage single-tenant-per-deployment product; revisit if queue depth or
polling overhead becomes a bottleneck.
