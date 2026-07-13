from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.aws.ec2_worker_provisioner import EC2WorkerProvisioner
from app.infrastructure.aws.s3_artifact_store import S3ArtifactStore
from app.infrastructure.database import create_engine, create_session_factory
from app.infrastructure.metrics import PrometheusMiddleware, render_metrics


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db_engine = create_engine(settings)
        app.state.db_session_factory = create_session_factory(app.state.db_engine)

        # None until Phase 3's Terraform is actually applied and these are configured —
        # get_worker_manager (api/v1/deps.py) returns None rather than crashing the API
        # process when a caller needs it and it's unset.
        app.state.worker_provisioner = None
        if settings.launch_template_id and settings.worker_subnet_id_list:
            app.state.worker_provisioner = EC2WorkerProvisioner(
                region=settings.aws_region,
                launch_template_id=settings.launch_template_id,
                subnet_ids=settings.worker_subnet_id_list,
            )

        # Same None-until-configured pattern as worker_provisioner above; get_artifact_store
        # (api/v1/deps.py) returns None when neither bucket is set.
        app.state.artifact_store = None
        if settings.logs_bucket_name or settings.artifacts_bucket_name:
            app.state.artifact_store = S3ArtifactStore(
                region=settings.aws_region,
                logs_bucket_name=settings.logs_bucket_name,
                artifacts_bucket_name=settings.artifacts_bucket_name,
            )

        yield
        await app.state.db_engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Provisions ephemeral AWS workers, runs shell/Playwright jobs, "
            "and streams logs and artifacts."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Ops endpoints stay unversioned at the root, since load balancer/orchestrator
    # health checks are configured against a fixed path regardless of API version.
    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        body, content_type = render_metrics()
        return Response(content=body, media_type=content_type)

    return app


app = create_app()
