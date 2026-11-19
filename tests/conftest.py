from collections.abc import AsyncIterator

import pytest

from app_template import env
from app_template.connectors.postgres import Pool
from tests import testdb

# Every variable env.py reads. The Makefile exports .env into the test process
# (`-include .env` + `export`), so tests that depend on config must start clean.
CONFIG_VARS = (
    "APP_NAME",
    "ENV",
    "PORT",
    "LOG_FORMAT",
    "LOG_LEVEL",
    "COMMIT",
    "READ_ENV_FROM_SHELL",
    "PG_HOST",
    "PG_PORT",
    "PG_USERNAME",
    "PG_PASSWORD",
    "PG_DATABASE",
    "PG_SCHEMA",
    "PG_SSLMODE",
)


@pytest.fixture
async def db() -> AsyncIterator[Pool]:
    """Yield a pool onto a migrated, truncated test database — see tests/testdb.py."""
    async with testdb.new() as pool:
        yield pool


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every config variable from the environment and reset the memoized config."""
    for name in CONFIG_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(env, "_config", None)
    return monkeypatch
