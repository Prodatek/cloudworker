import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from app.domain.entities import WorkerStatus
from app.domain.repositories import RepositoryBundle
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.models import WorkerModel
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.main import app
from app.services.worker_reaper import WorkerReaper
from tests.integration.conftest import auth_headers, register_user
from tests.unit.fakes import FakeWorkerProvisioner


async def _drain_queue() -> None:
    session_factory = app.state.db_session_factory
    while True:
        async with session_factory() as session:
            claimed = await SqlAlchemyJobRepository(session).claim_next_job()
        if claimed is None:
            break


def _repository_factory():
    session_factory = app.state.db_session_factory

    @asynccontextmanager
    async def factory() -> AsyncIterator[RepositoryBundle]:
        async with session_factory() as session:
            yield RepositoryBundle(
                job_repository=SqlAlchemyJobRepository(session),
                worker_repository=SqlAlchemyWorkerRepository(session),
            )

    return factory


async def _backdate_worker_updated_at(worker_id: uuid.UUID, seconds_ago: float) -> None:
    """Simulates a worker that's been stuck for a while, by directly rewriting
    updated_at — the SqlAlchemyWorkerRepository's own methods always set it to now().
    """
    session_factory = app.state.db_session_factory
    async with session_factory() as session:
        await session.execute(
            update(WorkerModel)
            .where(WorkerModel.id == worker_id)
            .values(updated_at=datetime.now(UTC) - timedelta(seconds=seconds_ago))
        )
        await session.commit()


async def test_reaper_terminates_and_fails_a_stale_provisioning_worker(
    client: AsyncClient, unique_email: str
) -> None:
    await _drain_queue()

    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=headers,
    )
    assert create_response.status_code == 201
    job_id = uuid.UUID(create_response.json()["id"])

    fake_provisioner = FakeWorkerProvisioner(ssm_ready=True)

    async with _repository_factory()() as repos:
        job = await repos.job_repository.claim_next_job()
        assert job is not None and job.id == job_id
        worker = await repos.worker_repository.create(job.id)
        worker = await repos.worker_repository.mark_provisioning(worker.id, "i-integration01")

    await _backdate_worker_updated_at(worker.id, seconds_ago=120)

    reaper = WorkerReaper(
        repository_factory=_repository_factory(),
        provisioner=fake_provisioner,
        stale_after_seconds=60.0,
    )
    reaped_count = await reaper.reap_once()

    assert reaped_count == 1
    assert fake_provisioner.terminated_instance_ids == ["i-integration01"]

    async with _repository_factory()() as repos:
        reaped_worker = await repos.worker_repository.get_by_job_id(job_id)
    assert reaped_worker is not None
    assert reaped_worker.status == WorkerStatus.FAILED
    assert reaped_worker.failure_reason is not None

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert get_response.json()["status"] == "failed"


async def test_reaper_leaves_a_fresh_provisioning_worker_alone(
    client: AsyncClient, unique_email: str
) -> None:
    await _drain_queue()

    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {"command": "echo hi"}},
        headers=headers,
    )
    job_id = uuid.UUID(create_response.json()["id"])

    fake_provisioner = FakeWorkerProvisioner(ssm_ready=True)

    async with _repository_factory()() as repos:
        job = await repos.job_repository.claim_next_job()
        assert job is not None
        worker = await repos.worker_repository.create(job.id)
        await repos.worker_repository.mark_provisioning(worker.id, "i-integration02")

    reaper = WorkerReaper(
        repository_factory=_repository_factory(),
        provisioner=fake_provisioner,
        stale_after_seconds=60.0,
    )
    reaped_count = await reaper.reap_once()

    assert reaped_count == 0
    assert fake_provisioner.terminated_instance_ids == []

    async with _repository_factory()() as repos:
        worker_after = await repos.worker_repository.get_by_job_id(job_id)
    assert worker_after is not None
    assert worker_after.status == WorkerStatus.PROVISIONING

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert get_response.json()["status"] == "running"
