# Phase 4 Report: Worker Manager

## What was built

- **Domain**: `WorkerStatus` enum (`pending`/`provisioning`/`ready`/`terminating`/`terminated`/
  `failed`) and a `Worker` dataclass; `WorkerRepository` and `WorkerProvisioner` protocols
  (`backend/app/domain/entities.py`, `repositories.py`, `worker_provisioner.py`).
- **Extended Phase 2's cancel semantics**: a job can now be cancelled while `running`, not just
  `queued` — `Job.is_cancellable` and `JobRepository.cancel()`'s SQL both changed to
  `WHERE status IN ('queued','running')`. A new `JobRepository.fail()` atomically transitions
  `running` → `failed`.
- **Infrastructure**: `WorkerModel` + `SqlAlchemyWorkerRepository` (Postgres); `workers` table via
  migration `0002`; `EC2WorkerProvisioner` (`infrastructure/aws/ec2_worker_provisioner.py`) —
  boto3-based, launches instances from Phase 3's launch template into a randomly-chosen
  configured subnet, tags them with the owning job id, polls SSM for registration, terminates.
- **`app/services/worker_manager.py`** (new `services/` layer): `WorkerManager` orchestrates
  claim → provision → SSM-ready → `ready`, marks failures and cleans up on any exception, and
  exposes `cancel_job_worker()` for the API to call when a running job is cancelled. Depends only
  on the `JobRepository`/`WorkerRepository`/`WorkerProvisioner` protocols — no SQLAlchemy or
  boto3 imports — so it's fully testable against in-memory fakes.
- **`app/worker_entrypoint.py`**: standalone process wiring real settings → engine → repositories
  → `EC2WorkerProvisioner` → `WorkerManager.run_forever()`. New `worker` service in
  `docker-compose.yml` runs it.
- **API**: `POST /api/v1/jobs/{id}/cancel` now also terminates the job's worker when it was
  `running`, via a new `get_worker_manager` dependency that returns `None` (not an error) when
  AWS isn't configured — a queued-job cancel never needed a worker and still doesn't require AWS
  to be set up.
- **Config**: `aws_region`, `launch_template_id`, `worker_subnet_ids`, `ssm_ready_timeout_seconds`,
  `worker_poll_interval_seconds` added to `Settings`, all env-driven, none hard-coded.

## Why it was designed this way

- **`services/` as a fourth layer** sits between `api`/`domain`/`infrastructure`: `WorkerManager`
  performs I/O (so it can't live in `domain`), isn't an HTTP concern (so it doesn't belong in
  `api`), and doesn't itself adapt to one external system (so it isn't `infrastructure`). This is
  the same layering principle used throughout the project, extended rather than bent to fit a new
  kind of component.
- **Standalone `worker` process, not a FastAPI background task**: EC2 provisioning + SSM
  registration can take 30–60s+; running that in-process with the API would either block request
  handling or require its own concurrency management inside a process that's supposed to be
  answering HTTP requests. A separate process polling the same Postgres queue keeps the two
  concerns (serve API requests fast; provision workers slowly) independently scalable.
- **`get_worker_manager` returns `None` instead of raising**: cancelling a `queued` job never had
  a worker to terminate, so requiring AWS configuration for *all* cancels would make local dev
  (no AWS yet) unable to cancel even a job that was never claimed. Only a `running` job's cancel
  path actually needs the provisioner, and that's exactly where the `None` check lives
  (`jobs.py`'s `cancel_job`).
- **`WorkerRepository`/`JobRepository.fail()` self-commit**, unlike the request-scoped Phase 2
  repositories: they're called from the standalone `WorkerManager` process loop, which has no
  HTTP request boundary to commit at the end of — same reasoning Phase 2 already established for
  `claim_next_job()`.

## Trade-offs

- **`moto` proves EC2 launch/terminate call shapes but not SSM agent check-in** — this was flagged
  going into the phase and confirmed true: `wait_until_ssm_ready()`'s retry/timeout *logic* is
  tested against a hand-mocked SSM client response sequence instead
  (`tests/unit/test_ssm_ready_polling.py`), separately from the moto-backed EC2 tests. Real
  end-to-end proof that a real instance's SSM Agent actually registers still needs a real AWS
  account.
- **Single long-lived DB session for the whole worker process** (`worker_entrypoint.py` opens one
  session and reuses it for the entire `run_forever()` loop) rather than a fresh session per
  iteration. Simpler, and safe because every repository method that mutates state self-commits —
  but a transient network blip during a raw `session.execute()` call (before a repo method's own
  try/except) isn't handled with reconnect/retry logic. Acceptable for a beta (the process would
  crash and restart via Docker's restart policy); worth revisiting if that proves noisy in
  practice.
- **Random subnet selection**, not round-robin or AZ-aware placement — simplest thing that spreads
  load across the configured subnets; fine at low worker counts, not optimized for balancing.
- **`docker-compose.yml`'s new `worker` service is inert without real AWS wiring** — documented
  explicitly rather than presented as "it just works," since claiming otherwise would be
  misleading given this environment couldn't prove it end-to-end.

## Tests run

```
ruff check backend/app backend/tests           -> All checks passed!
ruff format --check backend/app backend/tests  -> clean
mypy backend/app                                -> Success: no issues found in 36 source files
pytest backend/tests/unit                       -> 24 passed
pytest backend/tests/integration/test_ec2_worker_provisioner_moto.py -> 3 passed
```

The moto tests genuinely exercise real boto3 call shapes: launching from a real (moto-simulated)
launch template into a specific subnet, confirming the `cloudworker:job-id` tag lands on the
instance, confirming `terminate()` actually transitions instance state, and confirming a bad
launch template id raises `ProvisioningError` rather than crashing unhandled. One thing worth
knowing: `mock_aws` had to be used as a context manager inside each test rather than as a
decorator on the `async def` test function — moto's decorator form isn't async-aware and
pytest-asyncio silently *skips* (not fails) tests wrapped that way, which would have made these
tests silently no-ops. Caught by checking the test run output showed `SKIPPED` instead of
`PASSED` rather than assuming a clean run meant real coverage.

**Postgres-backed integration tests were attempted and failed for the same reason as every prior
phase**: this sandbox has no usable Postgres (a real local Postgres 18 service exists but with
different credentials than the app expects, and the user has twice declined provisioning a
`cloudworker` role/db in it). `test_worker_lifecycle_integration.py`'s two tests
(provision→ready→HTTP-cancel→terminate, and provisioning-failure→job-failed) are written and
correctly exercise the real `SqlAlchemyJobRepository`/`SqlAlchemyWorkerRepository`/HTTP-cancel
path against a fake provisioner, but have never been run successfully in this environment.

**Action for the user, before treating Phase 4 as fully proven**: with `docker compose up -d db`
and migrations applied, run `pytest backend/tests/integration/test_worker_lifecycle_integration.py`
— both tests should pass.

## Technical debt

1. Postgres-backed integration tests unverified in this sandbox (see above) — same standing item
   as every prior phase, now with two more tests added to the pile that need checking.
2. No retry/reconnect logic around the worker process's long-lived DB session.
3. Random (not AZ-aware or load-balanced) subnet selection.
4. `WorkerManager.run_forever()` has no backoff on repeated provisioning failures — a
   misconfigured launch template would fail every claimed job in a tight loop (bounded by
   `worker_poll_interval_seconds` only when the queue is empty, not when jobs keep arriving and
   failing). Worth a circuit breaker or exponential backoff before this runs against a real fleet.
5. No metrics/alerting on worker provisioning failures yet (Prometheus counters exist for HTTP
   requests since Phase 1, but nothing worker-process-specific) — reasonable to defer to Phase 8.
6. Still entirely unverified against real AWS (inherited from Phase 3, unchanged by this phase's
   moto coverage, which mocks the API surface, not real EC2/SSM/VPC-endpoint behavior).

## Proposed Phase 5: Shell Job Execution over SSM

Scope proposal (not yet implemented):
- `SendCommand` dispatch of the job's `payload.command` to a `ready` worker via SSM, using the
  `AWS-RunShellScript` document.
- Polling `GetCommandInvocation` for stdout/stderr and exit status; streaming output to S3 (logs
  bucket from Phase 3) and/or the `jobs.result` column.
- On completion (success or failure), transition the job to `succeeded`/`failed` and call the
  `WorkerManager` method Phase 4 deliberately left unimplemented: terminate-on-normal-completion.
- Timeout handling for jobs that never complete.
- This is the first phase where `docs/api-examples.md`'s "nothing executes this job yet" caveat
  finally goes away — worth an end-to-end example (create job → watch it run → see real output)
  once it's built.

Will present this as a full plan for approval before writing any Phase 5 code, same as Phases 1–4.
