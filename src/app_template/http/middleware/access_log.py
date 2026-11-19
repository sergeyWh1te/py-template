import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app_template.http.middleware.request_id import request_id
from app_template.utils.deps import Logger

_STATUS_INTERNAL_ERROR = 500


class AccessLogMiddleware:
    """One structured log line per request (uvicorn's own access log is turned off)."""

    def __init__(self, app: ASGIApp, log: Logger) -> None:
        self._app = app
        self._log = log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        start = time.perf_counter()
        status = _STATUS_INTERNAL_ERROR

        async def send_capturing_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, send_capturing_status)
        finally:
            self._log.info(
                "http request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 3),
                request_id=request_id(scope),
            )
