from psycopg_pool import AsyncConnectionPool

from app_template.connectors.postgres import Pool
from app_template.pkg.users.entity import User
from app_template.pkg.users.errors import NotFoundError
from app_template.pkg.users.repository import UserRepository
from app_template.utils.either import is_left, is_right
from app_template.utils.errors import WrappedError


async def test_create_returns_a_new_id(db: Pool) -> None:
    repo = UserRepository(db)

    result = await repo.create()

    assert is_right(result)
    # Truncate restarts identity, so the first row of a clean schema is id 1.
    assert result.right == 1


async def test_get_returns_the_created_user(db: Pool) -> None:
    repo = UserRepository(db)

    created = await repo.create()
    assert is_right(created)

    result = await repo.get(created.right)

    assert is_right(result)
    assert result.right == User(id=created.right)


async def test_get_missing_user_returns_not_found(db: Pool) -> None:
    repo = UserRepository(db)

    result = await repo.get(404)

    assert is_left(result)
    assert isinstance(result.left, NotFoundError)
    assert "404" in str(result.left)


# Each test gets a truncated schema; this asserts that isolation rather than
# assuming it, since every other test depends on it.
async def test_each_test_starts_from_a_clean_table(db: Pool) -> None:
    repo = UserRepository(db)

    result = await repo.create()

    assert is_right(result)
    assert result.right == 1


async def test_driver_errors_become_lefts_not_exceptions() -> None:
    # A pool that was never opened: every checkout raises psycopg_pool.PoolClosed,
    # a psycopg.Error — the same path a dead database takes. No server needed.
    closed: Pool = AsyncConnectionPool("", open=False)
    repo = UserRepository(closed)

    got = await repo.get(1)
    created = await repo.create()

    assert is_left(got)
    assert isinstance(got.left, WrappedError)
    assert not isinstance(got.left, NotFoundError)
    assert str(got.left).startswith("get user 1: ")
    assert is_left(created)
    assert str(created.left).startswith("create user: ")
