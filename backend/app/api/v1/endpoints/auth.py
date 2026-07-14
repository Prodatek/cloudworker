from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import enforce_auth_rate_limit, get_api_key_repository, get_user_repository
from app.api.v1.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
from app.core.config import get_settings
from app.infrastructure.db.api_key_repository import SqlAlchemyApiKeyRepository
from app.infrastructure.db.user_repository import SqlAlchemyUserRepository
from app.infrastructure.security import (
    api_key_display_prefix,
    create_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def register(
    body: RegisterRequest,
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
) -> RegisterResponse:
    """Creates a user and returns their one and only initial API key.

    The key is only ever returned here, in plaintext, once — only its hash is stored.
    No email verification yet (tracked as tech debt); rate-limited per client IP.
    """
    existing = await user_repository.get_by_email(body.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = await user_repository.create(body.email, hash_password(body.password))

    api_key = generate_api_key()
    await api_key_repository.create(user.id, hash_api_key(api_key), api_key_display_prefix(api_key))

    return RegisterResponse(user_id=user.id, email=user.email, api_key=api_key)


@router.post(
    "/login", response_model=LoginResponse, dependencies=[Depends(enforce_auth_rate_limit)]
)
async def login(
    body: LoginRequest,
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
) -> LoginResponse:
    """Password login for the dashboard. Issues a JWT — API clients keep using API keys.

    Returns the same generic 401 whether the email is unknown or the password is wrong,
    so a caller can't use this to enumerate registered emails. Rate-limited per client IP.
    """
    user = await user_repository.get_by_email(body.email)
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    settings = get_settings()
    access_token = create_access_token(
        user.id,
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        expiry_minutes=settings.jwt_access_token_expiry_minutes,
    )
    return LoginResponse(access_token=access_token, user_id=user.id, email=user.email)
