"""Hand-written test doubles for the users ports.

Plain classes rather than ``unittest.mock``: they are type-checked against the
Protocols (see the assignments at the bottom), so a signature change in
``interfaces.py`` breaks mypy here instead of silently passing a test.
"""

from dataclasses import dataclass, field

from app_template.pkg.users import interfaces as users
from app_template.pkg.users.entity import User
from app_template.utils.either import Either, left


@dataclass(slots=True)
class RepositoryMock:
    get_result: Either[Exception, User] = field(default_factory=lambda: left(RuntimeError("get not stubbed")))
    create_result: Either[Exception, int] = field(default_factory=lambda: left(RuntimeError("create not stubbed")))
    get_calls: list[int] = field(default_factory=list)
    create_calls: int = 0

    async def get(self, user_id: int) -> Either[Exception, User]:
        self.get_calls.append(user_id)
        return self.get_result

    async def create(self) -> Either[Exception, int]:
        self.create_calls += 1
        return self.create_result


@dataclass(slots=True)
class UsecaseMock:
    get_result: Either[Exception, User] = field(default_factory=lambda: left(RuntimeError("get not stubbed")))
    get_calls: list[int] = field(default_factory=list)

    async def get(self, user_id: int) -> Either[Exception, User]:
        self.get_calls.append(user_id)
        return self.get_result


# Static conformance checks: mypy fails here if a mock drifts from its port.
_repository_check: type[users.Repository] = RepositoryMock
_usecase_check: type[users.Usecase] = UsecaseMock
