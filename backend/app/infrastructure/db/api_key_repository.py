import uuid
from datetime import UTC, datetime

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

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        result = await self._session.execute(
            select(ApiKeyModel)
            .where(ApiKeyModel.user_id == user_id)
            .order_by(ApiKeyModel.created_at.desc())
        )
        return [_to_entity(model) for model in result.scalars().all()]

    async def revoke(self, api_key_id: uuid.UUID, user_id: uuid.UUID) -> ApiKey | None:
        result = await self._session.execute(
            select(ApiKeyModel).where(ApiKeyModel.id == api_key_id, ApiKeyModel.user_id == user_id)
        )
        model = result.scalar_one_or_none()
        if model is None or model.revoked_at is not None:
            return None
        model.revoked_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_entity(model)
