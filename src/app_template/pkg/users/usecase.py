from app_template.pkg.users.entity import User
from app_template.pkg.users.interfaces import Repository
from app_template.utils.either import Either, is_left, right


class UserUsecase:
    """Business logic of the users domain. Depends on the ``Repository`` port only."""

    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    async def get(self, user_id: int) -> Either[Exception, User]:
        result = await self._repo.get(user_id)
        if is_left(result):
            return result

        user = result.right
        # Business rules on `user` go here, each failure returned as left(...).
        return right(user)
