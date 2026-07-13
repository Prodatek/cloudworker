from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user


async def test_login_with_registered_credentials_returns_working_jwt(
    client: AsyncClient, unique_email: str
) -> None:
    password = "correct horse battery staple"
    await register_user(client, unique_email, password)

    login_response = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": password}
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    # Prove the JWT actually authenticates a real endpoint end-to-end, same as an API key.
    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=auth_headers(token),
    )
    assert create_response.status_code == 201


async def test_login_rejects_wrong_password(client: AsyncClient, unique_email: str) -> None:
    await register_user(client, unique_email, "correct horse battery staple")

    response = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": "wrong password"}
    )

    assert response.status_code == 401


async def test_api_key_and_jwt_authenticate_as_the_same_user(
    client: AsyncClient, unique_email: str
) -> None:
    password = "correct horse battery staple"
    registration = await register_user(client, unique_email, password)

    login_response = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": password}
    )
    jwt_token = login_response.json()["access_token"]

    via_api_key = await client.get("/api/v1/jobs", headers=auth_headers(registration["api_key"]))
    via_jwt = await client.get("/api/v1/jobs", headers=auth_headers(jwt_token))

    assert via_api_key.status_code == 200
    assert via_jwt.status_code == 200


async def test_create_list_and_revoke_api_keys_over_http(
    client: AsyncClient, unique_email: str
) -> None:
    password = "correct horse battery staple"
    registration = await register_user(client, unique_email, password)
    login_response = await client.post(
        "/api/v1/auth/login", json={"email": unique_email, "password": password}
    )
    headers = auth_headers(login_response.json()["access_token"])

    list_response = await client.get("/api/v1/api-keys", headers=headers)
    assert list_response.status_code == 200
    # The one issued at registration should already be listed.
    assert len(list_response.json()["api_keys"]) == 1

    create_response = await client.post("/api/v1/api-keys", headers=headers)
    assert create_response.status_code == 201
    new_key = create_response.json()

    list_after_create = await client.get("/api/v1/api-keys", headers=headers)
    assert len(list_after_create.json()["api_keys"]) == 2

    revoke_response = await client.post(f"/api/v1/api-keys/{new_key['id']}/revoke", headers=headers)
    assert revoke_response.status_code == 200
    assert revoke_response.json()["revoked_at"] is not None

    # A revoked key can no longer authenticate.
    revoked_key_response = await client.get(
        "/api/v1/jobs", headers=auth_headers(new_key["api_key"])
    )
    assert revoked_key_response.status_code == 401

    # But the original registration key still works — revoking one key doesn't
    # affect others.
    original_key_response = await client.get(
        "/api/v1/jobs", headers=auth_headers(registration["api_key"])
    )
    assert original_key_response.status_code == 200
