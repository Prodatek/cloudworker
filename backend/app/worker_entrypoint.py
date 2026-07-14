import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.entities import JobType
from app.domain.job_executor import JobExecutor
from app.domain.repositories import RepositoryBundle, RepositoryFactory
from app.infrastructure.aws.ec2_worker_provisioner import EC2WorkerProvisioner
from app.infrastructure.aws.playwright_job_executor import PlaywrightJobExecutor
from app.infrastructure.aws.s3_artifact_store import S3ArtifactStore
from app.infrastructure.aws.ssm_job_executor import SsmJobExecutor
from app.infrastructure.database import create_engine, create_session_factory
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.services.job_processor import JobProcessor
from app.services.worker_reaper import WorkerReaper


def _make_repository_factory(settings: Settings) -> tuple[AsyncEngine, RepositoryFactory]:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def repository_factory() -> AsyncIterator[RepositoryBundle]:
        async with session_factory() as session:
            yield RepositoryBundle(
                job_repository=SqlAlchemyJobRepository(session),
                worker_repository=SqlAlchemyWorkerRepository(session),
            )

    return engine, repository_factory


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine, repository_factory = _make_repository_factory(settings)

    artifact_store = S3ArtifactStore(
        region=settings.aws_region,
        logs_bucket_name=settings.logs_bucket_name,
        artifacts_bucket_name=settings.artifacts_bucket_name,
    )
    executors: dict[JobType, JobExecutor] = {
        JobType.SHELL: SsmJobExecutor(
            region=settings.aws_region,
            logs_bucket_name=settings.logs_bucket_name,
            execution_timeout_seconds=settings.job_execution_timeout_seconds,
        ),
        JobType.BROWSER: PlaywrightJobExecutor(
            region=settings.aws_region,
            logs_bucket_name=settings.logs_bucket_name,
            artifacts_bucket_name=settings.artifacts_bucket_name,
            artifact_store=artifact_store,
            execution_timeout_seconds=settings.job_execution_timeout_seconds,
        ),
    }

    provisioner = EC2WorkerProvisioner(
        region=settings.aws_region,
        launch_template_id=settings.launch_template_id,
        subnet_ids=settings.worker_subnet_id_list,
    )

    processor = JobProcessor(
        repository_factory=repository_factory,
        provisioner=provisioner,
        executors=executors,
        ssm_ready_timeout_seconds=settings.ssm_ready_timeout_seconds,
        job_execution_timeout_seconds=settings.job_execution_timeout_seconds,
        max_concurrent_jobs=settings.max_concurrent_jobs,
    )
    reaper = WorkerReaper(
        repository_factory=repository_factory,
        provisioner=provisioner,
        stale_after_seconds=settings.worker_stale_after_seconds,
    )
    try:
        # One process, two independent poll loops: the reaper is a safety net that must
        # keep running even though it's logically separate from the job-claiming loop —
        # same single-deployable-unit reasoning the worker process already follows.
        await asyncio.gather(
            processor.run_forever(settings.worker_poll_interval_seconds),
            reaper.run_forever(settings.worker_reaper_poll_interval_seconds),
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
