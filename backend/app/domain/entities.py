import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    SHELL = "shell"
    # Not executable until Phase 6, but accepted/persisted now so the job
    # model doesn't need reshaping when browser automation lands.
    BROWSER = "browser"


@dataclass
class User:
    id: uuid.UUID
    email: str
    hashed_password: str
    created_at: datetime


@dataclass
class ApiKey:
    id: uuid.UUID
    user_id: uuid.UUID
    hashed_key: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass
class Job:
    id: uuid.UUID
    user_id: uuid.UUID
    job_type: JobType
    status: JobStatus
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    result: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_cancellable(self) -> bool:
        return self.status == JobStatus.QUEUED
