import logging
import uuid

from app.domain.entities import Worker, WorkerStatus
from app.domain.repositories import WorkerRepository
from app.domain.worker_provisioner import ProvisioningError, WorkerProvisioner

logger = logging.getLogger("cloudworker.worker_manager")


class WorkerManager:
    """Worker lifecycle only: provision a worker for a job, or terminate one.

    Deliberately knows nothing about the jobs table or the queue — those are
    JobProcessor's concern. Depends only on WorkerRepository/WorkerProvisioner
    protocols, not SQLAlchemy or boto3, so it's testable against in-memory fakes.
    Used two ways: request-scoped from the API (cancel endpoint, one instance per
    request) and per-task from JobProcessor (one instance per concurrently
    processed job, each with its own session-backed WorkerRepository).
    """

    def __init__(
        self,
        worker_repository: WorkerRepository,
        provisioner: WorkerProvisioner,
        ssm_ready_timeout_seconds: float,
    ) -> None:
        self._worker_repository = worker_repository
        self._provisioner = provisioner
        self._ssm_ready_timeout_seconds = ssm_ready_timeout_seconds

    async def provision_worker(self, job_id: uuid.UUID) -> Worker:
        """Creates a worker, launches an instance, waits for SSM readiness, marks ready.

        On any failure, marks the worker failed and terminates any instance that was
        launched, then re-raises — the caller (JobProcessor) is responsible for failing
        the job itself, since this class doesn't touch the jobs table.
        """
        worker = await self._worker_repository.create(job_id)
        instance_id: str | None = None
        try:
            instance_id = await self._provisioner.launch(job_id)
            await self._worker_repository.mark_provisioning(worker.id, instance_id)

            ready = await self._provisioner.wait_until_ssm_ready(
                instance_id, self._ssm_ready_timeout_seconds
            )
            if not ready:
                raise ProvisioningError(
                    f"Instance {instance_id} did not register with SSM within "
                    f"{self._ssm_ready_timeout_seconds}s"
                )

            worker = await self._worker_repository.mark_ready(worker.id)
            logger.info("Worker ready for job %s (instance %s)", job_id, instance_id)
            return worker
        except Exception as exc:
            logger.warning("Provisioning failed for job %s: %s", job_id, exc)
            await self._worker_repository.mark_failed(worker.id, failure_reason=str(exc))
            if instance_id is not None:
                await self._provisioner.terminate(instance_id)
            raise

    async def terminate_worker_for_job(self, job_id: uuid.UUID) -> None:
        """Terminates the job's worker, if one exists and isn't already terminated/failed.

        Used both when a running job is cancelled and after a job finishes executing
        (success or failure) — the termination itself is identical either way.
        """
        worker = await self._worker_repository.get_by_job_id(job_id)
        if worker is None or worker.status in (WorkerStatus.TERMINATED, WorkerStatus.FAILED):
            return

        await self._worker_repository.mark_terminating(worker.id)
        if worker.instance_id is not None:
            await self._provisioner.terminate(worker.instance_id)
        await self._worker_repository.mark_terminated(worker.id)
