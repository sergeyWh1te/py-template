import psycopg
from psycopg.rows import class_row

from app_template.connectors.postgres import Pool
from app_template.pkg.users.entity import User
from app_template.pkg.users.errors import NotFoundError
from app_template.utils.either import Either, left, right
from app_template.utils.errors import wrap


class UserRepository:
    """Raw-SQL access to the ``users`` table.

    This is where driver exceptions stop: ``psycopg.Error`` (which includes pool
    timeouts) becomes ``left(...)`` with context, and "no row" becomes the domain's
    ``NotFoundError``. Anything else — a bug — propagates to the HTTP recovery
    middleware and is answered with a 500.
    """

    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    async def get(self, user_id: int) -> Either[Exception, User]:
        try:
            async with self._pool.connection() as conn:
                cur = conn.cursor(row_factory=class_row(User))
                await cur.execute("select id from users where id = %s", (user_id,))
                row = await cur.fetchone()
        except psycopg.Error as exc:
            return left(wrap(f"get user {user_id}", exc))

        if row is None:
            return left(NotFoundError(f"get user {user_id}: user not found"))

        return right(row)

    async def create(self) -> Either[Exception, int]:
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute("insert into users default values returning id")
                row = await cur.fetchone()
        except psycopg.Error as exc:
            return left(wrap("create user", exc))

        if row is None:
            return left(RuntimeError("create user: insert returned no id"))

        user_id: int = row[0]
        return right(user_id)
