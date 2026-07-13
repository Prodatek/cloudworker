from httpx import AsyncClient


async def test_readyz_confirms_real_database_connectivity(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_healthz_still_works_alongside_real_db(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
