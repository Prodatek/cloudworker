import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import get_api_key_repository, get_current_user
from app.api.v1.schemas.api_key import ApiKeyCreateResponse, ApiKeyListResponse, ApiKeyResponse
from app.domain.entities import User
from app.infrastructure.db.api_key_repository import SqlAlchemyApiKeyRepository
from app.infrastructure.security import (
    api_key_display_prefix,
    generate_api_key,
    hash_api_key,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
) -> ApiKeyListResponse:
    keys = await api_key_repository.list_for_user(current_user.id)
    return ApiKeyListResponse(api_keys=[ApiKeyResponse.from_entity(key) for key in keys])


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    current_user: User = Depends(get_current_user),
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
) -> ApiKeyCreateResponse:
    api_key = generate_api_key()
    record = await api_key_repository.create(
        current_user.id, hash_api_key(api_key), api_key_display_prefix(api_key)
    )
    return ApiKeyCreateResponse(
        id=record.id,
        prefix=record.prefix,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        api_key=api_key,
    )


@router.post("/{api_key_id}/revoke", response_model=ApiKeyResponse)
async def revoke_api_key(
    api_key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    api_key_repository: SqlAlchemyApiKeyRepository = Depends(get_api_key_repository),
) -> ApiKeyResponse:
    revoked = await api_key_repository.revoke(api_key_id, current_user.id)
    if revoked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )
    return ApiKeyResponse.from_entity(revoked)
