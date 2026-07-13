import uuid

from app.domain.entities import JobStatus, WorkerStatus
from app.services.worker_manager import WorkerManager
from tests.unit.fakes import FakeJobRepository, FakeWorkerProvisioner, FakeWorkerRepository


def _make_manager(
    job_repository: FakeJobRepository,
    worker_repository: FakeWorkerRepository,
    provisioner: FakeWorkerProvisioner,
    ssm_ready_timeout_seconds: float = 1.0,
) -> WorkerManager:
    return WorkerManager(
        job_repository=job_repository,
        worker_repository=worker_repository,
        provisioner=provisioner,
        ssm_ready_timeout_seconds=ssm_ready_timeout_seconds,
    )


async def test_process_next_job_returns_false_when_queue_empty() -> None:
    manager = _make_manager(FakeJobRepository(), FakeWorkerRepository(), FakeWorkerProvisioner())

    claimed = await manager.process_next_job()

    assert claimed is False


async def test_process_next_job_provisions_worker_to_ready_on_success() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    job = job_repository.seed_queued_job()
    manager = _make_manager(job_repository, worker_repository, provisioner)

    claimed = await manager.process_next_job()

    assert claimed is True
    assert job_repository.jobs[job.id].status == JobStatus.RUNNING
    worker = await worker_repository.get_by_job_id(job.id)
    assert worker is not None
    assert worker.status == WorkerStatus.READY
    assert worker.instance_id is not None
    assert provisioner.launched_job_ids == [job.id]


async def test_process_next_job_marks_failed_when_launch_raises() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(fail_launch=True)
    job = job_repository.seed_queued_job()
    manager = _make_manager(job_repository, worker_repository, provisioner)

    claimed = await manager.process_next_job()

    assert claimed is True
    assert job_repository.jobs[job.id].status == JobStatus.FAILED
    worker = await worker_repository.get_by_job_id(job.id)
    assert worker is not None
    assert worker.status == WorkerStatus.FAILED
    # Never launched, so nothing to terminate.
    assert provisioner.terminated_instance_ids == []


async def test_process_next_job_terminates_and_fails_on_ssm_timeout() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=False)
    job = job_repository.seed_queued_job()
    manager = _make_manager(job_repository, worker_repository, provisioner)

    claimed = await manager.process_next_job()

    assert claimed is True
    assert job_repository.jobs[job.id].status == JobStatus.FAILED
    worker = await worker_repository.get_by_job_id(job.id)
    assert worker is not None
    assert worker.status == WorkerStatus.FAILED
    assert len(provisioner.terminated_instance_ids) == 1


async def test_cancel_job_worker_terminates_ready_worker() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    job = job_repository.seed_queued_job()
    manager = _make_manager(job_repository, worker_repository, provisioner)
    await manager.process_next_job()
    worker_before = await worker_repository.get_by_job_id(job.id)
    assert worker_before is not None and worker_before.status == WorkerStatus.READY

    await manager.cancel_job_worker(job.id)

    worker_after = await worker_repository.get_by_job_id(job.id)
    assert worker_after is not None
    assert worker_after.status == WorkerStatus.TERMINATED
    assert provisioner.terminated_instance_ids == [worker_before.instance_id]


async def test_cancel_job_worker_is_a_no_op_when_no_worker_exists() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    manager = _make_manager(job_repository, worker_repository, provisioner)

    await manager.cancel_job_worker(uuid.uuid4())

    assert provisioner.terminated_instance_ids == []


async def test_cancel_job_worker_is_a_no_op_when_already_terminated() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    job = job_repository.seed_queued_job()
    manager = _make_manager(job_repository, worker_repository, provisioner)
    await manager.process_next_job()
    await manager.cancel_job_worker(job.id)
    assert len(provisioner.terminated_instance_ids) == 1

    await manager.cancel_job_worker(job.id)

    # No second termination call for an already-terminated worker.
    assert len(provisioner.terminated_instance_ids) == 1
