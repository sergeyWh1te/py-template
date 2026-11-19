import platform

import httpx
from prometheus_client import CollectorRegistry

from app_template.app.repository import new_repositories
from app_template.app.routes import new_router
from app_template.app.server import App
from app_template.app.usecase import Usecases, new_usecases
from app_template.connectors import metrics
from app_template.connectors.postgres import Pool
from app_template.pkg.users.entity import User
from app_template.pkg.users.repository import UserRepository
from app_template.utils.either import right
from tests.pkg.users.mocks import UsecaseMock
from tests.utils.fake_logger import FakeLogger


def build(usecases: Usecases) -> httpx.AsyncClient:
    store = metrics.new(CollectorRegistry(), "py-template", "test", "deadbeef")
    app = App(FakeLogger(), store, usecases)
    app.metrics.build_info.inc()
    api = new_router()
    app.register_routes(api)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test")


async def test_routes_are_wired() -> None:
    usecases = Usecases(user=UsecaseMock(get_result=right(User(id=1))))

    async with build(usecases) as client:
        health = await client.get("/health")
        example = await client.get("/example")
        exposition = await client.get("/metrics")
        docs = await client.get("/docs")

    assert health.json() == {"status": "ok"}
    assert example.json() == {"id": 1}
    labels = f'commit="deadbeef",env="test",name="py-template",version="{platform.python_version()}"'
    assert f"py_template_metric_build_info_total{{{labels}}} 1.0" in exposition.text
    assert docs.status_code == 404


async def test_full_stack_against_the_database(db: Pool) -> None:
    # The real repository and usecase, wired by the composition-root factories.
    usecases = new_usecases(new_repositories(db))

    async with build(usecases) as client:
        missing = await client.get("/example")
        created = await UserRepository(db).create()
        found = await client.get("/example")

    assert missing.status_code == 404
    assert missing.json() == {"error": "user not found"}
    assert created == right(1)
    assert found.status_code == 200
    assert found.json() == {"id": 1}
