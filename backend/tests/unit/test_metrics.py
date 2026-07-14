import uuid

from prometheus_client import generate_latest

from app.domain.entities import JobType
from app.infrastructure.metrics import (
    JOB_EXECUTION_SECONDS,
    JOBS_TOTAL,
    WORKER_PROVISIONING_SECONDS,
    WORKERS_REAPED_TOTAL,
)
from app.services.job_processor import JobProcessor
from app.services.worker_manager import WorkerManager
from app.services.worker_reaper import WorkerReaper
from tests.unit.fakes import (
    FakeJobExecutor,
    FakeJobRepository,
    FakeWorkerProvisioner,
    FakeWorkerRepository,
    fake_repository_factory,
)

# Metrics live on prometheus_client's process-global default registry, so tests read the
# exposition text directly rather than poking at Counter/Histogram internals, and compare
# before/after snapshots (delta) instead of absolute values — the registry is shared
# across the whole test session, other tests may have already incremented these.


def _metric_value(metric_name: str, **labels: str) -> float:
    text = generate_latest().decode()
    for line in text.splitlines():
        if line.startswith("#") or not line.startswith(metric_name):
            continue
        rest = line[len(metric_name) :]
        if not (rest.startswith("{") or rest.startswith(" ")):
            continue  # e.g. skip metric_name_bucket when looking for metric_name
        if labels:
            if not rest.startswith("{"):
                continue
            if not all(f'{k}="{v}"' in rest for k, v in labels.items()):
                continue
        elif rest.startswith("{"):
            continue
        return float(line.rsplit(" ", 1)[-1])
    return 0.0


async def test_provision_worker_observes_provisioning_seconds() -> None:
    before = _metric_value("cloudworker_worker_provisioning_seconds_count")

    manager = WorkerManager(
        worker_repository=FakeWorkerRepository(),
        provisioner=FakeWorkerProvisioner(ssm_ready=True),
        ssm_ready_timeout_seconds=1.0,
    )
    await manager.provision_worker(uuid.uuid4())

    after = _metric_value("cloudworker_worker_provisioning_seconds_count")
    assert after == before + 1


async def test_job_processor_records_jobs_total_and_execution_seconds_on_success() -> None:
    before_total = _metric_value("cloudworker_jobs_total", job_type="shell", status="succeeded")
    before_exec = _metric_value("cloudworker_job_execution_seconds_count", job_type="shell")

    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    job = job_repository.seed_queued_job(job_type=JobType.SHELL)
    job.payload = {"command": "echo hi"}
    processor = JobProcessor(
        repository_factory=fake_repository_factory(job_repository, worker_repository),
        provisioner=FakeWorkerProvisioner(ssm_ready=True),
        executors={JobType.SHELL: FakeJobExecutor(succeed=True)},
        ssm_ready_timeout_seconds=1.0,
        job_execution_timeout_seconds=5.0,
        max_concurrent_jobs=5,
    )

    claimed = await job_repository.claim_next_job()
    assert claimed is not None
    await processor._run_job(claimed)

    after_total = _metric_value("cloudworker_jobs_total", job_type="shell", status="succeeded")
    after_exec = _metric_value("cloudworker_job_execution_seconds_count", job_type="shell")
    assert after_total == before_total + 1
    assert after_exec == before_exec + 1


async def test_job_processor_records_jobs_total_failed_when_unsupported_job_type() -> None:
    before = _metric_value("cloudworker_jobs_total", job_type="browser", status="failed")

    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    job_repository.seed_queued_job(job_type=JobType.BROWSER)
    processor = JobProcessor(
        repository_factory=fake_repository_factory(job_repository, worker_repository),
        provisioner=FakeWorkerProvisioner(),
        executors={},
        ssm_ready_timeout_seconds=1.0,
        job_execution_timeout_seconds=5.0,
        max_concurrent_jobs=5,
    )

    claimed = await job_repository.claim_next_job()
    assert claimed is not None
    await processor._run_job(claimed)

    after = _metric_value("cloudworker_jobs_total", job_type="browser", status="failed")
    assert after == before + 1


async def test_worker_reaper_increments_workers_reaped_total() -> None:
    from datetime import UTC, datetime, timedelta

    before = _metric_value("cloudworker_workers_reaped_total")

    job_repository = FakeJobRepository()
    worker_repository = FakeWorkerRepository()
    job = job_repository.seed_queued_job()
    await job_repository.claim_next_job()
    worker = await worker_repository.create(job.id)
    await worker_repository.mark_provisioning(worker.id, "i-metrics0001")
    worker_repository.workers[worker.id].updated_at = datetime.now(UTC) - timedelta(seconds=999)

    reaper = WorkerReaper(
        repository_factory=fake_repository_factory(job_repository, worker_repository),
        provisioner=FakeWorkerProvisioner(),
        stale_after_seconds=60.0,
    )
    await reaper.reap_once()

    after = _metric_value("cloudworker_workers_reaped_total")
    assert after == before + 1


def test_metric_names_are_registered() -> None:
    text = generate_latest().decode()
    assert "cloudworker_jobs_total" in text
    assert "cloudworker_worker_provisioning_seconds" in text
    assert "cloudworker_job_execution_seconds" in text
    assert "cloudworker_workers_reaped_total" in text


def test_histograms_are_exported_objects() -> None:
    # Sanity check the module exposes the objects other services import and call
    # .observe()/.inc() on directly (see worker_manager.py, job_processor.py, worker_reaper.py).
    assert JOB_EXECUTION_SECONDS is not None
    assert WORKER_PROVISIONING_SECONDS is not None
    assert JOBS_TOTAL is not None
    assert WORKERS_REAPED_TOTAL is not None
