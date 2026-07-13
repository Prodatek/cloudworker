import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import health
from app.main import app


class _FakeEngine:
    """Stands in for the real SQLAlchemy engine so no Postgres is needed."""


@pytest.fixture
async def client():
    app.state.db_engine = _FakeEngine()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_healthz_returns_ok_with_no_dependencies(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_returns_200_when_database_reachable(monkeypatch, client: AsyncClient) -> None:
    async def fake_check_ok(_engine: object) -> bool:
        return True

    monkeypatch.setattr(health, "check_database_connection", fake_check_ok)

    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_readyz_returns_503_when_database_unreachable(
    monkeypatch, client: AsyncClient
) -> None:
    async def fake_check_failing(_engine: object) -> bool:
        return False

    monkeypatch.setattr(health, "check_database_connection", fake_check_failing)

    response = await client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
