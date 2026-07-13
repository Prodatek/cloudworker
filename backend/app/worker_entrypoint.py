import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.repositories import RepositoryBundle, RepositoryFactory
from app.infrastructure.aws.ec2_worker_provisioner import EC2WorkerProvisioner
from app.infrastructure.aws.ssm_job_executor import SsmJobExecutor
from app.infrastructure.database import create_engine, create_session_factory
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.services.job_processor import JobProcessor


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

    processor = JobProcessor(
        repository_factory=repository_factory,
        provisioner=EC2WorkerProvisioner(
            region=settings.aws_region,
            launch_template_id=settings.launch_template_id,
            subnet_ids=settings.worker_subnet_id_list,
        ),
        executor=SsmJobExecutor(
            region=settings.aws_region,
            logs_bucket_name=settings.logs_bucket_name,
            execution_timeout_seconds=settings.job_execution_timeout_seconds,
        ),
        ssm_ready_timeout_seconds=settings.ssm_ready_timeout_seconds,
        job_execution_timeout_seconds=settings.job_execution_timeout_seconds,
        max_concurrent_jobs=settings.max_concurrent_jobs,
    )
    try:
        await processor.run_forever(settings.worker_poll_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
