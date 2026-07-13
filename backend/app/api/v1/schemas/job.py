import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.entities import Job, JobStatus, JobType


class JobCreateRequest(BaseModel):
    job_type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: uuid.UUID
    job_type: JobType
    status: JobStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_entity(cls, job: Job) -> "JobResponse":
        return cls(
            id=job.id,
            job_type=job.job_type,
            status=job.status,
            payload=job.payload,
            result=job.result,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    limit: int
    offset: int
