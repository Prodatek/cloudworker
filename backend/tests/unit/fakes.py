import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.domain.artifact_store import ArtifactRef
from app.domain.entities import ApiKey, Job, JobStatus, JobType, User, Worker, WorkerStatus
from app.domain.job_executor import JobExecutionResult
from app.domain.repositories import RepositoryBundle
from app.domain.worker_provisioner import ProvisioningError


class FakeUserRepository:
    """In-memory UserRepository for testing auth endpoints without a real database."""

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}

    def seed_user(self, email: str, hashed_password: str) -> User:
        now = datetime.now(UTC)
        user = User(id=uuid.uuid4(), email=email, hashed_password=hashed_password, created_at=now)
        self.users[user.id] = user
        return user

    async def create(self, email: str, hashed_password: str) -> User:
        return self.seed_user(email, hashed_password)

    async def get_by_email(self, email: str) -> User | None:
        for user in self.users.values():
            if user.email == email:
                return user
        return None

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.users.get(user_id)


class FakeApiKeyRepository:
    """In-memory ApiKeyRepository for testing auth endpoints without a real database."""

    def __init__(self) -> None:
        self.keys: dict[uuid.UUID, ApiKey] = {}

    async def create(self, user_id: uuid.UUID, hashed_key: str, prefix: str) -> ApiKey:
        now = datetime.now(UTC)
        key = ApiKey(
            id=uuid.uuid4(), user_id=user_id, hashed_key=hashed_key, prefix=prefix, created_at=now
        )
        self.keys[key.id] = key
        return key

    async def get_by_hashed_key(self, hashed_key: str) -> ApiKey | None:
        for key in self.keys.values():
            if key.hashed_key == hashed_key:
                return key
        return None

    async def list_for_user(self, user_id: uuid.UUID) -> list[ApiKey]:
        return sorted(
            (key for key in self.keys.values() if key.user_id == user_id),
            key=lambda key: key.created_at,
            reverse=True,
        )

    async def revoke(self, api_key_id: uuid.UUID, user_id: uuid.UUID) -> ApiKey | None:
        key = self.keys.get(api_key_id)
        if key is None or key.user_id != user_id or key.revoked_at is not None:
            return None
        key.revoked_at = datetime.now(UTC)
        return key


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

    async def complete(self, job_id: uuid.UUID, result: dict) -> Job | None:
        job = self.jobs.get(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return None
        job.status = JobStatus.SUCCEEDED
        job.result = result
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


class FakeJobExecutor:
    """Configurable fake JobExecutor recording calls for assertions.

    `delay_seconds` lets concurrency tests prove two jobs actually overlap in time,
    rather than one finishing before the other starts.
    """

    def __init__(
        self,
        succeed: bool = True,
        raise_error: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self.succeed = succeed
        self.raise_error = raise_error
        self.delay_seconds = delay_seconds
        self.executed: list[tuple[uuid.UUID, str, str]] = []
        self._active = 0
        self.max_concurrent_observed = 0

    async def execute(self, job: Job, instance_id: str) -> JobExecutionResult:
        self._active += 1
        self.max_concurrent_observed = max(self.max_concurrent_observed, self._active)
        try:
            command_or_script = str(job.payload.get("command") or job.payload.get("script") or "")
            self.executed.append((job.id, command_or_script, instance_id))
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if self.raise_error:
                raise RuntimeError("simulated execution transport failure")
            if self.succeed:
                return JobExecutionResult(succeeded=True, exit_code=0, result={"exit_code": 0})
            return JobExecutionResult(
                succeeded=False, exit_code=1, error_message="command exited non-zero"
            )
        finally:
            self._active -= 1


class FakeArtifactStore:
    """Configurable fake ArtifactStore recording calls for assertions."""

    def __init__(self, artifacts: list[ArtifactRef] | None = None) -> None:
        self.artifacts = artifacts or []
        self.presigned_url_calls: list[tuple[str, str, int]] = []

    async def list_job_artifacts(self, job_id: uuid.UUID) -> list[ArtifactRef]:
        return self.artifacts

    async def generate_presigned_url(self, bucket: str, key: str, expires_in_seconds: int) -> str:
        self.presigned_url_calls.append((bucket, key, expires_in_seconds))
        return f"https://{bucket}.s3.example.com/{key}?expires={expires_in_seconds}"


def fake_repository_factory(
    job_repository: FakeJobRepository, worker_repository: FakeWorkerRepository
):
    """Builds a RepositoryFactory-shaped callable over the given fakes.

    Unlike the real SQLAlchemy-backed factory, this doesn't open a new session per
    call — it just re-wraps the same two fake repository instances each time, which is
    exactly what tests want: all "concurrent tasks" observe and mutate the same
    in-memory state.
    """

    @asynccontextmanager
    async def factory() -> AsyncIterator[RepositoryBundle]:
        yield RepositoryBundle(job_repository=job_repository, worker_repository=worker_repository)

    return factory
