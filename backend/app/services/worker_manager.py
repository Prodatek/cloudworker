import asyncio
import logging
import uuid

from app.domain.entities import WorkerStatus
from app.domain.repositories import JobRepository, WorkerRepository
from app.domain.worker_provisioner import ProvisioningError, WorkerProvisioner

logger = logging.getLogger("cloudworker.worker_manager")


class WorkerManager:
    """Orchestrates claiming jobs and provisioning/tearing down their workers.

    Depends only on the JobRepository/WorkerRepository/WorkerProvisioner protocols, not
    on SQLAlchemy or boto3 directly, so it can be tested against in-memory fakes and
    reused unchanged whether it's driven by the standalone poll loop (run_forever) or a
    single call from the API (cancel_job_worker).
    """

    def __init__(
        self,
        job_repository: JobRepository,
        worker_repository: WorkerRepository,
        provisioner: WorkerProvisioner,
        ssm_ready_timeout_seconds: float,
    ) -> None:
        self._job_repository = job_repository
        self._worker_repository = worker_repository
        self._provisioner = provisioner
        self._ssm_ready_timeout_seconds = ssm_ready_timeout_seconds

    async def process_next_job(self) -> bool:
        """Claims one job and provisions a worker for it, if one is queued.

        Returns True if a job was claimed (regardless of whether provisioning
        succeeded), False if the queue was empty.
        """
        job = await self._job_repository.claim_next_job()
        if job is None:
            return False

        worker = await self._worker_repository.create(job.id)
        instance_id: str | None = None
        try:
            instance_id = await self._provisioner.launch(job.id)
            await self._worker_repository.mark_provisioning(worker.id, instance_id)

            ready = await self._provisioner.wait_until_ssm_ready(
                instance_id, self._ssm_ready_timeout_seconds
            )
            if not ready:
                raise ProvisioningError(
                    f"Instance {instance_id} did not register with SSM within "
                    f"{self._ssm_ready_timeout_seconds}s"
                )

            await self._worker_repository.mark_ready(worker.id)
            logger.info("Worker ready for job %s (instance %s)", job.id, instance_id)
        except Exception as exc:
            logger.warning("Provisioning failed for job %s: %s", job.id, exc)
            await self._worker_repository.mark_failed(worker.id, failure_reason=str(exc))
            if instance_id is not None:
                await self._provisioner.terminate(instance_id)
            await self._job_repository.fail(job.id, error_message=str(exc))

        return True

    async def cancel_job_worker(self, job_id: uuid.UUID) -> None:
        """Terminates the job's worker, if one exists and isn't already terminated/failed."""
        worker = await self._worker_repository.get_by_job_id(job_id)
        if worker is None or worker.status in (WorkerStatus.TERMINATED, WorkerStatus.FAILED):
            return

        await self._worker_repository.mark_terminating(worker.id)
        if worker.instance_id is not None:
            await self._provisioner.terminate(worker.instance_id)
        await self._worker_repository.mark_terminated(worker.id)

    async def run_forever(self, poll_interval_seconds: float) -> None:
        logger.info("WorkerManager starting poll loop (interval=%ss)", poll_interval_seconds)
        while True:
            claimed = await self.process_next_job()
            if not claimed:
                await asyncio.sleep(poll_interval_seconds)
