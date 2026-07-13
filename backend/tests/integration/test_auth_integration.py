from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user


async def test_register_returns_user_and_api_key(client: AsyncClient, unique_email: str) -> None:
    body = await register_user(client, unique_email)

    assert body["email"] == unique_email
    assert body["api_key"].startswith("cw_live_")
    assert "user_id" in body


async def test_register_rejects_duplicate_email(client: AsyncClient, unique_email: str) -> None:
    await register_user(client, unique_email)

    response = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "another-password123"},
    )

    assert response.status_code == 409


async def test_jobs_endpoint_requires_authorization_header(client: AsyncClient) -> None:
    response = await client.get("/api/v1/jobs")

    assert response.status_code == 401


async def test_jobs_endpoint_rejects_bogus_api_key(client: AsyncClient) -> None:
    response = await client.get("/api/v1/jobs", headers=auth_headers("not-a-real-key"))

    assert response.status_code == 401
