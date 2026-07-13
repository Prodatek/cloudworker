from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.infrastructure.database import check_database_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


@router.get("/healthz", response_model=HealthResponse, summary="Liveness probe")
async def healthz() -> HealthResponse:
    """Returns 200 as long as the process is running. Has no external dependencies."""
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=ReadinessResponse, summary="Readiness probe")
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    """Returns 200 only if the API can actually reach Postgres, 503 otherwise."""
    engine = request.app.state.db_engine
    database_ok = await check_database_connection(engine)
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if database_ok else "degraded",
        database="ok" if database_ok else "unreachable",
    )
