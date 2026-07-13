import uuid
from typing import Protocol

from app.domain.entities import ApiKey, Job, User


class UserRepository(Protocol):
    async def create(self, email: str, hashed_password: str) -> User: ...

    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...


class ApiKeyRepository(Protocol):
    async def create(self, user_id: uuid.UUID, hashed_key: str, prefix: str) -> ApiKey: ...

    async def get_by_hashed_key(self, hashed_key: str) -> ApiKey | None: ...


class JobRepository(Protocol):
    async def create(self, user_id: uuid.UUID, job_type: str, payload: dict) -> Job: ...

    async def get_by_id_for_user(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None: ...

    async def list_for_user(self, user_id: uuid.UUID, limit: int, offset: int) -> list[Job]: ...

    async def cancel(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None:
        """Cancels the job if it belongs to the user and is still queued.

        Returns None if the job doesn't exist / isn't owned by the user; the caller
        distinguishes "not found" from "not cancellable" by re-fetching if needed.
        """
        ...

    async def claim_next_job(self) -> Job | None:
        """Atomically claims the oldest queued job using SELECT ... FOR UPDATE SKIP LOCKED.

        Safe to call concurrently from multiple workers: each job is claimed by
        exactly one caller.
        """
        ...
