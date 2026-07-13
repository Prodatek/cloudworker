from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import get_api_key_repository, get_user_repository
from app.api.v1.schemas.auth import RegisterRequest, RegisterResponse
from app.infrastructure.db.api_key_repository import SqlAlchemyApiKeyRepository
from app.infrastructure.db.user_repository import SqlAlchemyUserRepository
from app.infrastructure.security import (
    api_key_display_prefix,
    generate_api_key,
    hash_api_key,
    hash_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    user_repository: SqlAlchemyUserRepository = Depends(get_user_repository),
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
) -> RegisterResponse:
    """Creates a user and returns their one and only initial API key.

    The key is only ever returned here, in plaintext, once — only its hash is stored.
    No email verification / rate limiting yet (tracked as tech debt).
    """
    existing = await user_repository.get_by_email(body.email)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = await user_repository.create(body.email, hash_password(body.password))

    api_key = generate_api_key()
    await api_key_repository.create(user.id, hash_api_key(api_key), api_key_display_prefix(api_key))

    return RegisterResponse(user_id=user.id, email=user.email, api_key=api_key)
