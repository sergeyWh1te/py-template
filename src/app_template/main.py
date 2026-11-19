"""Entry point: signals -> config -> logger -> db -> wire -> serve -> drain -> close db.

Run it as ``app-template`` (the console script) or ``python -m app_template``.
Never as ``python src/app_template/main.py``: that puts the package directory on
``sys.path`` and the ``app_template.http`` subpackage would shadow the stdlib
``http`` module.
"""

import asyncio
import signal
import sys

from prometheus_client import CollectorRegistry

from app_template import env
from app_template.app.repository import new_repositories
from app_template.app.routes import new_router
from app_template.app.server import App
from app_template.app.usecase import new_usecases
from app_template.connectors import logger, metrics, postgres
from app_template.utils.either import is_left
from app_template.utils.shutdown import Shutdown

_HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM)


async def run() -> int:
    # Signals first, so a Ctrl-C during startup is already a clean shutdown request.
    loop = asyncio.get_running_loop()
    shutdown = Shutdown()
    for sig in _HANDLED_SIGNALS:
        loop.add_signal_handler(sig, shutdown.request)

    cfg_result = env.read()
    if is_left(cfg_result):
        # No logger yet: the logger is configured from this very config.
        print(f"read env error: {cfg_result.left}", file=sys.stderr)  # noqa: T201
        return 1
    cfg = cfg_result.right

    log = logger.new(cfg.app)

    db_result = await postgres.connect(cfg.pg)
    if is_left(db_result):
        log.error("could not connect to db", error=str(db_result.left))
        return 1
    db = db_result.right

    try:
        log.info("started application", name=cfg.app.name, env=cfg.app.env, port=cfg.app.port)

        metrics_store = metrics.new(CollectorRegistry(), cfg.app.name, cfg.app.env, cfg.app.commit)

        repos = new_repositories(db)
        usecases = new_usecases(repos)

        app = App(log, metrics_store, usecases)
        app.metrics.build_info.inc()

        api = new_router()
        app.register_routes(api)

        served = await app.run_http_server(cfg.app.port, api, shutdown)

        # Stop trapping signals now that the server has drained: from here on a
        # second Ctrl-C must kill the process outright, not be swallowed while
        # the pool is closing.
        release_signals(loop)
    finally:
        # Close the pool only now: the server has drained, so no handler still
        # holds a connection. On the early-exception path this is the safety net.
        await postgres.close()

    if is_left(served):
        log.error("server stopped", error=str(served.left))
        return 1

    log.info("shutdown complete")
    return 0


def release_signals(loop: asyncio.AbstractEventLoop) -> None:
    for sig in _HANDLED_SIGNALS:
        loop.remove_signal_handler(sig)
        # SIG_DFL, not Python's default SIGINT handler: KeyboardInterrupt could be
        # caught on its way out; the OS default terminates, like Go after stop().
        signal.signal(sig, signal.SIG_DFL)


def main() -> None:
    sys.exit(asyncio.run(run()))
