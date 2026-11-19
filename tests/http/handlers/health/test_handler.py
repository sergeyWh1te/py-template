import httpx
from fastapi import FastAPI

from app_template.http.handlers.health.handler import HealthHandler


async def test_health_returns_ok() -> None:
    api = FastAPI()
    api.add_api_route("/health", HealthHandler().handle, methods=["GET"])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
