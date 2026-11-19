import asyncio
import socket
import time

import httpx
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry

from app_template.app.routes import new_router
from app_template.app.server import App
from app_template.app.usecase import Usecases
from app_template.connectors import metrics
from app_template.utils.either import Either, is_left, is_right
from app_template.utils.shutdown import Shutdown
from tests.pkg.users.mocks import UsecaseMock
from tests.utils.fake_logger import FakeLogger


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def new_app() -> App:
    store = metrics.new(CollectorRegistry(), "test", "test", "")
    return App(FakeLogger(), store, Usecases(user=UsecaseMock()))


async def wait_until_healthy(port: int) -> httpx.Response:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        for _ in range(100):
            try:
                return await client.get("/health")
            except httpx.ConnectError:
                await asyncio.sleep(0.05)
    msg = "server did not come up"
    raise AssertionError(msg)


async def test_serves_until_shutdown_is_requested() -> None:
    app = new_app()
    api = new_router()
    app.register_routes(api)
    port = unused_port()
    shutdown = Shutdown()

    server: asyncio.Task[Either[Exception, None]] = asyncio.create_task(app.run_http_server(port, api, shutdown))
    response = await wait_until_healthy(port)
    shutdown.request()
    result = await asyncio.wait_for(server, timeout=10)

    assert response.json() == {"status": "ok"}
    assert is_right(result)


async def test_in_flight_request_is_drained_before_returning() -> None:
    app = new_app()
    api = new_router()
    app.register_routes(api)
    release = asyncio.Event()

    async def slow() -> JSONResponse:
        await release.wait()
        return JSONResponse({"done": True})

    api.add_api_route("/slow", slow, methods=["GET"])
    port = unused_port()
    shutdown = Shutdown()
    server = asyncio.create_task(app.run_http_server(port, api, shutdown))
    await wait_until_healthy(port)

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        in_flight = asyncio.create_task(client.get("/slow"))
        await asyncio.sleep(0.2)
        shutdown.request()
        await asyncio.sleep(0.3)
        # Shutdown was requested, but the server keeps waiting for the request.
        assert not server.done()
        release.set()
        response = await in_flight

    result = await asyncio.wait_for(server, timeout=10)
    assert response.json() == {"done": True}
    assert is_right(result)


async def test_second_request_forces_the_shutdown() -> None:
    app = new_app()
    api = new_router()
    app.register_routes(api)

    async def hang() -> JSONResponse:
        await asyncio.Event().wait()
        return JSONResponse({})

    api.add_api_route("/hang", hang, methods=["GET"])
    port = unused_port()
    shutdown = Shutdown()
    server = asyncio.create_task(app.run_http_server(port, api, shutdown))
    await wait_until_healthy(port)

    # Client timeout far beyond the assertion: only the forced shutdown can end the request.
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
        in_flight = asyncio.create_task(client.get("/hang"))
        await asyncio.sleep(0.2)
        started = time.monotonic()
        shutdown.request()
        shutdown.request()
        # Well inside the 15s drain budget: forced means "stop waiting".
        result = await asyncio.wait_for(server, timeout=5)
        elapsed = time.monotonic() - started
        response = await in_flight

    assert is_right(result)
    assert elapsed < 2
    # The cancelled handler is answered by the recovery path, not left hanging.
    assert response.status_code == 500


async def test_port_in_use_is_a_left() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("0.0.0.0", 0))  # noqa: S104 — must collide with the server's 0.0.0.0 bind.
        taken.listen()
        port: int = taken.getsockname()[1]

        result = await new_app().run_http_server(port, new_router(), Shutdown())

    assert is_left(result)
    assert f"port {port}" in str(result.left)
