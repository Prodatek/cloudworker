import asyncio

from httpx import AsyncClient

from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.main import app
from tests.integration.conftest import auth_headers, register_user


async def _drain_queue() -> None:
    """Claims and discards any jobs left queued by other tests/prior runs, so this
    test's assertions aren't affected by unrelated state in the shared jobs table.
    """
    session_factory = app.state.db_session_factory
    while True:
        async with session_factory() as session:
            claimed = await SqlAlchemyJobRepository(session).claim_next_job()
        if claimed is None:
            break


async def test_claim_next_job_is_safe_under_concurrent_claimers(
    client: AsyncClient, unique_email: str
) -> None:
    await _drain_queue()

    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    job_count = 5
    created_ids = set()
    for i in range(job_count):
        response = await client.post(
            "/api/v1/jobs",
            json={"job_type": "shell", "payload": {"i": i}},
            headers=headers,
        )
        assert response.status_code == 201
        created_ids.add(response.json()["id"])

    session_factory = app.state.db_session_factory

    async def claim_once():
        async with session_factory() as session:
            return await SqlAlchemyJobRepository(session).claim_next_job()

    # More claimers than jobs, to prove the extra claimers safely get nothing back
    # instead of double-claiming or crashing.
    claimer_count = job_count + 3
    results = await asyncio.gather(*(claim_once() for _ in range(claimer_count)))

    claimed_jobs = [job for job in results if job is not None]
    claimed_ids = {str(job.id) for job in claimed_jobs}

    assert len(claimed_jobs) == job_count
    assert claimed_ids == created_ids
