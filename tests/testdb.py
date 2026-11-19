"""Wires tests to a real Postgres instance.

Tests that need a database take the ``db`` fixture (tests/conftest.py), which
calls ``new``. Each test gets a pool onto a schema with every migration applied
and every table truncated (identity restarted), so ids are predictable.

Skip/fail split — deliberate, and the reason CI runs ``make test-integration``:

* ``TEST_PG_DSN`` unset and nothing answering at ``DEFAULT_DSN`` -> **skip**, so
  ``make test`` passes on a laptop with nothing running.
* ``TEST_PG_DSN`` set but the database unusable -> **fail**, so a broken CI
  service container can never look like a green run.

Migrations: the real ``db/migrations/*.up.sql`` files are executed in version
order, tracked in a golang-migrate-compatible ``schema_migrations`` table
(``version bigint``, ``dirty boolean``, one row). There is no second copy of the
DDL to drift, and ``make migrate`` (the migrate/migrate image) recognises a
database prepared here and vice versa.

    make test-db-up
    make test-integration
"""

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app_template.connectors.postgres import Pool

DSN_ENV = "TEST_PG_DSN"

# Matches the postgres service in docker-compose.yml (host port 5434), so a
# developer who ran `make test-db-up` needs no further setup.
DEFAULT_DSN = "postgresql://postgres:postgres@127.0.0.1:5434/master?sslmode=disable"

CONNECT_TIMEOUT_S = 5

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"

_UP_FILE = re.compile(r"^(\d+)_.+\.up\.sql$")
# Any constant works; it only has to be the same for every test process.
_MIGRATION_LOCK_ID = 7_201_100


async def _reachable(dsn: str) -> bool:
    try:
        conn = await psycopg.AsyncConnection.connect(dsn, connect_timeout=CONNECT_TIMEOUT_S)
    except psycopg.Error:
        return False
    await conn.close()
    return True


async def resolve_dsn() -> str:
    """Return the DSN to test against, or skip the test when none is configured or reachable."""
    dsn = os.environ.get(DSN_ENV)
    if dsn is not None and dsn != "":
        return dsn

    # Nothing configured: fall back to the compose default, but treat an
    # unreachable database as "not set up" instead of a failure.
    if not await _reachable(DEFAULT_DSN):
        pytest.skip(f"no test database: set {DSN_ENV} or run `make test-db-up`")
    return DEFAULT_DSN


def up_migrations() -> list[tuple[int, Path]]:
    """``*.up.sql`` files in db/migrations, sorted by version."""
    found: list[tuple[int, Path]] = []
    for path in MIGRATIONS_DIR.iterdir():
        match = _UP_FILE.match(path.name)
        if match is None:
            continue
        found.append((int(match.group(1)), path))
    found.sort()
    return found


async def migrate_up(conn: psycopg.AsyncConnection[TupleRow]) -> None:
    """Apply pending up-migrations, the way golang-migrate records them."""
    async with conn.transaction():
        # Serialises concurrent test processes; released at commit.
        await conn.execute("select pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
        await conn.execute(
            "create table if not exists schema_migrations (version bigint not null primary key, dirty boolean not null)"
        )
        cur = await conn.execute("select version, dirty from schema_migrations limit 1")
        row = await cur.fetchone()

        current = 0
        if row is not None:
            version, dirty = row
            if dirty:
                pytest.fail(f"schema_migrations is dirty at version {version}: run `make migrate-force v=...`")
            current = int(str(version))

        latest = current
        for version_number, path in up_migrations():
            if version_number <= current:
                continue
            # bytes, not str: the file is trusted repository SQL, and psycopg only
            # accepts a str query as a LiteralString (an injection guard).
            await conn.execute(path.read_bytes())
            latest = version_number

        if latest != current:
            await conn.execute("delete from schema_migrations")
            await conn.execute("insert into schema_migrations (version, dirty) values (%s, false)", (latest,))


async def truncate(conn: psycopg.AsyncConnection[TupleRow]) -> None:
    """Empty every application table and restart identity sequences.

    ``schema_migrations`` is left alone: emptying it would re-run every migration.
    """
    cur = await conn.execute(
        "select tablename from pg_tables where schemaname = 'public' and tablename <> 'schema_migrations'"
    )
    rows = await cur.fetchall()
    if len(rows) == 0:
        return

    tables: list[sql.Composable] = []
    for row in rows:
        tables.append(sql.Identifier("public", str(row[0])))

    # One statement, so foreign keys never block the truncation order.
    stmt = sql.SQL("truncate table {} restart identity cascade").format(sql.SQL(", ").join(tables))
    await conn.execute(stmt)


@asynccontextmanager
async def new() -> AsyncIterator[Pool]:
    """Yield a pool onto a migrated, truncated database (see the module docstring)."""
    dsn = await resolve_dsn()

    try:
        conn = await psycopg.AsyncConnection.connect(dsn, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True)
    except psycopg.Error as exc:
        pytest.fail(f"connect to test database at {dsn}: {exc}")

    try:
        await migrate_up(conn)
        await truncate(conn)
    finally:
        await conn.close()

    pool: Pool = AsyncConnectionPool(dsn, min_size=1, max_size=4, open=False)
    try:
        await pool.open(wait=True, timeout=CONNECT_TIMEOUT_S)
    except PoolTimeout as exc:
        await pool.close()
        pytest.fail(f"open pool to test database at {dsn}: {exc}")

    try:
        yield pool
    finally:
        await pool.close()
