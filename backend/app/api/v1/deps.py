from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.domain.entities import User
from app.infrastructure.database import get_db_session
from app.infrastructure.db.api_key_repository import SqlAlchemyApiKeyRepository
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.user_repository import SqlAlchemyUserRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.infrastructure.security import hash_api_key
from app.services.worker_manager import WorkerManager


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session(request.app.state.db_session_factory):
        yield session


def get_user_repository(session: AsyncSession = Depends(get_session)) -> SqlAlchemyUserRepository:
    return SqlAlchemyUserRepository(session)


def get_api_key_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyApiKeyRepository:
    return SqlAlchemyApiKeyRepository(session)


def get_job_repository(session: AsyncSession = Depends(get_session)) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(session)


def get_worker_repository(
    session: AsyncSession = Depends(get_session),
) -> SqlAlchemyWorkerRepository:
    return SqlAlchemyWorkerRepository(session)


def get_worker_manager(
    request: Request,
    job_repository: SqlAlchemyJobRepository = Depends(get_job_repository),
    worker_repository: SqlAlchemyWorkerRepository = Depends(get_worker_repository),
) -> WorkerManager | None:
    """Returns None (not an error) when AWS isn't configured — expected in local dev
    before Phase 3's Terraform has actually been applied. A job can be cancelled from
    'queued' without ever needing this; callers that require it check for None
    themselves and respond accordingly (see jobs.py's cancel_job).
    """
    provisioner = request.app.state.worker_provisioner
    if provisioner is None:
        return None
    settings = get_settings()
    return WorkerManager(
        job_repository=job_repository,
        worker_repository=worker_repository,
        provisioner=provisioner,
        ssm_ready_timeout_seconds=settings.ssm_ready_timeout_seconds,
    )


async def get_current_user(
    request: Request,
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> User:
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    api_key = authorization.removeprefix("Bearer ").strip()
    key_record = await api_key_repository.get_by_hashed_key(hash_api_key(api_key))
    if key_record is None or key_record.is_revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    user = await user_repository.get_by_id(key_record.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    return user
