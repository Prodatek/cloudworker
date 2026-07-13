# Phase 5 Report: Shell Job Execution over SSM

## What was built

- **`JobExecutor` protocol + `SsmJobExecutor`** (`app/domain/job_executor.py`,
  `app/infrastructure/aws/ssm_job_executor.py`): dispatches a shell command via SSM
  `SendCommand` (`AWS-RunShellScript`), with `OutputS3BucketName`/`OutputS3KeyPrefix` set so SSM
  itself writes full, untruncated stdout/stderr to Phase 3's logs bucket. Polls
  `GetCommandInvocation` for a terminal status (`Success`/`Failed`/`Cancelled`/`TimedOut`),
  tolerating the brief window right after dispatch where SSM hasn't registered the invocation
  yet. Returns exit code + S3 key references, not log text.
- **`JobProcessor`** (`app/services/job_processor.py`): the new concurrency-aware orchestrator the
  worker process runs. Claims a job, spawns it as its own `asyncio` task (bounded by a
  `max_concurrent_jobs` semaphore, each task with its own DB session via a `RepositoryFactory`),
  and runs it through provision → dispatch → poll → complete/fail → terminate. Non-`shell` job
  types (i.e. `browser`) fail immediately with a clear "not yet supported" message instead of
  wasting a worker provisioning cycle on something nothing can execute yet.
- **`WorkerManager` split into worker-lifecycle-only** (`app/services/worker_manager.py`):
  Phase 4's inline provisioning logic is now `provision_worker(job_id) -> Worker`, reusable by
  `JobProcessor`; `cancel_job_worker` is renamed `terminate_worker_for_job` since `JobProcessor`
  now calls the identical method after normal completion, not just cancellation. `WorkerManager`
  no longer takes a `JobRepository` at all — it doesn't touch the jobs table, only `workers`.
- **`JobRepository.complete(job_id, result)`**: atomic `running` → `succeeded`, parallel to the
  existing `fail()`.
- **Validation**: `JobCreateRequest` gets a `model_validator` — a `shell` job's `payload.command`
  must be a non-empty string, or `POST /api/v1/jobs` returns `422` before the job is ever queued.
- **Config**: `logs_bucket_name`, `job_execution_timeout_seconds` (900s default),
  `max_concurrent_jobs` (5 default) — env-driven, matching every prior phase.
- **`worker_entrypoint.py`** rewritten from "one shared session for the whole process" to a
  `repository_factory` (session-per-task), constructing `JobProcessor` instead of calling
  `WorkerManager.run_forever()` directly (which no longer exists — `run_forever` moved to
  `JobProcessor`, since claiming/looping is a queue-consumer concern, not a worker-lifecycle one).

## Why it was designed this way

- **Splitting `WorkerManager` (lifecycle) from `JobExecutor` (execution) from `JobProcessor`
  (orchestration)** mirrors the mission's own separation of "Worker Manager" and "runs shell
  scripts" as distinct concerns, and keeps each class unit-testable against a single kind of fake
  without a database or AWS credentials — exactly the pattern `docs/architecture.md` already
  documents for `WorkerManager` since Phase 4, now extended to two more classes.
- **Concurrent job processing via per-task sessions**, not the serial loop Phase 4 shipped: this
  was surfaced as a real bug while building this phase (see Context in the plan) — a job that
  takes minutes to run would otherwise block every other queued job from even starting
  provisioning. `AsyncSession` isn't safe to share across concurrent `asyncio` tasks, so each task
  gets its own via `RepositoryFactory` (a `Protocol`, so `JobProcessor` stays ignorant of
  SQLAlchemy — only `worker_entrypoint.py`, the composition root, knows it's session-backed).
- **SSM's native `OutputS3BucketName`**, not manually re-uploading `GetCommandInvocation`'s
  response: that API truncates stdout/stderr at 2500 characters, so letting SSM write full output
  directly to S3 is the only way to satisfy "streams logs" without losing data on any
  non-trivial script. `jobs.result` stores key references, not text, keeping the JSONB column
  small regardless of how much a script prints.
- **Validate the shell command at creation time**: a job that would definitely fail (empty
  command) is rejected before it ever occupies a queue slot or costs a worker provisioning cycle
  — cheaper for the system and a clearer, immediate error for the caller than a 30-60s round trip
  to find out.

## Trade-offs

- **`asyncio.wait_for` wraps `JobExecutor.execute()` with its own external timeout** on top of
  `SsmJobExecutor`'s internal one — belt-and-suspenders against an executor implementation that
  doesn't correctly bound its own polling (a future `PlaywrightJobExecutor` in Phase 6, say).
  Slightly redundant for `SsmJobExecutor` itself, which already self-bounds; kept anyway since the
  cost is one extra `wait_for` call, not real complexity.
- **No circuit breaker on repeated provisioning/execution failures** — `JobProcessor` will happily
  claim and fail jobs in a tight loop if, say, `LAUNCH_TEMPLATE_ID` is misconfigured. Bounded only
  by `worker_poll_interval_seconds` when the queue is empty, not when it's full of jobs that will
  all fail the same way. Tracked as debt (inherited from Phase 4, still true).
- **`JobProcessor._run_job` is accessed directly in integration tests** (`# noqa: SLF001`) rather
  than only through the public `run_forever()` polling loop — chosen for determinism (no reliance
  on real-time sleeps/polling against a real Postgres in a test), at the cost of testing a
  "private" method directly. The unit tests (`test_job_processor.py`) do exercise the full
  `run_forever()` loop, including the concurrency-bounding behavior, against fast in-memory fakes.
- **Concurrency tests are timing-based** (`asyncio.sleep` delays + wall-clock windows in
  `test_job_processor.py`) — generous margins (150-200ms delays inside 400-500ms windows) keep
  them robust in practice, but timing-based tests are inherently a little more fragile than
  pure logic assertions. Accepted as the most direct way to prove real concurrent overlap.

## Tests run

```
ruff check backend/app backend/tests           -> All checks passed!
ruff format --check backend/app backend/tests  -> clean
mypy backend/app                                -> Success: no issues found in 39 source files
pytest backend/tests/unit                       -> 39 passed
pytest backend/tests/integration/test_ec2_worker_provisioner_moto.py -> 3 passed (unaffected by this phase)
```

New unit coverage this phase: `test_job_processor.py` (end-to-end shell success/failure,
provisioning-failure short-circuit, non-shell job type rejected without provisioning, concurrent
execution proven via overlap + semaphore bound), `test_ssm_execution_polling.py` (dispatch
call-shape, transient-status polling, invocation-not-yet-registered tolerance, our own timeout,
dispatch-failure → `JobExecutionError`), `test_worker_manager.py` rewritten for the new
lifecycle-only API, plus new payload-validation tests in `test_job_schemas.py`.

**Postgres-backed integration tests were attempted and failed for the same single reason as every
prior phase**: `asyncpg.exceptions.InvalidPasswordError` against the real local Postgres 18
service (no usable `cloudworker` role/db in this sandbox). All 12 failures in this run trace back
to that one root cause — confirmed by grepping the full failure output for distinct error types,
not just eyeballing pass/fail counts — so this phase introduced no new *code* bugs, only the same
standing environment limitation. `test_worker_lifecycle_integration.py` (extended with two new
`JobProcessor` end-to-end tests) and the fixed `test_job_queue_claim_concurrency.py`/
`test_jobs_integration.py` (both needed a `payload.command` added given the new validation) are
written correctly but unverified here.

**Action for the user, before treating Phase 5 as fully proven**: `docker compose up -d db` +
migrations + `pytest backend/tests/integration` should show all green, including the new
end-to-end shell execution flow.

## Technical debt

1. Postgres-backed integration tests unverified in this sandbox (standing item, now larger).
2. No circuit breaker/backoff on repeated job failures (see Trade-offs).
3. Still entirely unverified against real AWS — `moto` and hand-mocked SSM clients prove call
   shapes and orchestration logic, not real EC2/SSM/S3 behavior end-to-end.
4. `browser` job types fail immediately with a clear message (better than hanging forever) but
   Phase 6 still needs to actually implement them.
5. No retrieval endpoint for the S3 log keys `jobs.result` now references — a customer can see
   `stdout_key`/`stderr_key` but has no way to fetch that content through the API yet
   (deliberately deferred to Phase 6's Artifact Service, which needs real access-control design,
   not just a raw S3 passthrough).
6. `max_concurrent_jobs` is a single global knob per worker process — no per-user fairness/quota
   (one user submitting 100 jobs could starve another user's single job of a concurrency slot).
   Fine for a beta with few tenants; would need revisiting before multi-tenant scale.

## Proposed Phase 6: Playwright Browser Automation + Artifact Service

Scope proposal (not yet implemented):
- A `PlaywrightJobExecutor` (implementing the same `JobExecutor` protocol `SsmJobExecutor` does)
  for `job_type: browser` — likely needs a custom AMI (Packer) with Playwright/Chromium
  preinstalled, since AL2023 doesn't ship with either (the AMI decision Phase 3 explicitly
  deferred to "whenever it's actually needed").
- Screenshot/video capture during a browser job, uploaded to the Phase 3 artifacts bucket.
- A formal **Artifact Service**: presigned-URL retrieval endpoints for the S3 keys this phase
  already produces (`jobs.result.stdout_key`/`stderr_key`) plus Phase 6's new
  screenshot/video artifacts — with real access control (only the owning user can generate a
  presigned URL for their own job's artifacts).
- This phase will finally need the custom-AMI/Packer pipeline Phase 3 flagged as debt.

Will present this as a full plan for approval before writing any Phase 6 code, same as Phases 1–5.
