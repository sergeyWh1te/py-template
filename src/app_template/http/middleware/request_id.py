import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = "X-Request-Id"
_MAX_INCOMING_LEN = 128


def request_id(scope: Scope) -> str:
    """Return the id ``RequestIDMiddleware`` assigned to this request ("" outside a request)."""
    state = scope.get("state")
    if not isinstance(state, dict):
        return ""
    value = state.get("request_id")
    if not isinstance(value, str):
        return ""
    return value


def _accept_incoming(value: str | None) -> bool:
    # Reuse an upstream id (load balancer, caller) so one request can be followed
    # across services — but never echo arbitrary junk into logs and headers.
    if value is None or value == "":
        return False
    if len(value) > _MAX_INCOMING_LEN:
        return False
    return value.isascii() and value.isprintable()


class RequestIDMiddleware:
    """Assigns every request an id, exposes it in ``scope["state"]`` and the response header."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(HEADER)
        rid = uuid.uuid4().hex
        if incoming is not None and _accept_incoming(incoming):
            rid = incoming

        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = rid
            await send(message)

        await self._app(scope, receive, send_with_id)
