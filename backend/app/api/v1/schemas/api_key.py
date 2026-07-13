import uuid
from datetime import datetime

from pydantic import BaseModel

from app.domain.entities import ApiKey


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_entity(cls, api_key: ApiKey) -> "ApiKeyResponse":
        return cls(
            id=api_key.id,
            prefix=api_key.prefix,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            revoked_at=api_key.revoked_at,
        )


class ApiKeyListResponse(BaseModel):
    api_keys: list[ApiKeyResponse]


class ApiKeyCreateResponse(ApiKeyResponse):
    api_key: str
    """The full key, in plaintext — only ever returned here, once."""
