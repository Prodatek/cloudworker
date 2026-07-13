import os

import pytest

# Integration tests need a real, reachable Postgres. Default to the port docker-compose
# exposes on localhost; override via DATABASE_URL when pointing at a CI service container.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://cloudworker:cloudworker@localhost:5432/cloudworker"
)

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
