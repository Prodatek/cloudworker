from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.deps import get_api_key_repository, get_auth_rate_limiter, get_user_repository
from app.core.rate_limit import FixedWindowRateLimiter
from app.infrastructure.security import hash_password
from app.main import app
from tests.unit.fakes import FakeApiKeyRepository, FakeUserRepository

# get_user_repository/get_api_key_repository are overridden with in-memory fakes, so
# these exercise the real routing/validation/status-code logic of the auth + api-keys
# endpoints (including get_current_user's dual API-key/JWT dispatch) without a database
# — FastAPI's dependency_overrides replaces the whole dependency callable, so the
# overridden ones' own Depends(get_session) sub-dependency is never invoked, meaning no
# app.state.db_engine/lifespan is needed either.


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, FakeUserRepository, FakeApiKeyRepository]]:
    user_repository = FakeUserRepository()
    api_key_repository = FakeApiKeyRepository()
    app.dependency_overrides[get_user_repository] = lambda: user_repository
    app.dependency_overrides[get_api_key_repository] = lambda: api_key_repository
    # A fresh, generously-limited rate limiter per test — these tests aren't testing rate
    # limiting itself (see test_auth_rate_limit.py) and `app` is a module-level singleton,
    # so without this override the real limiter's counters would leak across tests.
    rate_limiter = FixedWindowRateLimiter(max_attempts=1000, window_seconds=60.0)
    app.dependency_overrides[get_auth_rate_limiter] = lambda: rate_limiter
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, user_repository, api_key_repository
    finally:
        app.dependency_overrides.pop(get_user_repository, None)
        app.dependency_overrides.pop(get_api_key_repository, None)
        app.dependency_overrides.pop(get_auth_rate_limiter, None)


async def test_register_creates_user_and_returns_api_key(client) -> None:
    ac, _, _ = client

    response = await ac.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["api_key"].startswith("cw_live_")


async def test_login_succeeds_with_correct_password(client) -> None:
    ac, user_repository, _ = client
    user_repository.seed_user("bob@example.com", hash_password("correct password"))

    response = await ac.post(
        "/api/v1/auth/login", json={"email": "bob@example.com", "password": "correct password"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_rejects_wrong_password(client) -> None:
    ac, user_repository, _ = client
    user_repository.seed_user("bob@example.com", hash_password("correct password"))

    response = await ac.post(
        "/api/v1/auth/login", json={"email": "bob@example.com", "password": "wrong password"}
    )

    assert response.status_code == 401


async def test_login_rejects_unknown_email(client) -> None:
    ac, _, _ = client

    response = await ac.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )

    assert response.status_code == 401


async def test_jwt_from_login_authenticates_a_protected_endpoint(client) -> None:
    ac, user_repository, _ = client
    user_repository.seed_user("carol@example.com", hash_password("correct password"))

    login_response = await ac.post(
        "/api/v1/auth/login", json={"email": "carol@example.com", "password": "correct password"}
    )
    token = login_response.json()["access_token"]

    response = await ac.get("/api/v1/api-keys", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"api_keys": []}


async def test_api_key_still_authenticates_after_jwt_support_was_added(client) -> None:
    ac, _, _ = client
    register_response = await ac.post(
        "/api/v1/auth/register",
        json={"email": "dave@example.com", "password": "correct horse battery staple"},
    )
    api_key = register_response.json()["api_key"]

    response = await ac.get("/api/v1/api-keys", headers={"Authorization": f"Bearer {api_key}"})

    assert response.status_code == 200
    assert len(response.json()["api_keys"]) == 1


async def test_garbage_bearer_token_is_rejected(client) -> None:
    ac, _, _ = client

    response = await ac.get(
        "/api/v1/api-keys", headers={"Authorization": "Bearer not-a-real-token"}
    )

    assert response.status_code == 401


async def test_missing_authorization_header_is_rejected(client) -> None:
    ac, _, _ = client

    response = await ac.get("/api/v1/api-keys")

    assert response.status_code == 401


async def test_create_and_revoke_api_key_via_jwt_auth(client) -> None:
    ac, user_repository, _ = client
    user_repository.seed_user("erin@example.com", hash_password("correct password"))
    login_response = await ac.post(
        "/api/v1/auth/login", json={"email": "erin@example.com", "password": "correct password"}
    )
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    create_response = await ac.post("/api/v1/api-keys", headers=headers)
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["api_key"].startswith("cw_live_")
    assert created["revoked_at"] is None

    list_response = await ac.get("/api/v1/api-keys", headers=headers)
    assert len(list_response.json()["api_keys"]) == 1

    revoke_response = await ac.post(f"/api/v1/api-keys/{created['id']}/revoke", headers=headers)
    assert revoke_response.status_code == 200
    assert revoke_response.json()["revoked_at"] is not None

    second_revoke_response = await ac.post(
        f"/api/v1/api-keys/{created['id']}/revoke", headers=headers
    )
    assert second_revoke_response.status_code == 404
