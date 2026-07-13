# Example API Calls

Assumes the API is running locally via `docker compose up --build` (`http://localhost:8000`).

## Liveness probe

```bash
curl -i http://localhost:8000/healthz
```

```json
HTTP/1.1 200 OK
{"status": "ok"}
```

## Readiness probe (checks real Postgres connectivity)

```bash
curl -i http://localhost:8000/readyz
```

```json
HTTP/1.1 200 OK
{"status": "ok", "database": "ok"}
```

If Postgres is unreachable, this returns `503` with `{"status": "degraded", "database": "unreachable"}`.

## Prometheus metrics

```bash
curl http://localhost:8000/metrics
```

```text
# HELP cloudworker_http_requests_total Total HTTP requests
# TYPE cloudworker_http_requests_total counter
cloudworker_http_requests_total{method="GET",path="/healthz",status_code="200"} 1.0
...
```

## Register a user (returns an API key — shown only once)

```bash
curl -i -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "correct horse battery staple"}'
```

```json
HTTP/1.1 201 Created
{
  "user_id": "b6a1c9de-...",
  "email": "alice@example.com",
  "api_key": "cw_live_9pQ2z...=="
}
```

Registering the same email twice returns `409 Conflict`.

## Log in (dashboard auth — returns a JWT, not an API key)

```bash
curl -i -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "password": "correct horse battery staple"}'
```

```json
HTTP/1.1 200 OK
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "user_id": "b6a1c9de-...",
  "email": "alice@example.com"
}
```

The `access_token` works as an `Authorization: Bearer <token>` header on every endpoint an API
key does — `get_current_user` accepts either, telling them apart by the `cw_live_` prefix API
keys always carry. Wrong password or unknown email both return the same generic `401` (doesn't
reveal which). This is what the dashboard (`frontend/`) uses; API clients keep using API keys.

## Manage API keys (requires being logged in, via either credential type)

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/api-keys

curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/api-keys

curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/api-keys/<id>/revoke
```

`POST /api/v1/api-keys` returns the new key's full value once (same one-time-reveal pattern as
registration); `GET`/list only ever returns the `prefix`. A revoked key immediately stops
authenticating; revoking one key never affects a user's other keys.

## Create a job

```bash
export API_KEY=cw_live_9pQ2z...==

curl -i -X POST http://localhost:8000/api/v1/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "shell", "payload": {"command": "echo hi"}}'
```

```json
HTTP/1.1 201 Created
{
  "id": "3fa5c2e1-...",
  "job_type": "shell",
  "status": "queued",
  "payload": {"command": "echo hi"},
  "result": null,
  "error_message": null,
  "created_at": "2026-07-13T12:00:00Z",
  "updated_at": "2026-07-13T12:00:00Z",
  "started_at": null,
  "completed_at": null
}
```

`payload.command` is required and must be a non-empty string for `job_type: shell` — an empty or
missing command is rejected immediately:

```bash
curl -i -X POST http://localhost:8000/api/v1/jobs \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{"job_type": "shell", "payload": {}}'
# HTTP/1.1 422 Unprocessable Entity
```

Once a Worker Manager process is running (Phase 4/5; see `docker-compose.yml`'s `worker` service)
and pointed at a real, Terraform-applied AWS account, this job is picked up automatically: an EC2
worker is provisioned for it, the command actually runs on it over SSM, and the job's `status`
moves through `running` → `succeeded`/`failed`. Polling `GET /api/v1/jobs/{id}` shows the
progression:

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/jobs/3fa5c2e1-...
```

```json
{
  "id": "3fa5c2e1-...",
  "job_type": "shell",
  "status": "succeeded",
  "payload": {"command": "echo hi"},
  "result": {
    "exit_code": 0,
    "status": "Success",
    "s3_bucket": "cloudworker-dev-<account-id>-logs",
    "stdout_key": "jobs/3fa5c2e1-.../<ssm-command-id>/<instance-id>/awsrunShellScript/0.awsrunShellScript/stdout",
    "stderr_key": "jobs/3fa5c2e1-.../<ssm-command-id>/<instance-id>/awsrunShellScript/0.awsrunShellScript/stderr"
  },
  "error_message": null,
  "created_at": "2026-07-13T12:00:00Z",
  "updated_at": "2026-07-13T12:00:05Z",
  "started_at": "2026-07-13T12:00:01Z",
  "completed_at": "2026-07-13T12:00:05Z"
}
```

`result` holds the exit code plus S3 key references to the full, untruncated stdout/stderr — SSM
writes those directly to the logs bucket.

## Create a browser job (Playwright)

```bash
curl -i -X POST http://localhost:8000/api/v1/jobs \
  -H "Authorization: Bearer $API_KEY" -H "Content-Type: application/json" \
  -d '{
    "job_type": "browser",
    "payload": {
      "script": "page.goto(\"https://example.com\")\npage.screenshot(path=output_dir / \"home.png\")"
    }
  }'
```

`payload.script` is a Python Playwright script, run by the runner harness baked into the worker
AMI (`infra/packer/`). It's given `page`/`browser`/`context`/`output_dir` to use directly — video
is recorded automatically for the whole session; call `page.screenshot(path=output_dir / "...")`
for explicit screenshots. Everything left in `output_dir` when the script finishes is uploaded to
the artifacts bucket. Same validation pattern as shell: an empty/missing `payload.script` is
rejected with `422` before the job is ever queued.

## Fetch a job's artifacts (logs, screenshots, video)

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/jobs/3fa5c2e1-.../artifacts
```

```json
{
  "artifacts": [
    {
      "key": "jobs/3fa5c2e1-.../cmd-id/i-instance/awsrunShellScript/0.awsrunShellScript/stdout",
      "kind": "log",
      "size_bytes": 42,
      "url": "https://cloudworker-dev-<account-id>-logs.s3.amazonaws.com/...(presigned)...",
      "expires_in_seconds": 900
    },
    {
      "key": "jobs/3fa5c2e1-.../artifacts/home.png",
      "kind": "screenshot",
      "size_bytes": 15234,
      "url": "https://cloudworker-dev-<account-id>-artifacts.s3.amazonaws.com/...(presigned)...",
      "expires_in_seconds": 900
    }
  ]
}
```

Each `url` is a presigned S3 GET URL, valid for `expires_in_seconds` (configurable via
`ARTIFACT_URL_EXPIRY_SECONDS`, default 900). If the AWS logs/artifacts buckets aren't configured,
this returns `503`, same pattern as job cancellation's worker-termination path when AWS isn't set
up.

## List / cancel a job

```bash
curl -H "Authorization: Bearer $API_KEY" http://localhost:8000/api/v1/jobs

curl -X POST -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/api/v1/jobs/3fa5c2e1-.../cancel
```

- A job can be cancelled while `queued` **or** `running` — cancelling a `running` job also
  terminates the EC2 worker that was provisioned for it (Phase 4).
- Cancelling a job that's already `cancelled`/`succeeded`/`failed` → `409 Conflict`.
- Fetching a job that doesn't exist, or belongs to another user → `404 Not Found`.
- Any `/api/v1/jobs*` call without a valid `Authorization: Bearer <key>` header → `401 Unauthorized`.

## Interactive docs

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Raw OpenAPI schema: <http://localhost:8000/openapi.json>

## Dashboard

`frontend/` (React + TypeScript, `docker compose up frontend` or `npm run dev`) is a UI over
everything above — log in, submit shell/browser jobs, poll status, download artifacts, manage API
keys. See `frontend/README.md`.
