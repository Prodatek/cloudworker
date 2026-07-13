import uuid
from datetime import UTC, datetime

from app.domain.entities import Job, JobStatus, JobType, Worker, WorkerStatus
from app.domain.worker_provisioner import ProvisioningError


class FakeJobRepository:
    """In-memory JobRepository for testing WorkerManager without a real database."""

    def __init__(self) -> None:
        self.jobs: dict[uuid.UUID, Job] = {}

    def seed_queued_job(self, job_type: JobType = JobType.SHELL) -> Job:
        now = datetime.now(UTC)
        job = Job(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            job_type=job_type,
            status=JobStatus.QUEUED,
            payload={},
            created_at=now,
            updated_at=now,
        )
        self.jobs[job.id] = job
        return job

    async def claim_next_job(self) -> Job | None:
        for job in sorted(self.jobs.values(), key=lambda j: j.created_at):
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.RUNNING
                return job
        return None

    async def fail(self, job_id: uuid.UUID, error_message: str) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return None
        job.status = JobStatus.FAILED
        job.error_message = error_message
        return job

    async def cancel(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.user_id != user_id or not job.is_cancellable:
            return None
        job.status = JobStatus.CANCELLED
        return job


class FakeWorkerRepository:
    """In-memory WorkerRepository for testing WorkerManager without a real database."""

    def __init__(self) -> None:
        self.workers: dict[uuid.UUID, Worker] = {}

    async def create(self, job_id: uuid.UUID) -> Worker:
        now = datetime.now(UTC)
        worker = Worker(
            id=uuid.uuid4(),
            job_id=job_id,
            status=WorkerStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        self.workers[worker.id] = worker
        return worker

    async def get_by_job_id(self, job_id: uuid.UUID) -> Worker | None:
        for worker in self.workers.values():
            if worker.job_id == job_id:
                return worker
        return None

    async def mark_provisioning(self, worker_id: uuid.UUID, instance_id: str) -> Worker:
        worker = self.workers[worker_id]
        worker.status = WorkerStatus.PROVISIONING
        worker.instance_id = instance_id
        return worker

    async def mark_ready(self, worker_id: uuid.UUID) -> Worker:
        worker = self.workers[worker_id]
        worker.status = WorkerStatus.READY
        worker.ready_at = datetime.now(UTC)
        return worker

    async def mark_terminating(self, worker_id: uuid.UUID) -> Worker:
        worker = self.workers[worker_id]
        worker.status = WorkerStatus.TERMINATING
        return worker

    async def mark_terminated(self, worker_id: uuid.UUID) -> Worker:
        worker = self.workers[worker_id]
        worker.status = WorkerStatus.TERMINATED
        worker.terminated_at = datetime.now(UTC)
        return worker

    async def mark_failed(self, worker_id: uuid.UUID, failure_reason: str) -> Worker:
        worker = self.workers[worker_id]
        worker.status = WorkerStatus.FAILED
        worker.failure_reason = failure_reason
        return worker


class FakeWorkerProvisioner:
    """Configurable fake WorkerProvisioner recording calls for assertions."""

    def __init__(
        self,
        fail_launch: bool = False,
        ssm_ready: bool = True,
    ) -> None:
        self.fail_launch = fail_launch
        self.ssm_ready = ssm_ready
        self.launched_job_ids: list[uuid.UUID] = []
        self.terminated_instance_ids: list[str] = []
        self._next_instance_number = 1

    async def launch(self, job_id: uuid.UUID) -> str:
        if self.fail_launch:
            raise ProvisioningError("simulated launch failure")
        self.launched_job_ids.append(job_id)
        instance_id = f"i-fake{self._next_instance_number:08d}"
        self._next_instance_number += 1
        return instance_id

    async def wait_until_ssm_ready(self, instance_id: str, timeout_seconds: float) -> bool:
        return self.ssm_ready

    async def terminate(self, instance_id: str) -> None:
        self.terminated_instance_ids.append(instance_id)
