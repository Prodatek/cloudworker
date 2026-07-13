import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from app.domain.entities import ApiKey, Job, User, Worker


class UserRepository(Protocol):
    async def create(self, email: str, hashed_password: str) -> User: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...


class ApiKeyRepository(Protocol):
    async def create(self, user_id: uuid.UUID, hashed_key: str, prefix: str) -> ApiKey: ...

    async def get_by_hashed_key(self, hashed_key: str) -> ApiKey | None: ...

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]: ...

    async def revoke(self, api_key_id: uuid.UUID, user_id: uuid.UUID) -> ApiKey | None:
        """Revokes the key if it belongs to the user and isn't already revoked.

        Returns None if it doesn't exist / isn't owned by the user / is already revoked.
        """
        ...


class JobRepository(Protocol):
    async def create(self, user_id: uuid.UUID, job_type: str, payload: dict) -> Job: ...

    async def get_by_id_for_user(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None: ...

    async def list_for_user(self, user_id: uuid.UUID, limit: int, offset: int) -> list[Job]: ...

    async def cancel(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None:
        """Cancels the job if it belongs to the user and is still queued or running.

        Returns None if the job doesn't exist / isn't owned by the user, or isn't in a
        cancellable state; the caller distinguishes "not found" from "not cancellable"
        by re-fetching if needed.
        """
        ...

    async def claim_next_job(self) -> Job | None:
        """Atomically claims the oldest queued job using SELECT ... FOR UPDATE SKIP LOCKED.

        Safe to call concurrently from multiple workers: each job is claimed by
        exactly one caller.
        """
        ...

    async def fail(self, job_id: uuid.UUID, error_message: str) -> Job | None:
        """Atomically transitions a running job to failed. Returns None if the job
        wasn't running (e.g. already cancelled/completed by someone else).
        """
        ...

    async def complete(self, job_id: uuid.UUID, result: dict) -> Job | None:
        """Atomically transitions a running job to succeeded, storing its result.
        Returns None if the job wasn't running.
        """
        ...


class WorkerRepository(Protocol):
    async def create(self, job_id: uuid.UUID) -> Worker: ...

    async def get_by_job_id(self, job_id: uuid.UUID) -> Worker | None: ...

    async def mark_provisioning(self, worker_id: uuid.UUID, instance_id: str) -> Worker: ...

    async def mark_ready(self, worker_id: uuid.UUID) -> Worker: ...

    async def mark_terminating(self, worker_id: uuid.UUID) -> Worker: ...

    async def mark_terminated(self, worker_id: uuid.UUID) -> Worker: ...

    async def mark_failed(self, worker_id: uuid.UUID, failure_reason: str) -> Worker: ...


@dataclass
class RepositoryBundle:
    """A JobRepository/WorkerRepository pair sharing one unit of work (DB session)."""

    job_repository: JobRepository
    worker_repository: WorkerRepository


# Called with no arguments, returns an async context manager yielding a fresh
# RepositoryBundle (backed by its own session) for the duration of the `with` block.
# JobProcessor depends on this instead of fixed repository instances so each concurrently
# processed job gets its own session; only worker_entrypoint.py (the composition root)
# knows this is actually backed by SQLAlchemy.
RepositoryFactory = Callable[[], AbstractAsyncContextManager[RepositoryBundle]]
