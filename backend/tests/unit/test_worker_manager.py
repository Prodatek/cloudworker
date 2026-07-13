import uuid

import pytest

from app.domain.entities import WorkerStatus
from app.domain.worker_provisioner import ProvisioningError
from app.services.worker_manager import WorkerManager
from tests.unit.fakes import FakeWorkerProvisioner, FakeWorkerRepository


def _make_manager(
    worker_repository: FakeWorkerRepository,
    provisioner: FakeWorkerProvisioner,
    ssm_ready_timeout_seconds: float = 1.0,
) -> WorkerManager:
    return WorkerManager(
        worker_repository=worker_repository,
        provisioner=provisioner,
        ssm_ready_timeout_seconds=ssm_ready_timeout_seconds,
    )


async def test_provision_worker_reaches_ready_on_success() -> None:
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    manager = _make_manager(worker_repository, provisioner)
    job_id = uuid.uuid4()

    worker = await manager.provision_worker(job_id)

    assert worker.status == WorkerStatus.READY
    assert worker.instance_id is not None
    assert provisioner.launched_job_ids == [job_id]


async def test_provision_worker_raises_and_marks_failed_when_launch_raises() -> None:
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(fail_launch=True)
    manager = _make_manager(worker_repository, provisioner)
    job_id = uuid.uuid4()

    with pytest.raises(ProvisioningError):
        await manager.provision_worker(job_id)

    worker = await worker_repository.get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.FAILED
    assert provisioner.terminated_instance_ids == []  # never launched, nothing to terminate


async def test_provision_worker_terminates_instance_on_ssm_timeout() -> None:
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=False)
    manager = _make_manager(worker_repository, provisioner)
    job_id = uuid.uuid4()

    with pytest.raises(ProvisioningError):
        await manager.provision_worker(job_id)

    worker = await worker_repository.get_by_job_id(job_id)
    assert worker is not None
    assert worker.status == WorkerStatus.FAILED
    assert len(provisioner.terminated_instance_ids) == 1


async def test_terminate_worker_for_job_terminates_ready_worker() -> None:
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    manager = _make_manager(worker_repository, provisioner)
    job_id = uuid.uuid4()
    worker_before = await manager.provision_worker(job_id)

    await manager.terminate_worker_for_job(job_id)

    worker_after = await worker_repository.get_by_job_id(job_id)
    assert worker_after is not None
    assert worker_after.status == WorkerStatus.TERMINATED
    assert provisioner.terminated_instance_ids == [worker_before.instance_id]


async def test_terminate_worker_for_job_is_a_no_op_when_no_worker_exists() -> None:
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    manager = _make_manager(worker_repository, provisioner)

    await manager.terminate_worker_for_job(uuid.uuid4())

    assert provisioner.terminated_instance_ids == []


async def test_terminate_worker_for_job_is_a_no_op_when_already_terminated() -> None:
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    manager = _make_manager(worker_repository, provisioner)
    job_id = uuid.uuid4()
    await manager.provision_worker(job_id)
    await manager.terminate_worker_for_job(job_id)
    assert len(provisioner.terminated_instance_ids) == 1

    await manager.terminate_worker_for_job(job_id)

    assert len(provisioner.terminated_instance_ids) == 1
