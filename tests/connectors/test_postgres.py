import socket
from collections.abc import AsyncIterator

import pytest
from psycopg.conninfo import conninfo_to_dict

from app_template.connectors import postgres
from app_template.env import PgConfig
from app_template.utils.either import is_left, is_right
from app_template.utils.errors import WrappedError
from tests import testdb


def pg_config(**overrides: object) -> PgConfig:
    values: dict[str, object] = {
        "PG_HOST": "127.0.0.1",
        "PG_PORT": 5434,
        "PG_USERNAME": "postgres",
        "PG_PASSWORD": "postgres",
        "PG_DATABASE": "master",
    }
    for key, value in overrides.items():
        values[key] = value
    return PgConfig.model_validate(values)


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(autouse=True)
async def reset_shared_pool() -> AsyncIterator[None]:
    await postgres.close()
    yield
    await postgres.close()


def test_conninfo_escapes_credentials() -> None:
    password = "p@ss word'with=quotes"
    dsn = postgres.conninfo(pg_config(PG_PASSWORD=password, PG_USERNAME="us er"))

    parsed = conninfo_to_dict(dsn)

    assert parsed["password"] == password
    assert parsed["user"] == "us er"
    assert parsed["host"] == "127.0.0.1"
    assert parsed["port"] == "5434"
    assert parsed["dbname"] == "master"
    assert parsed["sslmode"] == "disable"


async def test_failed_connect_returns_left_and_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing listens on the port; no need to wait the full production budget.
    monkeypatch.setattr(postgres, "PING_TIMEOUT_S", 0.5)
    cfg = pg_config(PG_PORT=unused_port())

    first = await postgres.connect(cfg)
    assert is_left(first)
    assert isinstance(first.left, WrappedError)
    assert "could not connect to postgres" in str(first.left)

    # Not memoized: the shared handle is still empty, so a second call redials.
    assert postgres._pool is None
    second = await postgres.connect(cfg)
    assert is_left(second)


async def test_connect_is_memoized_and_close_resets_it() -> None:
    parsed = conninfo_to_dict(await testdb.resolve_dsn())
    cfg = pg_config(
        PG_HOST=parsed.get("host", "127.0.0.1"),
        PG_PORT=int(str(parsed.get("port", "5432"))),
        PG_USERNAME=parsed.get("user", "postgres"),
        PG_PASSWORD=parsed.get("password", ""),
        PG_DATABASE=parsed.get("dbname", "master"),
    )

    first = await postgres.connect(cfg)
    assert is_right(first)
    second = await postgres.connect(cfg)
    assert is_right(second)
    assert second.right is first.right

    async with first.right.connection() as conn:
        cur = await conn.execute("select 1")
        assert await cur.fetchone() == (1,)

    await postgres.close()
    assert postgres._pool is None
    assert first.right.closed


async def test_close_without_connect_is_a_no_op() -> None:
    await postgres.close()
    await postgres.close()
