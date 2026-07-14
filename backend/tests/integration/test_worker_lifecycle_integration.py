import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from httpx import AsyncClient

from app.domain.entities import JobType, WorkerStatus
from app.domain.repositories import RepositoryBundle
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.main import app
from app.services.job_processor import JobProcessor
from app.services.worker_manager import WorkerManager
from tests.integration.conftest import auth_headers, register_user
from tests.unit.fakes import FakeJobExecutor, FakeWorkerProvisioner


async def _drain_queue() -> None:
    """Claims and discards any jobs left queued by other tests/prior runs (same
    reasoning as test_job_queue_claim_concurrency.py's helper), so claim_next_job()
    below is guaranteed to claim the job this test just created.
    """
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


async def test_worker_manager_provisions_and_http_cancel_terminates_worker(
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

    # Wire a fake provisioner in for this test so the HTTP cancel path below exercises
    # real WorkerManager/repository code without needing real (or moto-mocked) AWS.
    fake_provisioner = FakeWorkerProvisioner(ssm_ready=True)
    app.state.worker_provisioner = fake_provisioner

    async with _repository_factory()() as repos:
        job = await repos.job_repository.claim_next_job()
        assert job is not None and job.id == job_id
        worker_manager = WorkerManager(
            worker_repository=repos.worker_repository,
            provisioner=fake_provisioner,
            ssm_ready_timeout_seconds=5,
        )
        await worker_manager.provision_worker(job.id)

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert get_response.json()["status"] == "running"

    cancel_response = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers)

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert len(fake_provisioner.terminated_instance_ids) == 1

    async with _repository_factory()() as repos:
        worker = await repos.worker_repository.get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.TERMINATED


async def test_job_processor_executes_and_completes_shell_job(
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
    fake_executor = FakeJobExecutor(succeed=True)
    processor = JobProcessor(
        repository_factory=_repository_factory(),
        provisioner=fake_provisioner,
        executors={JobType.SHELL: fake_executor},
        ssm_ready_timeout_seconds=5,
        job_execution_timeout_seconds=5,
        max_concurrent_jobs=1,
    )

    async with _repository_factory()() as repos:
        job = await repos.job_repository.claim_next_job()
    assert job is not None and job.id == job_id

    await processor._run_job(job)  # noqa: SLF001 - deterministic single-job run, no polling

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    body = get_response.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"exit_code": 0}

    async with _repository_factory()() as repos:
        worker = await repos.worker_repository.get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.TERMINATED
    assert len(fake_executor.executed) == 1
    executed_job_id, executed_command, executed_instance_id = fake_executor.executed[0]
    assert executed_job_id == job_id
    assert executed_command == "echo hi"
    assert executed_instance_id == worker.instance_id


async def test_job_processor_fails_job_when_provisioning_fails(
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

    fake_provisioner = FakeWorkerProvisioner(fail_launch=True)
    fake_executor = FakeJobExecutor()
    processor = JobProcessor(
        repository_factory=_repository_factory(),
        provisioner=fake_provisioner,
        executors={JobType.SHELL: fake_executor},
        ssm_ready_timeout_seconds=5,
        job_execution_timeout_seconds=5,
        max_concurrent_jobs=1,
    )

    async with _repository_factory()() as repos:
        job = await repos.job_repository.claim_next_job()
    assert job is not None

    await processor._run_job(job)  # noqa: SLF001

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert get_response.json()["status"] == "failed"
    assert fake_executor.executed == []

    async with _repository_factory()() as repos:
        worker = await repos.worker_repository.get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.FAILED
