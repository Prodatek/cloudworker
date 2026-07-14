import asyncio
import logging

from app.domain.repositories import RepositoryFactory
from app.domain.worker_provisioner import WorkerProvisioner
from app.infrastructure.metrics import JOBS_TOTAL, WORKERS_REAPED_TOTAL

logger = logging.getLogger("cloudworker.worker_reaper")


class WorkerReaper:
    """Guaranteed-cleanup safety net for workers the happy path never reaches.

    WorkerManager only terminates a worker when JobProcessor explicitly asks it to
    (job finished, job cancelled) — nothing recovers a worker whose owning process
    crashed mid-provisioning, or whose job hung past its execution timeout without the
    executor ever returning. This polls for workers stuck in a non-terminal status for
    too long, force-terminates their instance, marks them failed, and fails the
    associated job if it isn't already terminal — the same "mission" guarantee
    WorkerManager provides on the happy path, extended to crash/hang recovery.
    """

    def __init__(
        self,
        repository_factory: RepositoryFactory,
        provisioner: WorkerProvisioner,
        stale_after_seconds: float,
    ) -> None:
        self._repository_factory = repository_factory
        self._provisioner = provisioner
        self._stale_after_seconds = stale_after_seconds

    async def reap_once(self) -> int:
        """Reaps every currently-stale worker. Returns how many were reaped."""
        async with self._repository_factory() as repos:
            stale_workers = await repos.worker_repository.list_stale(self._stale_after_seconds)

        for worker in stale_workers:
            async with self._repository_factory() as repos:
                logger.warning(
                    "Reaping stale worker %s (job %s, status %s, instance %s)",
                    worker.id,
                    worker.job_id,
                    worker.status.value,
                    worker.instance_id,
                )
                if worker.instance_id is not None:
                    await self._provisioner.terminate(worker.instance_id)
                await repos.worker_repository.mark_failed(
                    worker.id,
                    failure_reason=(
                        f"Reaped: stuck in '{worker.status.value}' for longer than "
                        f"{self._stale_after_seconds}s"
                    ),
                )
                failed_job = await repos.job_repository.fail(
                    worker.job_id,
                    error_message="Worker was reaped after becoming stuck and unresponsive",
                )
                if failed_job is not None:
                    JOBS_TOTAL.labels(
                        job_type=failed_job.job_type.value, status=failed_job.status.value
                    ).inc()
                WORKERS_REAPED_TOTAL.inc()

        return len(stale_workers)

    async def run_forever(self, poll_interval_seconds: float) -> None:
        logger.info(
            "WorkerReaper starting poll loop (interval=%ss, stale_after=%ss)",
            poll_interval_seconds,
            self._stale_after_seconds,
        )
        while True:
            try:
                reaped = await self.reap_once()
                if reaped:
                    logger.info("Reaped %d stale worker(s)", reaped)
            except Exception as exc:
                logger.error("WorkerReaper.reap_once() failed: %s", exc, exc_info=exc)
            await asyncio.sleep(poll_interval_seconds)
