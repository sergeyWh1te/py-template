"""Narrow interfaces for injected cross-cutting dependencies (mirrors go-template's ``utils/deps``).

These are ``typing.Protocol`` classes: anything with matching methods satisfies
them structurally, so the concrete structlog logger never has to inherit from or
even know about this module, and a test can pass a ten-line fake.
"""

from typing import Protocol


class Logger(Protocol):
    """The structured, key/value logging surface handlers and middleware depend on.

    Log an event name plus fields — ``log.error("get user", error=str(err))`` —
    never a pre-formatted string.
    """

    def debug(self, event: str, **kw: object) -> object: ...

    def info(self, event: str, **kw: object) -> object: ...

    def warning(self, event: str, **kw: object) -> object: ...

    def error(self, event: str, **kw: object) -> object: ...
