from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app_template.http.middleware.request_id import request_id
from app_template.utils.deps import Logger


class RecoveryMiddleware:
    """Turns an unexpected exception in a handler into a logged 500 (chi's ``Recoverer``).

    Expected failures never get here — they travel as ``Left`` values and handlers
    map them to responses. What arrives here is a bug, so it is logged with its
    traceback and the client gets a generic body.
    """

    def __init__(self, app: ASGIApp, log: Logger) -> None:
        self._app = app
        self._log = log

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

        try:
            await self._app(scope, receive, send_tracking_start)
        except Exception as exc:  # noqa: BLE001 — this is the catch-all boundary by design.
            self._log.error("unhandled exception", path=scope["path"], request_id=request_id(scope), exc_info=exc)
            if started:
                # Headers are already on the wire; the server closes the
                # half-written response. Nothing more can be sent.
                return
            response = JSONResponse({"error": "internal server error"}, status_code=500)
            await response(scope, receive, send)
