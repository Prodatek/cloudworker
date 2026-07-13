import asyncio
import logging

from app.domain.entities import Job, JobType
from app.domain.job_executor import JobExecutor
from app.domain.repositories import RepositoryBundle, RepositoryFactory
from app.domain.worker_provisioner import WorkerProvisioner
from app.services.worker_manager import WorkerManager

logger = logging.getLogger("cloudworker.job_processor")

# Slack added on top of the executor's own execution timeout before JobProcessor gives
# up waiting on it outright — a safety net against an executor implementation that
# doesn't correctly bound its own polling, not the primary timeout mechanism.
_EXECUTOR_WAIT_SLACK_SECONDS = 60.0


class JobProcessor:
    """The concurrency-aware orchestrator the worker process actually runs.

    Claims jobs and processes each as its own asyncio task (bounded by a semaphore),
    so a long-running job never blocks claiming/provisioning the next one. Each task
    gets its own repositories (and therefore its own DB session) via repository_factory
    — AsyncSession isn't safe to share across concurrent tasks.
    """

    def __init__(
        self,
        repository_factory: RepositoryFactory,
        provisioner: WorkerProvisioner,
        executor: JobExecutor,
        ssm_ready_timeout_seconds: float,
        job_execution_timeout_seconds: float,
        max_concurrent_jobs: int,
    ) -> None:
        self._repository_factory = repository_factory
        self._provisioner = provisioner
        self._executor = executor
        self._ssm_ready_timeout_seconds = ssm_ready_timeout_seconds
        self._job_execution_timeout_seconds = job_execution_timeout_seconds
        self._max_concurrent_jobs = max_concurrent_jobs
        self._semaphore = asyncio.Semaphore(max_concurrent_jobs)

    def _worker_manager_for(self, repos: RepositoryBundle) -> WorkerManager:
        return WorkerManager(
            worker_repository=repos.worker_repository,
            provisioner=self._provisioner,
            ssm_ready_timeout_seconds=self._ssm_ready_timeout_seconds,
        )

    async def run_forever(self, poll_interval_seconds: float) -> None:
        logger.info(
            "JobProcessor starting poll loop (interval=%ss, max_concurrent=%s)",
            poll_interval_seconds,
            self._max_concurrent_jobs,
        )
        background_tasks: set[asyncio.Task[None]] = set()
        while True:
            # Only claim a job once we have capacity to actually start processing it —
            # otherwise claimed-but-unprocessed jobs would pile up in 'running' for no
            # reason ahead of what this process can concurrently handle.
            await self._semaphore.acquire()

            async with self._repository_factory() as repos:
                job = await repos.job_repository.claim_next_job()

            if job is None:
                self._semaphore.release()
                await asyncio.sleep(poll_interval_seconds)
                continue

            task = asyncio.create_task(self._run_job(job))
            background_tasks.add(task)
            task.add_done_callback(lambda t: self._on_job_task_done(t, background_tasks))

    def _on_job_task_done(
        self, task: "asyncio.Task[None]", background_tasks: set["asyncio.Task[None]"]
    ) -> None:
        background_tasks.discard(task)
        self._semaphore.release()
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Unhandled exception processing job: %s", exc, exc_info=exc)

    async def _run_job(self, job: Job) -> None:
        if job.job_type != JobType.SHELL:
            async with self._repository_factory() as repos:
                await repos.job_repository.fail(
                    job.id,
                    error_message=(
                        f"Job type '{job.job_type.value}' execution is not yet supported"
                    ),
                )
            return

        async with self._repository_factory() as repos:
            try:
                worker = await self._worker_manager_for(repos).provision_worker(job.id)
            except Exception as exc:
                await repos.job_repository.fail(job.id, error_message=str(exc))
                return

        if worker.instance_id is None:
            # Can't happen given provision_worker's contract (mark_ready always follows
            # mark_provisioning, which always sets instance_id) — handled explicitly
            # rather than asserted, since it's a real None in the type system.
            async with self._repository_factory() as repos:
                await repos.job_repository.fail(
                    job.id, error_message="Worker has no instance id after provisioning"
                )
            return

        command = str(job.payload.get("command", ""))
        try:
            execution_result = await asyncio.wait_for(
                self._executor.execute(job.id, command, worker.instance_id),
                timeout=self._job_execution_timeout_seconds + _EXECUTOR_WAIT_SLACK_SECONDS,
            )
        except Exception as exc:
            logger.warning("Execution failed for job %s: %s", job.id, exc)
            async with self._repository_factory() as repos:
                await repos.job_repository.fail(job.id, error_message=str(exc))
                await self._worker_manager_for(repos).terminate_worker_for_job(job.id)
            return

        async with self._repository_factory() as repos:
            if execution_result.succeeded:
                await repos.job_repository.complete(job.id, execution_result.result)
            else:
                await repos.job_repository.fail(
                    job.id,
                    error_message=execution_result.error_message or "Job execution failed",
                )
            await self._worker_manager_for(repos).terminate_worker_for_job(job.id)
