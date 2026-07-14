# Observability

CloudWorker exposes structured JSON logs to stdout and Prometheus metrics at `GET /metrics`. It
doesn't ship or deploy Prometheus/Grafana itself — a customer scrapes `/metrics` with their own
monitoring stack (Prometheus, Datadog agent, Grafana Alloy, etc.). This doc describes what's
exposed and how to query it once it's being scraped.

## Logs

Every request is logged once, on completion, by `RequestContextMiddleware`
(`app/core/middleware.py`):

```json
{"timestamp": "...", "level": "INFO", "logger": "cloudworker.request",
 "message": "POST /api/v1/jobs -> 201 (42.10ms)", "request_id": "..."}
```

- `request_id` comes from the caller's `X-Request-Id` header if present, otherwise a generated
  UUID — echoed back in the response's `X-Request-Id` header so a caller can correlate their
  request with server-side logs.
- Only method, path, status code, and duration are logged — never request/response bodies,
  headers, or tokens (see `docs/architecture.md`'s Security model section).
- The worker process (`app/worker_entrypoint.py`) logs job/worker lifecycle transitions
  (provisioning, execution failures, reaping) through the same structured JSON formatter
  (`app/core/logging.py`), tagged with `cloudworker.job_processor` / `cloudworker.worker_manager`
  / `cloudworker.worker_reaper` loggers.

## Metrics

`GET /metrics` (unversioned, alongside `/healthz`/`/readyz`) returns Prometheus exposition
format. Defined in `app/infrastructure/metrics.py`:

| Metric | Type | Labels | Meaning |
| --- | --- | --- | --- |
| `cloudworker_http_requests_total` | Counter | `method`, `path`, `status_code` | Every HTTP request handled by the API. |
| `cloudworker_http_request_duration_seconds` | Histogram | `method`, `path` | API request latency. |
| `cloudworker_jobs_total` | Counter | `job_type`, `status` | Incremented once per job reaching a terminal state (`succeeded`/`failed`/`cancelled`), from wherever that happens: `JobProcessor`, the cancel endpoint, or `WorkerReaper`. |
| `cloudworker_worker_provisioning_seconds` | Histogram | — | Time from starting `WorkerManager.provision_worker()` to it returning (success or failure) — launch + SSM-ready wait. |
| `cloudworker_job_execution_seconds` | Histogram | `job_type` | Time spent inside the job's `JobExecutor.execute()` call. |
| `cloudworker_workers_reaped_total` | Counter | — | Workers force-terminated by `WorkerReaper` after being stuck in a non-terminal status past `WORKER_STALE_AFTER_SECONDS`. Should normally stay at 0; a nonzero rate means something upstream (provisioning, SSM, or the executor) is hanging or crashing. |

## Example PromQL queries

```promql
# Request rate by endpoint, last 5 minutes
sum by (path) (rate(cloudworker_http_requests_total[5m]))

# p95 API latency by endpoint
histogram_quantile(0.95, sum by (le, path) (rate(cloudworker_http_request_duration_seconds_bucket[5m])))

# Job failure rate by type, last 15 minutes
sum by (job_type) (rate(cloudworker_jobs_total{status="failed"}[15m]))
/
sum by (job_type) (rate(cloudworker_jobs_total[15m]))

# p95 worker provisioning latency — alert if this trends up, it means AWS/SSM is degraded
histogram_quantile(0.95, rate(cloudworker_worker_provisioning_seconds_bucket[15m]))

# p95 job execution duration by type
histogram_quantile(0.95, sum by (le, job_type) (rate(cloudworker_job_execution_seconds_bucket[15m])))

# Any reaping at all in the last hour — should alert on > 0
increase(cloudworker_workers_reaped_total[1h]) > 0
```

## Health checks

- `GET /healthz` — liveness only (process is up). No dependencies checked.
- `GET /readyz` — readiness: confirms the API can reach Postgres. Returns 503 if not.

## Trade-offs / known limitations

- No tracing (OpenTelemetry spans) — logs + metrics only. Acceptable for a beta's single-process
  API/worker topology where a request's full path is usually inferable from `request_id`
  correlation; would be worth adding if this becomes a multi-service deployment.
- `cloudworker_workers_reaped_total` and the reaper's `poll_interval`/`stale_after` thresholds
  (`WORKER_REAPER_POLL_INTERVAL_SECONDS`/`WORKER_STALE_AFTER_SECONDS`, `backend/.env.example`)
  are the main "is something stuck" signal — there's no dead-letter queue or alerting config
  shipped, since this repo doesn't prescribe a specific alerting stack (see the deployment guide).
