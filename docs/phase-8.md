# Phase 8 Report: Hardening & Beta

This is the final phase of the original 8-phase roadmap. Rather than new user-facing features, it
closes out tech debt every prior phase's report flagged and gets the project into a shape a
customer could actually adopt.

## What was built

- **Guaranteed worker cleanup** (`app/services/worker_reaper.py`). Phases 4–6 only terminated a
  worker on the happy path (job completes) or explicit cancellation — nothing recovered a worker
  stuck mid-provisioning after a crash, or a job that hung past its timeout without the executor
  ever returning. `WorkerRepository` gained `list_stale(older_than_seconds)`
  (`app/domain/repositories.py`, `app/infrastructure/db/worker_repository.py`); `WorkerReaper.
  reap_once()` finds workers in a non-terminal status whose `updated_at` hasn't moved in over
  `WORKER_STALE_AFTER_SECONDS`, terminates their instance via the same `WorkerProvisioner` other
  services already use, marks the worker `failed`, and fails the associated job if it isn't
  already terminal. `worker_entrypoint.py` runs `WorkerReaper.run_forever()` concurrently with
  `JobProcessor.run_forever()` via `asyncio.gather` — one process, no new docker-compose service,
  same reasoning Phase 4 used for keeping the worker a single deployable unit.
- **Richer metrics** (`app/infrastructure/metrics.py`): `cloudworker_jobs_total{job_type,status}`
  (incremented in `JobProcessor`, the cancel endpoint, and `WorkerReaper` — wherever a job
  actually reaches a terminal state), `cloudworker_worker_provisioning_seconds` (observed around
  `WorkerManager.provision_worker()`), `cloudworker_job_execution_seconds{job_type}` (observed
  around each executor call), `cloudworker_workers_reaped_total`. `docs/observability.md`
  documents all of them plus example PromQL queries.
- **Auth rate limiting** (`app/core/rate_limit.py`): an in-memory fixed-window limiter applied to
  `POST /api/v1/auth/register` and `POST /api/v1/auth/login`, keyed by client IP, configurable via
  `AUTH_RATE_LIMIT_MAX_ATTEMPTS`/`AUTH_RATE_LIMIT_WINDOW_SECONDS`. Closes the "no rate limiting at
  all" gap flagged as debt since Phase 2.
- **Security self-review**, findings fixed inline (see below).
- **CI/CD deploy pipeline** (`.github/workflows/deploy.yml`, authored/YAML-validated, not
  executed — no GitHub remote exists yet, same status as Terraform/Packer): builds and pushes
  `backend`/`frontend` images to GHCR on a version tag push, plus a manual-dispatch job for
  `terraform plan`/`apply` gated behind AWS credentials that don't exist in this repo yet.
- **`docs/deployment-guide.md`**: end-to-end instructions for standing this up in a real AWS
  account — bootstrap → apply Terraform → (optionally) build the Packer AMI → migrate → run the
  containers. Explicitly scopes out prescribing a specific API/worker hosting platform (ECS vs.
  EC2 vs. App Runner etc.) as a customer decision, not something this repo should own.
- **Playwright E2E scaffold** (`frontend/e2e/`, authored/spec-verified via `playwright test
  --list`, not executed — needs a running backend + Postgres this sandbox doesn't have): a smoke
  spec covering register → auto-login → create a shell job → see it listed, plus a logout/login
  persistence check.

## Why it was designed this way

- **The reaper reuses `WorkerProvisioner`/`WorkerRepository`, not new abstractions** — it's the
  same lifecycle machinery `WorkerManager` already uses, just triggered by "stuck too long"
  instead of "job finished." Two services calling the same protocols beats a wider interface with
  optional behavior.
- **Metrics are incremented inline, not via a decorator/middleware layer** — `JOBS_TOTAL` in
  particular only fires when `fail()`/`complete()`/`cancel()` actually returns a row (not `None`),
  so a race where two paths both try to terminally-transition the same job never double-counts.
- **Rate limiting is deliberately simple (in-memory, single-process)** rather than reaching for
  Redis — this is a beta closing an obvious gap (zero rate limiting), not a claim of
  production-scale correctness under multiple API replicas. Documented explicitly as a scope
  limit, not glossed over.
- **The deployment guide stops at "here are your images and your worker-fleet infrastructure"**
  rather than prescribing ECS/Fargate — building a specific hosting module would be new
  infrastructure scope disguised as hardening, and different customers will have very different
  existing hosting conventions to fit into.

## Security self-review findings

| Area | Finding | Resolution |
| --- | --- | --- |
| Dependency vulnerabilities | `pip-audit` found 21 known advisories across `pyjwt` (2.10.1) and `starlette` (0.41.3, transitive via `fastapi` 0.115.6) | Upgraded `pyjwt` to 2.13.0 and `fastapi` to 0.139.0 (pulling starlette 1.3.1, which patches every flagged advisory). Also upgraded `pytest`/`pytest-asyncio` (dev-only) for a `pytest` advisory. Full unit suite (82 tests), ruff, and mypy re-verified clean after the bump. |
| JWT key length | The upgraded `pyjwt` started emitting `InsecureKeyLengthWarning` for the dev-default `JWT_SECRET_KEY` (29 bytes, under the 32-byte HMAC-SHA256 recommendation) | Padded the dev default to 36 bytes. Still loudly documented as insecure/must-override — this only silences a noisy warning on an already-flagged placeholder, it doesn't make the default "safe to ship." |
| Trust model documentation | The shell/Playwright execution model (arbitrary code execution is the point) wasn't written down anywhere as an intentional design decision vs. an oversight | Added a "Security model" section to `docs/architecture.md` covering: why arbitrary execution is safe here (per-job ephemeral/isolated workers, scoped IAM, private-only networking), dual-credential auth converging on one identity, JWT algorithm pinning, and the request-logging redaction already in place since Phase 1. |
| IAM least-privilege | Re-verified `infra/terraform/modules/iam` | No wildcard resources — unchanged from Phase 3, confirmed still correct. |
| Request logging | Re-verified `RequestContextMiddleware` | Only method/path/status/duration logged, no bodies/headers/tokens — unchanged from Phase 1, confirmed still correct. |
| `npm audit` | Frontend dependencies | 0 vulnerabilities found. |
| Stale test code found during this pass | `tests/integration/test_worker_lifecycle_integration.py` called `JobProcessor(executor=...)` — a signature that stopped existing when Phase 6 moved to `executors: dict[JobType, JobExecutor]`. This file has never successfully run in this sandbox (blocked on Postgres), so the drift went uncaught. | Fixed to `executors={JobType.SHELL: fake_executor}` at both call sites. Unrelated to this phase's security scope but left broken code would have violated "never leave the project in a broken state." |

## Tests run

```
Backend:
ruff check backend/app backend/tests           -> All checks passed!
ruff format --check backend/app backend/tests  -> clean
mypy backend/app                                -> Success: no issues found in 48 source files
pytest backend/tests/unit                       -> 82 passed (was 63 at end of Phase 7; +19 this
                                                    phase: WorkerReaper x7, rate limiter x4,
                                                    rate-limit-endpoint x2, metrics x6)
pip-audit                                       -> No known vulnerabilities found
pytest backend/tests/integration                -> attempted; same standing InvalidPasswordError
                                                    root cause as every phase since Phase 2 (no
                                                    new error types) — includes 2 new
                                                    WorkerReaper integration tests, written and
                                                    ready, unverified in this sandbox

Frontend:
npm run lint       -> clean (1 informational warning, pre-existing since Phase 7)
npm run typecheck  -> clean
npm run build      -> succeeds, dist/ produced
npm run test       -> same vite-node/tilde-path environment issue root-caused in Phase 7
                       (this machine's user directory is literally `D~`) — unrelated to this
                       phase's changes, still CI-unaffected
npx playwright test --list -> 2 tests discovered, config/specs parse correctly (execution needs
                       a running backend+Postgres this sandbox doesn't have)

CI/CD:
YAML-parsed .github/workflows/deploy.yml successfully (same PyYAML `on:` -> `True` key quirk
the pre-existing ci.yml also exhibits — not a defect)
```

## Technical debt (end of Phase 8 / project)

Carried forward, not resolved by this phase (all previously documented, restated here for a
single end-of-project view):

1. Postgres-backed integration tests have never run successfully in this development sandbox
   (no reachable Postgres with matching credentials) — standing since Phase 2, always verified by
   error-type grep to confirm no new bugs, never silently assumed fine.
2. Terraform has never been `apply`'d and the Packer AMI has never been built against a real AWS
   account — authored and validated (`terraform validate`, where possible `packer validate`), not
   proven end-to-end.
3. No password reset / email verification (Phase 7).
4. No refresh tokens — 60-minute hard JWT expiry (Phase 7).
5. `npm run test` unverified directly in this specific local sandbox (tilde-path/vite-node issue,
   root-caused in Phase 7, confirmed CI-unaffected).
6. E2E tests are scaffolded, not executed — same Postgres/Docker limitation as #1.
7. Rate limiting is in-memory/single-process — doesn't coordinate across multiple API replicas.
   Needs a shared store (Redis/Postgres) for real multi-replica production use.
8. No distributed tracing — logs + metrics only (see `docs/observability.md`).
9. No production hosting stack for the API/worker containers is prescribed — deliberate scope
   boundary (see `docs/deployment-guide.md`), but it does mean a customer has real work left
   before this is running anywhere.
10. Frontend has no design system — plain CSS, acceptable for a beta (Phase 7).

## What's next (not a Phase 9 — the roadmap ends here)

The original 8-phase roadmap is complete. Reasonable next steps, driven explicitly by the user
rather than assumed:

- **Real AWS deployment**: `terraform apply` against a real account, build the Packer AMI, and
  run through `docs/deployment-guide.md` end to end — the single biggest gap between "authored"
  and "proven."
- **Run the E2E suite** once a real backend+Postgres is reachable.
- **Pick a production hosting platform** for the API/worker containers and, if desired, build a
  Terraform module for it (explicitly out of scope for this repo as shipped).
- **Wire `deploy.yml`'s secrets** (container registry auth is already GITHUB_TOKEN-based; AWS
  credentials need to be added as repo/environment secrets) once a GitHub remote exists.
- Address technical debt items above as they become relevant to real usage, rather than
  speculatively.
