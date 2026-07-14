import uuid
from datetime import UTC, datetime, timedelta

from app.domain.entities import JobStatus, WorkerStatus
from app.services.worker_reaper import WorkerReaper
from tests.unit.fakes import (
    FakeJobRepository,
    FakeWorkerProvisioner,
    FakeWorkerRepository,
    fake_repository_factory,
)


def _make_reaper(
    job_repository: FakeJobRepository,
    worker_repository: FakeWorkerRepository,
    provisioner: FakeWorkerProvisioner,
    stale_after_seconds: float = 60.0,
) -> WorkerReaper:
    return WorkerReaper(
        repository_factory=fake_repository_factory(job_repository, worker_repository),
        provisioner=provisioner,
        stale_after_seconds=stale_after_seconds,
    )


async def test_reap_once_terminates_and_fails_stale_provisioning_worker() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()  # RUNNING, so fail() can act on it

    worker = await worker_repository.create(job.id)
    await worker_repository.mark_provisioning(worker.id, "i-stale00000001")
    worker_repository.workers[worker.id].updated_at = datetime.now(UTC) - timedelta(seconds=120)

    reaper = _make_reaper(job_repository, worker_repository, provisioner, stale_after_seconds=60.0)
    reaped_count = await reaper.reap_once()

    assert reaped_count == 1
    reaped_worker = worker_repository.workers[worker.id]
    assert reaped_worker.status == WorkerStatus.FAILED
    assert reaped_worker.failure_reason is not None
    assert provisioner.terminated_instance_ids == ["i-stale00000001"]
    assert job_repository.jobs[job.id].status == JobStatus.FAILED


async def test_reap_once_ignores_fresh_workers() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()

    worker = await worker_repository.create(job.id)
    await worker_repository.mark_provisioning(worker.id, "i-fresh0000001")

    reaper = _make_reaper(job_repository, worker_repository, provisioner, stale_after_seconds=60.0)
    reaped_count = await reaper.reap_once()

    assert reaped_count == 0
    assert worker_repository.workers[worker.id].status == WorkerStatus.PROVISIONING
    assert provisioner.terminated_instance_ids == []
    assert job_repository.jobs[job.id].status == JobStatus.RUNNING


async def test_reap_once_ignores_workers_already_terminal() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()

    worker = await worker_repository.create(job.id)
    await worker_repository.mark_provisioning(worker.id, "i-done0000001")
    await worker_repository.mark_terminated(worker.id)
    worker_repository.workers[worker.id].updated_at = datetime.now(UTC) - timedelta(seconds=120)

    reaper = _make_reaper(job_repository, worker_repository, provisioner, stale_after_seconds=60.0)
    reaped_count = await reaper.reap_once()

    assert reaped_count == 0
    assert provisioner.terminated_instance_ids == []


async def test_reap_once_handles_worker_with_no_instance_id_yet() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()

    worker = await worker_repository.create(job.id)  # still PENDING, no instance_id
    worker_repository.workers[worker.id].updated_at = datetime.now(UTC) - timedelta(seconds=120)

    reaper = _make_reaper(job_repository, worker_repository, provisioner, stale_after_seconds=60.0)
    reaped_count = await reaper.reap_once()

    assert reaped_count == 1
    assert provisioner.terminated_instance_ids == []  # nothing to terminate
    assert worker_repository.workers[worker.id].status == WorkerStatus.FAILED
    assert job_repository.jobs[job.id].status == JobStatus.FAILED


async def test_run_forever_reaps_on_each_poll_until_cancelled() -> None:
    import asyncio

    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()
    worker = await worker_repository.create(job.id)
    await worker_repository.mark_provisioning(worker.id, "i-loop0000001")
    worker_repository.workers[worker.id].updated_at = datetime.now(UTC) - timedelta(seconds=120)

    reaper = _make_reaper(job_repository, worker_repository, provisioner, stale_after_seconds=60.0)
    task = asyncio.create_task(reaper.run_forever(poll_interval_seconds=0.01))
    try:
        for _ in range(100):
            if worker_repository.workers[worker.id].status == WorkerStatus.FAILED:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()

    assert worker_repository.workers[worker.id].status == WorkerStatus.FAILED


async def test_reap_once_is_a_no_op_when_nothing_is_stale() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()

    reaper = _make_reaper(job_repository, worker_repository, provisioner)
    reaped_count = await reaper.reap_once()

    assert reaped_count == 0


async def test_reap_once_uses_unique_job_id_correctly() -> None:
    # Guards against accidentally keying off worker.id instead of worker.job_id
    # when failing the associated job.
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()

    worker = await worker_repository.create(job.id)
    assert worker.id != job.id
    worker_repository.workers[worker.id].updated_at = datetime.now(UTC) - timedelta(seconds=120)

    reaper = _make_reaper(job_repository, worker_repository, provisioner, stale_after_seconds=60.0)
    await reaper.reap_once()

    assert job_repository.jobs[job.id].status == JobStatus.FAILED
    assert uuid.UUID(str(worker.job_id)) == job.id
