"""Postgres connection pool (psycopg 3 + psycopg_pool, async, raw SQL — no ORM).

Two rules, both because breaking them hides outages:

* **Never cache a failed connection.** The shared pool is memoized behind a lock
  and stored only after it has proven it can connect; on failure it is closed and
  the next ``connect`` dials again. (``functools.cache``/``sync.Once``-style
  memoization would hand back the first failure, or a dead pool, forever.)
* **Close after drain.** ``close`` is called by ``main`` only once the HTTP server
  has finished its in-flight requests.
"""

import asyncio

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import TupleRow
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app_template.env import PgConfig
from app_template.utils.either import Either, left, right
from app_template.utils.errors import wrap

type Pool = AsyncConnectionPool[AsyncConnection[TupleRow]]

MAX_OPEN_CONNS = 25
# Kept open while idle (psycopg_pool's floor). Below MAX_OPEN_CONNS by design:
# idle connections are a subset of open ones.
MAX_IDLE_CONNS = 10
CONN_MAX_LIFETIME_S = 30 * 60.0
CONN_MAX_IDLE_TIME_S = 5 * 60.0
PING_TIMEOUT_S = 5.0
# How long a request waits for a free connection before failing. Below the 10s
# request timeout so a saturated pool surfaces as a logged 500, not a timeout.
CHECKOUT_TIMEOUT_S = 5.0

_lock = asyncio.Lock()
_pool: Pool | None = None


def conninfo(cfg: PgConfig) -> str:
    # make_conninfo quotes and escapes every value, so a password containing
    # spaces, quotes or '@' cannot break (or inject into) the connection string —
    # the libpq-format equivalent of URL-encoding credentials.
    return make_conninfo(
        host=cfg.host,
        port=str(cfg.port),
        user=cfg.username,
        password=cfg.password.get_secret_value(),
        dbname=cfg.database,
        sslmode=cfg.ssl_mode,
        connect_timeout=str(int(PING_TIMEOUT_S)),
    )


def new_pool(dsn: str) -> Pool:
    # Prepared statements stay on: psycopg sends parameters with the extended
    # protocol and auto-prepares a query after `prepare_threshold` (default 5)
    # executions. Set `kwargs={"prepare_threshold": None}` only behind a
    # transaction-mode pooler such as pgbouncer — not here.
    return AsyncConnectionPool(
        dsn,
        min_size=MAX_IDLE_CONNS,
        max_size=MAX_OPEN_CONNS,
        max_lifetime=CONN_MAX_LIFETIME_S,
        max_idle=CONN_MAX_IDLE_TIME_S,
        timeout=CHECKOUT_TIMEOUT_S,
        # Validate a connection on checkout, so a server restart costs one retry
        # inside the pool instead of an error in a request.
        check=AsyncConnectionPool.check_connection,
        open=False,
        name="app",
    )


async def connect(cfg: PgConfig) -> Either[Exception, Pool]:
    """Return the shared pool, opening it on first success."""
    global _pool  # noqa: PLW0603 — the memoized DB handle is one of the two sanctioned globals.

    async with _lock:
        if _pool is not None:
            return right(_pool)

        pool = new_pool(conninfo(cfg))
        try:
            # wait=True blocks until min_size connections are up: this is the
            # startup ping, bounded by PING_TIMEOUT_S.
            await pool.open(wait=True, timeout=PING_TIMEOUT_S)
        except PoolTimeout as exc:
            # Drop the pool so a later call dials again instead of handing back
            # one that never worked.
            await pool.close()
            return left(wrap(f"could not connect to postgres at {cfg.host}:{cfg.port}", exc))

        _pool = pool
        return right(pool)


async def close() -> None:
    """Close the shared pool and forget it, so a later ``connect`` dials afresh.

    psycopg_pool waits for connections that are checked out, so call this only
    after request handlers have drained. Safe to call when nothing was opened.
    """
    global _pool  # noqa: PLW0603 — see connect.

    async with _lock:
        if _pool is None:
            return
        pool = _pool
        _pool = None
        await pool.close()
