from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.database import create_engine, create_session_factory
from app.infrastructure.metrics import PrometheusMiddleware, render_metrics


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db_engine = create_engine(settings)
        app.state.db_session_factory = create_session_factory(app.state.db_engine)
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
