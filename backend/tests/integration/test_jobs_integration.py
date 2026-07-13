from httpx import AsyncClient

from tests.integration.conftest import auth_headers, register_user


async def test_create_get_list_and_cancel_job(client: AsyncClient, unique_email: str) -> None:
    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=headers,
    )
    assert create_response.status_code == 201
    job = create_response.json()
    assert job["status"] == "queued"
    assert job["payload"] == {"command": "echo hi"}

    get_response = await client.get(f"/api/v1/jobs/{job['id']}", headers=headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == job["id"]

    list_response = await client.get("/api/v1/jobs", headers=headers)
    assert list_response.status_code == 200
    listed_ids = [j["id"] for j in list_response.json()["jobs"]]
    assert job["id"] in listed_ids

    cancel_response = await client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"

    second_cancel_response = await client.post(f"/api/v1/jobs/{job['id']}/cancel", headers=headers)
    assert second_cancel_response.status_code == 409


async def test_get_job_not_found_returns_404(client: AsyncClient, unique_email: str) -> None:
    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    response = await client.get(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000", headers=headers
    )

    assert response.status_code == 404


async def test_user_cannot_see_another_users_job(client: AsyncClient, unique_email: str) -> None:
    owner = await register_user(client, unique_email)
    owner_headers = auth_headers(owner["api_key"])
    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=owner_headers,
    )
    job_id = create_response.json()["id"]

    other_email = f"other-{unique_email}"
    other = await register_user(client, other_email)
    other_headers = auth_headers(other["api_key"])

    response = await client.get(f"/api/v1/jobs/{job_id}", headers=other_headers)

    assert response.status_code == 404


async def test_create_shell_job_without_command_is_rejected(
    client: AsyncClient, unique_email: str
) -> None:
    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {}},
        headers=headers,
    )

    assert response.status_code == 422
