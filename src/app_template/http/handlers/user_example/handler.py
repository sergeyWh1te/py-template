from typing import Protocol

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app_template.pkg.users.entity import User
from app_template.pkg.users.errors import NotFoundError
from app_template.utils.deps import Logger
from app_template.utils.either import Either, is_left

EXAMPLE_USER_ID = 1


class UserGetter(Protocol):
    """The one usecase method this handler calls — declared by the consumer.

    Narrower than ``users.Usecase``: a test fake only has to implement ``get``,
    and adding methods to the usecase never touches this handler.
    """

    async def get(self, user_id: int) -> Either[Exception, User]: ...


class UserResponse(BaseModel):
    """HTTP DTO. Built here from the domain entity; never passed into the domain."""

    id: int


class UserExampleHandler:
    def __init__(self, log: Logger, users: UserGetter) -> None:
        self._log = log
        self._users = users

    async def handle(self) -> JSONResponse:
        result = await self._users.get(EXAMPLE_USER_ID)
        if is_left(result):
            return self._error(result.left)

        body = UserResponse(id=result.right.id)
        return JSONResponse(body.model_dump())

    def _error(self, err: Exception) -> JSONResponse:
        if isinstance(err, NotFoundError):
            # Expected outcome of the request, not a fault of the service.
            self._log.warning("get user", user_id=EXAMPLE_USER_ID, error=str(err))
            return JSONResponse({"error": "user not found"}, status_code=404)

        # Details go to the log, never to the client.
        self._log.error("get user", user_id=EXAMPLE_USER_ID, error=str(err), exc_info=err)
        return JSONResponse({"error": "internal server error"}, status_code=500)
