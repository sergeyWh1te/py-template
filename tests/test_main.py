import asyncio
import os
import signal
import socket
from collections.abc import Iterator

import httpx
import pytest
from psycopg.conninfo import conninfo_to_dict

from app_template import main
from app_template.connectors import postgres
from tests import testdb


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture
def restore_signals() -> Iterator[None]:
    # run() resets SIGINT/SIGTERM to SIG_DFL after draining; give pytest its
    # own handlers back afterwards.
    saved_int = signal.getsignal(signal.SIGINT)
    saved_term = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGINT, saved_int)
    signal.signal(signal.SIGTERM, saved_term)


@pytest.mark.usefixtures("restore_signals")
async def test_run_fails_fast_on_bad_config(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("READ_ENV_FROM_SHELL", "true")

    assert await main.run() == 1


@pytest.mark.usefixtures("restore_signals")
async def test_run_fails_when_the_database_is_unreachable(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setattr(postgres, "PING_TIMEOUT_S", 0.5)
    clean_env.setenv("READ_ENV_FROM_SHELL", "true")
    clean_env.setenv("APP_NAME", "test")
    clean_env.setenv("PG_HOST", "127.0.0.1")
    clean_env.setenv("PG_PORT", str(unused_port()))
    clean_env.setenv("PG_USERNAME", "postgres")
    clean_env.setenv("PG_PASSWORD", "postgres")
    clean_env.setenv("PG_DATABASE", "master")

    assert await main.run() == 1


@pytest.mark.usefixtures("restore_signals")
async def test_sigterm_drains_and_exits_cleanly(clean_env: pytest.MonkeyPatch) -> None:
    parsed = conninfo_to_dict(await testdb.resolve_dsn())
    port = unused_port()
    clean_env.setenv("READ_ENV_FROM_SHELL", "true")
    clean_env.setenv("APP_NAME", "py-template")
    clean_env.setenv("PORT", str(port))
    clean_env.setenv("LOG_LEVEL", "error")
    clean_env.setenv("PG_HOST", str(parsed.get("host", "127.0.0.1")))
    clean_env.setenv("PG_PORT", str(parsed.get("port", "5432")))
    clean_env.setenv("PG_USERNAME", str(parsed.get("user", "postgres")))
    clean_env.setenv("PG_PASSWORD", str(parsed.get("password", "")))
    clean_env.setenv("PG_DATABASE", str(parsed.get("dbname", "master")))

    task = asyncio.create_task(main.run())

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        body: object = None
        for _ in range(200):
            try:
                body = (await client.get("/metrics")).text
                break
            except httpx.ConnectError:
                await asyncio.sleep(0.05)

    os.kill(os.getpid(), signal.SIGTERM)
    code = await asyncio.wait_for(task, timeout=20)

    assert isinstance(body, str)
    assert "py_template_metric_build_info_total" in body
    assert code == 0
    # The pool was closed after the drain, and the signal handler released.
    assert postgres._pool is None
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
