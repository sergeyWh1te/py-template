import asyncio

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app_template.http.middleware.access_log import AccessLogMiddleware
from app_template.http.middleware.recovery import RecoveryMiddleware
from app_template.http.middleware.request_id import HEADER, RequestIDMiddleware, request_id
from app_template.http.middleware.timeout import TimeoutMiddleware
from tests.utils.fake_logger import FakeLogger


def build(log: FakeLogger, timeout_s: float = 10.0) -> FastAPI:
    api = FastAPI()
    # Same order as app/routes.py: RequestID outermost, Timeout innermost.
    api.add_middleware(TimeoutMiddleware, log=log, seconds=timeout_s)
    api.add_middleware(RecoveryMiddleware, log=log)
    api.add_middleware(AccessLogMiddleware, log=log)
    api.add_middleware(RequestIDMiddleware)

    async def echo_id(request: Request) -> JSONResponse:
        return JSONResponse({"request_id": request_id(request.scope)})

    async def boom() -> JSONResponse:
        msg = "handler bug"
        raise RuntimeError(msg)

    async def slow() -> JSONResponse:
        await asyncio.sleep(5)
        return JSONResponse({})

    async def inner_timeout() -> JSONResponse:
        # A TimeoutError that is not the middleware's own deadline.
        raise TimeoutError

    api.add_api_route("/id", echo_id, methods=["GET"])
    api.add_api_route("/boom", boom, methods=["GET"])
    api.add_api_route("/slow", slow, methods=["GET"])
    api.add_api_route("/inner-timeout", inner_timeout, methods=["GET"])
    return api


async def get(api: FastAPI, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


async def test_request_id_is_generated_and_returned() -> None:
    response = await get(build(FakeLogger()), "/id")

    rid = response.headers[HEADER]
    assert len(rid) == 32
    assert response.json() == {"request_id": rid}


async def test_valid_incoming_request_id_is_reused() -> None:
    response = await get(build(FakeLogger()), "/id", headers={HEADER: "upstream-123"})

    assert response.headers[HEADER] == "upstream-123"


async def test_oversized_incoming_request_id_is_replaced() -> None:
    response = await get(build(FakeLogger()), "/id", headers={HEADER: "x" * 500})

    assert response.headers[HEADER] != "x" * 500


async def test_access_log_records_status_and_request_id() -> None:
    log = FakeLogger()

    response = await get(build(log), "/id")

    assert log.levels() == ["info"]
    entry = log.entries[0]
    assert entry.event == "http request"
    assert entry.fields["method"] == "GET"
    assert entry.fields["path"] == "/id"
    assert entry.fields["status"] == 200
    assert entry.fields["request_id"] == response.headers[HEADER]


async def test_unhandled_exception_becomes_logged_500() -> None:
    log = FakeLogger()

    response = await get(build(log), "/boom")

    assert response.status_code == 500
    assert response.json() == {"error": "internal server error"}
    assert HEADER in response.headers
    assert log.levels() == ["error", "info"]
    assert log.entries[0].event == "unhandled exception"
    # The access log sees the recovered status.
    assert log.entries[1].fields["status"] == 500


async def test_slow_request_hits_the_timeout() -> None:
    log = FakeLogger()

    response = await get(build(log, timeout_s=0.05), "/slow")

    assert response.status_code == 503
    assert response.json() == {"error": "request timeout"}
    assert log.entries[0].event == "request timed out"


async def test_foreign_timeout_error_is_a_regular_500() -> None:
    log = FakeLogger()

    response = await get(build(log), "/inner-timeout")

    assert response.status_code == 500
    assert log.entries[0].event == "unhandled exception"
