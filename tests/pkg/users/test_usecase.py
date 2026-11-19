from app_template.pkg.users.entity import User
from app_template.pkg.users.errors import NotFoundError
from app_template.pkg.users.usecase import UserUsecase
from app_template.utils.either import is_left, is_right, left, right
from tests.pkg.users.mocks import RepositoryMock


async def test_get_returns_the_user_from_the_repository() -> None:
    repo = RepositoryMock(get_result=right(User(id=7)))
    uc = UserUsecase(repo)

    result = await uc.get(7)

    assert is_right(result)
    assert result.right == User(id=7)
    assert repo.get_calls == [7]


async def test_get_passes_not_found_through_unchanged() -> None:
    not_found = NotFoundError("get user 7: user not found")
    repo = RepositoryMock(get_result=left(not_found))
    uc = UserUsecase(repo)

    result = await uc.get(7)

    assert is_left(result)
    assert result.left is not_found


async def test_get_passes_other_errors_through_unchanged() -> None:
    failure = RuntimeError("database is down")
    repo = RepositoryMock(get_result=left(failure))
    uc = UserUsecase(repo)

    result = await uc.get(7)

    assert is_left(result)
    assert result.left is failure
