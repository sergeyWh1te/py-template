"""Ports of the users domain, as ``typing.Protocol`` classes.

* ``Repository`` is declared here because its consumer — the usecase — lives in
  this package. The concrete ``UserRepository`` satisfies it structurally.
* ``Usecase`` is the domain's published contract: the composition root stores
  the concrete usecase under this type. Each handler additionally declares the
  narrow slice it actually calls (see ``http/handlers/user_example``), and mypy
  checks the two are compatible at the wiring point in ``app/routes.py``.

Both return ``Either`` — expected failures (not found, database down) are values.
"""

from typing import Protocol

from app_template.pkg.users.entity import User
from app_template.utils.either import Either


class Repository(Protocol):
    async def get(self, user_id: int) -> Either[Exception, User]: ...

    async def create(self) -> Either[Exception, int]: ...


class Usecase(Protocol):
    async def get(self, user_id: int) -> Either[Exception, User]: ...
