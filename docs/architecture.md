# Architecture

## Layering (Clean Architecture)

```
api/            Thin HTTP controllers (FastAPI routers). Translate HTTP <-> domain calls.
core/           Cross-cutting concerns: configuration, logging, middleware.
domain/         Pure business entities and rules. No FastAPI/SQLAlchemy/boto3 imports.
infrastructure/ Adapters to the outside world: Postgres, S3, SSM, EC2.
```

Dependencies point inward: `api` depends on `domain` and `infrastructure`; `domain` depends on
nothing. This keeps business rules (e.g. "a job queue entry can only be claimed once") testable
without a database, and swappable (e.g. moving from a Postgres-backed queue to SQS later would
only touch `infrastructure`, not `domain` or `api`).

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
- **Worker Manager** — provisions/terminates EC2 instances, dispatches commands over SSM (Phase 4).
- **Artifact Service** — uploads/downloads logs, screenshots, videos to/from S3 (Phase 6).
- **Authentication** — API keys or JWT for programmatic access (Phase 2).
- **Dashboard** — React + TypeScript frontend (Phase 7).

## 8-Phase Roadmap

1. **Foundations** *(shipped)* — FastAPI skeleton, Postgres wiring, Docker Compose, CI, health/metrics endpoints, OpenAPI docs.
2. **Auth + Job Domain** *(shipped)* — API key auth, `users`/`jobs` tables (Alembic), Postgres-backed job queue, CRUD API.
3. **AWS Infra (Terraform)** — VPC, IAM/SSM role, S3 buckets, EC2 launch template referencing a prebuilt AMI.
4. **Worker Manager** — boto3-driven EC2 provisioning/termination, worker lifecycle state machine, queue consumer.
5. **Shell Execution** — SSM RunCommand for shell jobs, log streaming to S3 + DB, cancellation/timeouts.
6. **Browser Automation** — Playwright jobs, screenshot/video capture, Artifact Service, presigned URL downloads.
7. **Dashboard** — React + TypeScript UI: submit jobs, tail logs live, browse artifacts.
8. **Hardening & Beta** — metrics dashboards, guaranteed cleanup (idle/orphan reaper), CD pipeline, security review, install docs.

## Why Postgres for the job queue (not SQS/Redis)

A `jobs` table with `SELECT ... FOR UPDATE SKIP LOCKED` gives at-least-once, safe-for-concurrent-
workers dequeuing without adding a second stateful service. Given Postgres is already a hard
dependency (job/user/artifact metadata all live there), this avoids running Redis or requiring
AWS/LocalStack for local development. Trade-off: higher operational ceiling (SQS scales queue
throughput independently of the database) is given up in exchange for operational simplicity —
acceptable for a beta-stage single-tenant-per-deployment product; revisit if queue depth or
polling overhead becomes a bottleneck.
