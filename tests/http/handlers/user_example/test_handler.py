import httpx
from fastapi import FastAPI

from app_template.http.handlers.user_example.handler import EXAMPLE_USER_ID, UserExampleHandler
from app_template.pkg.users.entity import User
from app_template.pkg.users.errors import NotFoundError
from app_template.utils.either import left, right
from tests.pkg.users.mocks import UsecaseMock
from tests.utils.fake_logger import FakeLogger


async def get_example(handler: UserExampleHandler) -> httpx.Response:
    api = FastAPI()
    api.add_api_route("/example", handler.handle, methods=["GET"])
    transport = httpx.ASGITransport(app=api)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/example")


async def test_returns_200_with_the_user() -> None:
    log = FakeLogger()
    users = UsecaseMock(get_result=right(User(id=EXAMPLE_USER_ID)))

    response = await get_example(UserExampleHandler(log, users))

    assert response.status_code == 200
    assert response.json() == {"id": EXAMPLE_USER_ID}
    assert users.get_calls == [EXAMPLE_USER_ID]
    assert log.entries == []


async def test_returns_404_on_not_found_and_logs_a_warning() -> None:
    log = FakeLogger()
    users = UsecaseMock(get_result=left(NotFoundError("get user 1: user not found")))

    response = await get_example(UserExampleHandler(log, users))

    assert response.status_code == 404
    assert response.json() == {"error": "user not found"}
    assert log.levels() == ["warning"]


async def test_returns_500_on_any_other_error_and_logs_an_error() -> None:
    log = FakeLogger()
    users = UsecaseMock(get_result=left(RuntimeError("connection refused")))

    response = await get_example(UserExampleHandler(log, users))

    assert response.status_code == 500
    # The cause stays in the log; the client gets a generic body.
    assert response.json() == {"error": "internal server error"}
    assert "connection refused" not in response.text
    assert log.levels() == ["error"]
    assert log.entries[0].fields["error"] == "connection refused"
