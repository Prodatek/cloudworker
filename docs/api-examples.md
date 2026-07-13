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
writes those directly to the logs bucket. Fetching the actual log contents from S3 (e.g. via
presigned URLs, with proper access control) is Phase 6's Artifact Service, not this phase.

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
