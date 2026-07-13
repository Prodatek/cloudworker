import asyncio

import pytest

from app.domain.entities import JobStatus, JobType, WorkerStatus
from app.services.job_processor import JobProcessor
from tests.unit.fakes import (
    FakeJobExecutor,
    FakeJobRepository,
    FakeWorkerProvisioner,
    FakeWorkerRepository,
    fake_repository_factory,
)


def _make_processor(
    job_repository: FakeJobRepository,
    worker_repository: FakeWorkerRepository,
    provisioner: FakeWorkerProvisioner,
    executor: FakeJobExecutor,
    max_concurrent_jobs: int = 5,
) -> JobProcessor:
    return JobProcessor(
        repository_factory=fake_repository_factory(job_repository, worker_repository),
        provisioner=provisioner,
        executors={JobType.SHELL: executor},
        ssm_ready_timeout_seconds=1.0,
        job_execution_timeout_seconds=5.0,
        max_concurrent_jobs=max_concurrent_jobs,
    )


async def _run_briefly(processor: JobProcessor, duration: float = 0.3) -> None:
    task = asyncio.create_task(processor.run_forever(poll_interval_seconds=0.01))
    await asyncio.sleep(duration)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_job_completes_shell_job_end_to_end() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    executor = FakeJobExecutor(succeed=True)
    job = job_repository.seed_queued_job()
    job.payload = {"command": "echo hi"}
    processor = _make_processor(job_repository, worker_repository, provisioner, executor)

    await _run_briefly(processor)

    assert job_repository.jobs[job.id].status == JobStatus.SUCCEEDED
    assert job_repository.jobs[job.id].result == {"exit_code": 0}
    worker = await worker_repository.get_by_job_id(job.id)
    assert worker is not None
    assert worker.status == WorkerStatus.TERMINATED
    assert len(executor.executed) == 1
    assert executor.executed[0][:2] == (job.id, "echo hi")


async def test_run_job_fails_job_when_execution_reports_failure() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    executor = FakeJobExecutor(succeed=False)
    job = job_repository.seed_queued_job()
    job.payload = {"command": "exit 1"}
    processor = _make_processor(job_repository, worker_repository, provisioner, executor)

    await _run_briefly(processor)

    assert job_repository.jobs[job.id].status == JobStatus.FAILED
    worker = await worker_repository.get_by_job_id(job.id)
    assert worker is not None
    assert worker.status == WorkerStatus.TERMINATED


async def test_run_job_fails_job_when_provisioning_fails_without_executing() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(fail_launch=True)
    executor = FakeJobExecutor()
    job = job_repository.seed_queued_job()
    job.payload = {"command": "echo hi"}
    processor = _make_processor(job_repository, worker_repository, provisioner, executor)

    await _run_briefly(processor)

    assert job_repository.jobs[job.id].status == JobStatus.FAILED
    assert executor.executed == []


async def test_run_job_fails_non_shell_job_type_without_provisioning() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner()
    executor = FakeJobExecutor()
    job = job_repository.seed_queued_job(job_type=JobType.BROWSER)
    processor = _make_processor(job_repository, worker_repository, provisioner, executor)

    await _run_briefly(processor)

    assert job_repository.jobs[job.id].status == JobStatus.FAILED
    assert provisioner.launched_job_ids == []
    assert executor.executed == []


async def test_run_job_routes_browser_jobs_to_their_own_executor() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    shell_executor = FakeJobExecutor(succeed=True)
    browser_executor = FakeJobExecutor(succeed=True)
    job = job_repository.seed_queued_job(job_type=JobType.BROWSER)
    job.payload = {"script": "page.goto('https://example.com')"}
    processor = JobProcessor(
        repository_factory=fake_repository_factory(job_repository, worker_repository),
        provisioner=provisioner,
        executors={JobType.SHELL: shell_executor, JobType.BROWSER: browser_executor},
        ssm_ready_timeout_seconds=1.0,
        job_execution_timeout_seconds=5.0,
        max_concurrent_jobs=5,
    )

    await _run_briefly(processor)

    assert job_repository.jobs[job.id].status == JobStatus.SUCCEEDED
    assert shell_executor.executed == []
    assert len(browser_executor.executed) == 1
    assert browser_executor.executed[0][:2] == (job.id, "page.goto('https://example.com')")


async def test_multiple_jobs_are_processed_concurrently() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    executor = FakeJobExecutor(succeed=True, delay_seconds=0.2)
    for _ in range(2):
        job = job_repository.seed_queued_job()
        job.payload = {"command": "sleep 1"}
    processor = _make_processor(
        job_repository, worker_repository, provisioner, executor, max_concurrent_jobs=2
    )

    await _run_briefly(processor, duration=0.4)

    assert executor.max_concurrent_observed == 2
    assert all(job.status == JobStatus.SUCCEEDED for job in job_repository.jobs.values())


async def test_max_concurrent_jobs_bounds_concurrency() -> None:
    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    provisioner = FakeWorkerProvisioner(ssm_ready=True)
    executor = FakeJobExecutor(succeed=True, delay_seconds=0.15)
    for _ in range(3):
        job = job_repository.seed_queued_job()
        job.payload = {"command": "sleep 1"}
    processor = _make_processor(
        job_repository, worker_repository, provisioner, executor, max_concurrent_jobs=1
    )

    await _run_briefly(processor, duration=0.5)

    assert executor.max_concurrent_observed == 1
