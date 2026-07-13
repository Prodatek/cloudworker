import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities import ApiKey
from app.infrastructure.db.models import ApiKeyModel


def _to_entity(model: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=model.id,
        user_id=model.user_id,
        hashed_key=model.hashed_key,
        prefix=model.prefix,
        created_at=model.created_at,
        last_used_at=model.last_used_at,
        revoked_at=model.revoked_at,
    )


class SqlAlchemyApiKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: uuid.UUID, hashed_key: str, prefix: str) -> ApiKey:
        model = ApiKeyModel(user_id=user_id, hashed_key=hashed_key, prefix=prefix)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_entity(model)

    async def get_by_hashed_key(self, hashed_key: str) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKeyModel).where(ApiKeyModel.hashed_key == hashed_key)
        )
        model = result.scalar_one_or_none()
        return _to_entity(model) if model else None
