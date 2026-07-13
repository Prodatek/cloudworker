# Phase 6 Report: Playwright Browser Automation + Artifact Service

## What was built

- **`infra/packer/`**: a Packer template (`worker-ami.pkr.hcl`) that layers Playwright + Chromium
  and a runner harness (`scripts/run_playwright.py`) onto the same AL2023 base Phase 3's launch
  template already references — one universal AMI for both job types, per the user's choice. The
  runner: executes a job's script inside a `sync_playwright()` context (exposing
  `page`/`browser`/`context`/`output_dir`), records video for the whole session automatically,
  and uploads everything left in `output_dir` to the artifacts bucket via the instance's own IAM
  role. `infra/terraform/modules/compute` gains an optional `custom_ami_id` variable (falls back
  to the stock AL2023 SSM parameter when unset), so this is adoptable incrementally.
- **`JobExecutor` protocol signature changed** from `execute(job_id, command, instance_id)` to
  `execute(job: Job, instance_id: str)` — each executor now extracts what it needs from
  `job.payload` itself (`command` for shell, `script` for browser) instead of `JobProcessor`
  needing to know every job type's payload shape.
- **`PlaywrightJobExecutor`** (`app/infrastructure/aws/playwright_job_executor.py`): base64-embeds
  the job's script into an SSM command that decodes it to a file and invokes the runner harness,
  dispatches via the same SSM mechanics as shell jobs, and — after a terminal status — calls
  `ArtifactStore.list_job_artifacts()` to report what the runner actually uploaded (more robust
  than parsing stdout for a manifest).
- **`app/infrastructure/aws/ssm_command_dispatch.py`** (new, shared): the send-command-then-poll
  mechanics extracted out of `SsmJobExecutor` so `PlaywrightJobExecutor` doesn't duplicate it —
  genuine duplication across two concrete call sites, not speculative abstraction.
- **`ArtifactStore` protocol + `S3ArtifactStore`**: lists a job's objects across both the logs and
  artifacts buckets (classified by key suffix into log/screenshot/video/other) and generates
  presigned GET URLs. Exposed via `GET /api/v1/jobs/{id}/artifacts`.
- **`JobProcessor` takes `executors: dict[JobType, JobExecutor]`** instead of a single executor —
  looks up the right one before provisioning, so an unsupported job type still fails fast without
  wasting a worker (same reasoning Phase 5 used for the shell-only check, now generalized to
  whatever's actually registered).
- Payload validation extended: `payload.script` is required and non-empty for `browser` jobs, same
  treatment `command` already got for `shell` jobs.
- Config: `artifacts_bucket_name`, `artifact_url_expiry_seconds` (900s default).

## Why it was designed this way

- **One universal AMI** (user's choice) avoids threading "which launch template for which job
  type" through `EC2WorkerProvisioner`, Terraform, and job dispatch — shell jobs simply never
  touch the Playwright bits that get added to the image.
- **Full Playwright script, not a declarative action list** (user's choice): consistent with shell
  jobs already trusting arbitrary customer code; no new action-grammar to design, document, and
  keep in sync with whatever Playwright itself can do.
- **`JobExecutor.execute(job, instance_id)` instead of `execute(job_id, command, instance_id)`**:
  the old signature baked in a shell-specific assumption ("jobs have a command") that broke the
  moment a second job type needed something else ("script"). This is a real API correction, not
  a cosmetic rename — worth calling out plainly since it's a breaking change to code written just
  one phase ago.
- **Artifacts listed via `ArtifactStore` after the fact, not parsed from stdout**: the runner
  harness uploads directly to S3 using its own IAM role; asking `PlaywrightJobExecutor` to also
  parse a stdout manifest would be a second, more fragile source of truth for the same
  information.
- **Presigned URLs, not a raw S3 passthrough proxy**: standard, well-understood pattern — the API
  never touches artifact bytes, just hands out time-limited signed links; `ArtifactStore` is the
  only thing that needs S3 read access beyond the workers themselves.

## Trade-offs

- **The AMI has not been built** — this environment has no real AWS credentials, so
  `packer build` (which launches a real EC2 instance) can't run here any more than `terraform
  apply` could in Phase 3. Authored and (where checkable) reviewed, not proven. `packer` itself
  also isn't installed in this sandbox, so not even `packer validate` could be attempted — noted
  explicitly rather than silently skipped.
- **The runner harness (`run_playwright.py`) is entirely unverified** — it only ever runs on a
  real worker with real Playwright/Chromium installed, which doesn't exist anywhere this session
  could reach. Written carefully (narrow try/except around script execution, always attempts the
  S3 upload even if the script raised), but "written carefully" isn't the same as "tested."
- **`exec()` of a customer-supplied script inside the runner** is the same trust model shell jobs
  already have (arbitrary customer code, running on an ephemeral, network-isolated worker) — not
  a new risk category, but worth stating plainly since `exec()` reads alarming out of context.
- **Video is always recorded, not opt-in** — simplest MVP (every browser job gets a video without
  the customer needing to configure anything), at the cost of extra storage/upload cost for jobs
  that don't want it. Configurable-per-job is a reasonable follow-up if it matters in practice.
- **No cleanup of old Packer-built AMIs** — noted in `infra/packer/README.md` as a gap, not solved
  here.

## Tests run

```
ruff check backend/app backend/tests           -> All checks passed!
ruff format --check backend/app backend/tests  -> clean
mypy backend/app                                -> Success: no issues found in 44 source files
pytest backend/tests/unit                       -> 49 passed
pytest backend/tests/integration (moto-backed)  -> 5 passed (2 new S3 artifact tests + 3 existing EC2 tests)
```

New this phase: `test_playwright_execution_polling.py` (dispatch call-shape, base64 round-trip,
artifact reporting on success, failure/timeout/dispatch-error paths — same hand-mocked-SSM-client
pattern as `test_ssm_execution_polling.py`, since moto doesn't simulate real Run Command
execution any more than it simulates SSM agent check-in); `test_s3_artifact_store.py`
(`generate_presigned_url` tested for real — genuine URL/signature/expiry assertions, not just
"a mock was called," since presigned URL generation is pure local signing); a new moto integration
test (`test_s3_artifact_store_moto.py`) proving `list_job_artifacts` against real (moto-simulated)
bucket contents across both buckets with correct classification — S3 operations are fully
simulable by moto, unlike EC2 instance status/SSM agent check-in, so this is stronger coverage
than Phases 4–5 could get.

One thing worth flagging from writing the presigned-URL tests: the first attempt used
`monkeypatch.setenv` for fake credentials and got real (stale) credentials from this machine's
`~/.aws` in the resulting URL anyway — a `boto3.client()` call reuses a process-global default
session, so credentials resolved by an *earlier* test in the same pytest run can outlive a later
test's env-var monkeypatching. Fixed by wrapping in `mock_aws()` instead, which moto guarantees
isolates regardless of what any other test in the run already did. Also caught (separately) that
the resulting presigned URLs used legacy SigV2 query params (`AWSAccessKeyId=`/`Signature=`) —
botocore's default for `us-east-1` — rather than the modern SigV4 format
(`X-Amz-Signature=`/`X-Amz-Expires=`) most regions require; fixed in `S3ArtifactStore` itself
(`Config(signature_version="s3v4")`), a real production bug the tests caught, not just a test
artifact.

**Postgres-backed integration tests (including the new artifacts endpoint) were attempted and
failed for the same single reason as every prior phase**: `InvalidPasswordError` against the
sandbox's unreachable Postgres. Confirmed via grep that every failure in this run traces to that
one root cause — no new code bugs. `test_job_artifacts_integration.py` is written correctly
(success case with presigned URLs, 404 for a missing job, 503 when AWS isn't configured) but
unverified here.

**Action for the user, before treating Phase 6 as fully proven**: `docker compose up -d db` +
migrations + `pytest backend/tests/integration` should go green, and separately — with real AWS
credentials, whenever that's available — `packer build infra/packer/worker-ami.pkr.hcl` needs to
actually run at least once to prove the AMI itself builds and the runner harness works against a
real browser.

## Technical debt

1. Worker AMI never built or run for real (highest-priority item — nothing about browser jobs is
   proven end-to-end until this happens).
2. Postgres-backed integration tests unverified in this sandbox (standing item).
3. No AMI cleanup/lifecycle management.
4. Video always recorded (no per-job opt-out).
5. No per-job execution resource limits (a Playwright script could theoretically run indefinitely
   within the shared `job_execution_timeout_seconds`, same ceiling shell jobs already have — not
   new debt, just worth remembering it applies here too).
6. `JobExecutor.execute()`'s signature change means any external code depending on the old
   3-argument shape would break — acceptable since nothing outside this repo depends on it yet,
   but worth remembering once there's a public plugin/extension story.

## Proposed Phase 7: React + TypeScript Dashboard

Scope proposal (not yet implemented):
- A new `frontend/` (Vite + React + TypeScript) submitting jobs, polling status, and displaying
  results — the first phase touching anything outside `backend/`.
- Login/API-key management UI (Phase 2's auth, never had a UI).
- Live-ish log/status view (polling `GET /api/v1/jobs/{id}`, no new backend endpoint needed) and
  an artifact browser (consuming this phase's `GET /api/v1/jobs/{id}/artifacts` directly).
- Docker Compose gains a `frontend` service; CI gains a frontend lint/build/test job.
- This is the first phase with no AWS-credential constraint at all — everything is testable for
  real in this sandbox (no moto, no "unverified" caveats), a welcome change from Phases 3–6.

Will present this as a full plan for approval before writing any Phase 7 code, same as every
phase so far.
