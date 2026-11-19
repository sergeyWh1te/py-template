import httpx
from fastapi import FastAPI
from prometheus_client import CollectorRegistry, Counter

from app_template.http.handlers.metrics.handler import MetricsHandler


async def test_metrics_serves_the_given_registry_only() -> None:
    registry = CollectorRegistry()
    Counter("served_here", "in the app registry", registry=registry).inc()
    api = FastAPI()
    api.add_api_route("/metrics", MetricsHandler(registry).handle, methods=["GET"])

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "served_here_total 1.0" in response.text
    # Nothing from the global default registry leaks in.
    assert "python_info" not in response.text
