from httpx import AsyncClient

from app.domain.artifact_store import ArtifactKind, ArtifactRef
from app.main import app
from tests.integration.conftest import auth_headers, register_user
from tests.unit.fakes import FakeArtifactStore


async def test_get_job_artifacts_returns_presigned_urls(
    client: AsyncClient, unique_email: str
) -> None:
    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=headers,
    )
    job_id = create_response.json()["id"]

    fake_store = FakeArtifactStore(
        artifacts=[
            ArtifactRef(
                bucket="cloudworker-logs",
                key=f"jobs/{job_id}/cmd/inst/stdout",
                kind=ArtifactKind.LOG,
                size_bytes=10,
            ),
        ]
    )
    app.state.artifact_store = fake_store

    response = await client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body["artifacts"]) == 1
    artifact = body["artifacts"][0]
    assert artifact["kind"] == "log"
    assert artifact["size_bytes"] == 10
    assert artifact["url"].startswith("https://cloudworker-logs.s3.example.com/")
    assert artifact["expires_in_seconds"] > 0
    assert fake_store.presigned_url_calls == [
        ("cloudworker-logs", f"jobs/{job_id}/cmd/inst/stdout", artifact["expires_in_seconds"])
    ]


async def test_get_job_artifacts_404_for_missing_job(
    client: AsyncClient, unique_email: str
) -> None:
    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    response = await client.get(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/artifacts", headers=headers
    )

    assert response.status_code == 404


async def test_get_job_artifacts_503_when_not_configured(
    client: AsyncClient, unique_email: str
) -> None:
    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])
    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=headers,
    )
    job_id = create_response.json()["id"]

    app.state.artifact_store = None

    response = await client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=headers)

    assert response.status_code == 503
