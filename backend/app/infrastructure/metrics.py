import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_COUNT = Counter(
    "cloudworker_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "cloudworker_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)

# Incremented whenever a job reaches a terminal state (succeeded/failed/cancelled),
# from wherever that transition happens: JobProcessor, the cancel endpoint, or WorkerReaper.
JOBS_TOTAL = Counter(
    "cloudworker_jobs_total",
    "Total jobs reaching a terminal state",
    ["job_type", "status"],
)

# Observed in WorkerManager.provision_worker() around the launch+SSM-ready wait, on both
# success and failure — provisioning latency (and its failure rate) is a key SLO signal.
WORKER_PROVISIONING_SECONDS = Histogram(
    "cloudworker_worker_provisioning_seconds",
    "Time to provision a worker and reach SSM-ready, in seconds",
)

# Observed in JobProcessor around each executor.execute() call, success or failure.
JOB_EXECUTION_SECONDS = Histogram(
    "cloudworker_job_execution_seconds",
    "Job execution duration in seconds",
    ["job_type"],
)

# Incremented by WorkerReaper for each stale worker it terminates.
WORKERS_REAPED_TOTAL = Counter(
    "cloudworker_workers_reaped_total",
    "Total workers force-terminated by the reaper after being stuck in a non-terminal status",
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Records request count and latency for every HTTP request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_seconds = time.perf_counter() - started_at

        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path

        REQUEST_COUNT.labels(
            method=request.method, path=path, status_code=response.status_code
        ).inc()
        REQUEST_LATENCY.labels(method=request.method, path=path).observe(duration_seconds)
        return response


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
