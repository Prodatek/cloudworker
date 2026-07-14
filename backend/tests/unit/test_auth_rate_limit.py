from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.deps import (
    get_api_key_repository,
    get_auth_rate_limiter,
    get_user_repository,
)
from app.core.rate_limit import FixedWindowRateLimiter
from app.main import app
from tests.unit.fakes import FakeApiKeyRepository, FakeUserRepository


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_user_repository] = lambda: FakeUserRepository()
    app.dependency_overrides[get_api_key_repository] = lambda: FakeApiKeyRepository()
    # One shared instance across requests within the test — a lambda re-invoked per
    # request (how FastAPI treats dependency_overrides) would hand out a fresh limiter
    # with a clean budget every time, never actually enforcing anything.
    rate_limiter = FixedWindowRateLimiter(max_attempts=2, window_seconds=60.0)
    app.dependency_overrides[get_auth_rate_limiter] = lambda: rate_limiter
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_api_key_repository, None)
        app.dependency_overrides.pop(get_auth_rate_limiter, None)


async def test_register_is_rate_limited_per_client(client: AsyncClient) -> None:
    for i in range(2):
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": f"user{i}@example.com", "password": "correct horse battery staple"},
        )
        assert response.status_code == 201

    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "user3@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 429


async def test_login_is_rate_limited_per_client(client: AsyncClient) -> None:
    for _ in range(2):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
        )
        assert response.status_code == 401  # under the limit, rejected for bad creds not 429

    response = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )

    assert response.status_code == 429
