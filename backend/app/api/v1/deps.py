from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import FixedWindowRateLimiter, RateLimitExceededError
from app.domain.artifact_store import ArtifactStore
from app.domain.entities import User
from app.infrastructure.database import get_db_session
from app.infrastructure.db.api_key_repository import SqlAlchemyApiKeyRepository
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.user_repository import SqlAlchemyUserRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.infrastructure.security import (
    InvalidAccessTokenError,
    decode_access_token,
    hash_api_key,
    looks_like_api_key,
)
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
        worker_repository=worker_repository,
        provisioner=provisioner,
        ssm_ready_timeout_seconds=settings.ssm_ready_timeout_seconds,
    )


def get_artifact_store(request: Request) -> ArtifactStore | None:
    """Returns None (not an error) when the artifact/logs buckets aren't configured —
    same reasoning as get_worker_manager: expected in local dev before Phase 3's
    Terraform has actually been applied.
    """
    return request.app.state.artifact_store


def get_auth_rate_limiter(request: Request) -> FixedWindowRateLimiter:
    # Lazily created rather than assumed to exist, so this dependency works whether or
    # not app lifespan startup ran (e.g. httpx's ASGITransport doesn't trigger it unless
    # asked to) — mirrors the None-until-configured pattern get_worker_manager/
    # get_artifact_store already use for other app.state-backed resources.
    limiter = getattr(request.app.state, "auth_rate_limiter", None)
    if limiter is None:
        settings = get_settings()
        limiter = FixedWindowRateLimiter(
            max_attempts=settings.auth_rate_limit_max_attempts,
            window_seconds=settings.auth_rate_limit_window_seconds,
        )
        request.app.state.auth_rate_limiter = limiter
    return limiter


def enforce_auth_rate_limit(
    request: Request,
    limiter: FixedWindowRateLimiter = Depends(get_auth_rate_limiter),
) -> None:
    """Applied to register/login. Keyed by client IP — good enough to blunt naive
    credential-stuffing/brute-force from a single source; see FixedWindowRateLimiter's
    docstring for the in-memory/single-process trade-off.
    """
    client_host = request.client.host if request.client is not None else "unknown"
    try:
        limiter.check(client_host)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts, please try again later",
        ) from exc


async def get_current_user(
    request: Request,
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> User:
    """Accepts either an API key or a JWT (from POST /api/v1/auth/login) in the same
    Authorization: Bearer header — dispatched by the cw_live_ prefix API keys carry, so
    the dashboard authenticates through the exact same dependency every API client does.
    """
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = authorization.removeprefix("Bearer ").strip()

    if looks_like_api_key(token):
        key_record = await api_key_repository.get_by_hashed_key(hash_api_key(token))
        if key_record is None or key_record.is_revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        user_id = key_record.user_id
    else:
        settings = get_settings()
        try:
            user_id = decode_access_token(
                token, secret_key=settings.jwt_secret_key, algorithm=settings.jwt_algorithm
            )
        except InvalidAccessTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
            ) from exc

    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    return user
