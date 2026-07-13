import uuid

from httpx import AsyncClient

from app.domain.entities import WorkerStatus
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.main import app
from app.services.worker_manager import WorkerManager
from tests.integration.conftest import auth_headers, register_user
from tests.unit.fakes import FakeWorkerProvisioner


async def _drain_queue() -> None:
    """Claims and discards any jobs left queued by other tests/prior runs (same
    reasoning as test_job_queue_claim_concurrency.py's helper), so process_next_job()
    below is guaranteed to claim the job this test just created.
    """
    session_factory = app.state.db_session_factory
    while True:
        async with session_factory() as session:
            claimed = await SqlAlchemyJobRepository(session).claim_next_job()
        if claimed is None:
            break


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

    session_factory = app.state.db_session_factory
    async with session_factory() as session:
        manager = WorkerManager(
            job_repository=SqlAlchemyJobRepository(session),
            worker_repository=SqlAlchemyWorkerRepository(session),
            provisioner=fake_provisioner,
            ssm_ready_timeout_seconds=5,
        )
        claimed = await manager.process_next_job()
    assert claimed is True

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert get_response.json()["status"] == "running"

    cancel_response = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers)

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert len(fake_provisioner.terminated_instance_ids) == 1

    async with session_factory() as session:
        worker = await SqlAlchemyWorkerRepository(session).get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.TERMINATED


async def test_worker_manager_fails_job_when_provisioning_fails(
    client: AsyncClient, unique_email: str
) -> None:
    await _drain_queue()

    registration = await register_user(client, unique_email)
    headers = auth_headers(registration["api_key"])

    create_response = await client.post(
        "/api/v1/jobs",
        json={"job_type": "shell", "payload": {}},
        headers=headers,
    )
    job_id = uuid.UUID(create_response.json()["id"])

    fake_provisioner = FakeWorkerProvisioner(fail_launch=True)
    session_factory = app.state.db_session_factory
    async with session_factory() as session:
        manager = WorkerManager(
            job_repository=SqlAlchemyJobRepository(session),
            worker_repository=SqlAlchemyWorkerRepository(session),
            provisioner=fake_provisioner,
            ssm_ready_timeout_seconds=5,
        )
        await manager.process_next_job()

    get_response = await client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert get_response.json()["status"] == "failed"

    async with session_factory() as session:
        worker = await SqlAlchemyWorkerRepository(session).get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.FAILED
