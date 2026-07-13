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

## Interactive docs

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- Raw OpenAPI schema: <http://localhost:8000/openapi.json>
