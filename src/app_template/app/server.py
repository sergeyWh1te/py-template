import asyncio
import contextlib
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI

from app_template.app.routes import register_routes
from app_template.app.usecase import Usecases
from app_template.connectors.metrics import Metrics
from app_template.utils.deps import Logger
from app_template.utils.either import Either, left, right
from app_template.utils.shutdown import Shutdown

# go-template's ReadTimeout/WriteTimeout (10s) are enforced per request by
# http.middleware.timeout; uvicorn has no such server-level knobs.
DEFAULT_IDLE_TIMEOUT_S = 60
# How long in-flight requests get to finish once a signal arrives. uvicorn
# starts this clock when the shutdown begins, so it is a fresh budget — never
# one that already ran out with the context that triggered the shutdown.
DEFAULT_SHUTDOWN_TIMEOUT_S = 15


class _Server(uvicorn.Server):
    """uvicorn's server with its signal handling switched off.

    Stock ``Server.serve`` traps SIGINT/SIGTERM itself and, once it returns,
    *re-raises* the captured signal — which would kill the process (SIGTERM) or
    cancel ``main`` (SIGINT) before the database pool is closed. ``main`` owns
    the signals instead and drives shutdown through ``Shutdown``.
    """

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


class App:
    def __init__(self, log: Logger, metrics: Metrics, usecases: Usecases) -> None:
        self.log = log
        self.metrics = metrics
        self._usecases = usecases

    def register_routes(self, api: FastAPI) -> None:
        register_routes(api, self.log, self.metrics, self._usecases)

    async def run_http_server(self, port: int, api: FastAPI, shutdown: Shutdown) -> Either[Exception, None]:
        """Serve until ``shutdown`` is requested, then drain for up to DEFAULT_SHUTDOWN_TIMEOUT_S."""
        config = uvicorn.Config(
            api,
            host="0.0.0.0",  # noqa: S104 — a service in a container must listen on all interfaces.
            port=port,
            # Resources are owned by main (opened before, closed after the
            # server), not by an ASGI lifespan.
            lifespan="off",
            # One structured access log line comes from AccessLogMiddleware;
            # uvicorn must not install its own logging config on top.
            log_config=None,
            access_log=False,
            timeout_keep_alive=DEFAULT_IDLE_TIMEOUT_S,
            timeout_graceful_shutdown=DEFAULT_SHUTDOWN_TIMEOUT_S,
            server_header=False,
        )
        server = _Server(config)

        watcher = asyncio.create_task(_watch(server, shutdown, self.log))
        try:
            await server.serve()
        except SystemExit as exc:
            # uvicorn reports a failed bind with sys.exit(1) from inside serve().
            return left(RuntimeError(f"http server failed to start on port {port} (exit {exc.code})"))
        finally:
            watcher.cancel()

        return right(None)


async def _watch(server: uvicorn.Server, shutdown: Shutdown, log: Logger) -> None:
    await shutdown.requested.wait()
    log.info("shutdown requested, draining in-flight requests", timeout_s=DEFAULT_SHUTDOWN_TIMEOUT_S)
    server.should_exit = True
    # A second signal while draining: stop waiting for in-flight requests.
    await shutdown.forced.wait()
    log.warning("second signal, cancelling in-flight requests", count=len(server.server_state.tasks))
    server.force_exit = True
    # force_exit alone only skips uvicorn's polling loops; its final
    # wait_closed() still waits for every open connection. Cancelling the
    # request tasks is what uvicorn itself does when the drain budget runs out.
    for task in list(server.server_state.tasks):
        task.cancel("forced shutdown")
