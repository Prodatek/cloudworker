import asyncio

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.aws.ec2_worker_provisioner import EC2WorkerProvisioner
from app.infrastructure.database import create_engine, create_session_factory
from app.infrastructure.db.job_repository import SqlAlchemyJobRepository
from app.infrastructure.db.worker_repository import SqlAlchemyWorkerRepository
from app.services.worker_manager import WorkerManager


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        manager = WorkerManager(
            job_repository=SqlAlchemyJobRepository(session),
            worker_repository=SqlAlchemyWorkerRepository(session),
            provisioner=EC2WorkerProvisioner(
                region=settings.aws_region,
                launch_template_id=settings.launch_template_id,
                subnet_ids=settings.worker_subnet_id_list,
            ),
            ssm_ready_timeout_seconds=settings.ssm_ready_timeout_seconds,
        )
        try:
            await manager.run_forever(settings.worker_poll_interval_seconds)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
