import asyncio

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app_template.http.middleware.request_id import request_id
from app_template.utils.deps import Logger

# go-template sets http.Server ReadTimeout/WriteTimeout to 10s. uvicorn has no
# equivalent per-request timeouts, so the budget is enforced here around the
# whole request (body read + handler + response write).
DEFAULT_REQUEST_TIMEOUT_S = 10.0


class TimeoutMiddleware:
    def __init__(self, app: ASGIApp, log: Logger, seconds: float = DEFAULT_REQUEST_TIMEOUT_S) -> None:
        self._app = app
        self._log = log
        self._seconds = seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        budget = asyncio.timeout(self._seconds)
        try:
            async with budget:
                await self._app(scope, receive, send_tracking_start)
        except TimeoutError:
            # Only our own deadline is handled; a TimeoutError raised by code
            # inside the handler is a regular exception for the recovery layer.
            if not budget.expired():
                raise
            self._log.error("request timed out", path=scope["path"], request_id=request_id(scope))
            if started:
                return
            # 503, like Go's http.TimeoutHandler.
            response = JSONResponse({"error": "request timeout"}, status_code=503)
            await response(scope, receive, send)
