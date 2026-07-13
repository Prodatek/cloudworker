import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_current_user, get_job_repository
from app.api.v1.schemas.job import JobCreateRequest, JobListResponse, JobResponse
from app.domain.entities import User
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: JobCreateRequest,
    current_user: User = Depends(get_current_user),
    job_repository: SqlAlchemyJobRepository = Depends(get_job_repository),
) -> JobResponse:
    job = await job_repository.create(current_user.id, body.job_type.value, body.payload)
    return JobResponse.from_entity(job)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    job_repository: SqlAlchemyJobRepository = Depends(get_job_repository),
) -> JobListResponse:
    jobs = await job_repository.list_for_user(current_user.id, limit=limit, offset=offset)
    return JobListResponse(
        jobs=[JobResponse.from_entity(job) for job in jobs], limit=limit, offset=offset
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    job_repository: SqlAlchemyJobRepository = Depends(get_job_repository),
) -> JobResponse:
    job = await job_repository.get_by_id_for_user(job_id, current_user.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobResponse.from_entity(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    job_repository: SqlAlchemyJobRepository = Depends(get_job_repository),
) -> JobResponse:
    existing = await job_repository.get_by_id_for_user(job_id, current_user.id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    cancelled = await job_repository.cancel(job_id, current_user.id)
    if cancelled is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job cannot be cancelled from status '{existing.status.value}'",
        )
    return JobResponse.from_entity(cancelled)
