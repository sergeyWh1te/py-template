from dataclasses import dataclass

from app_template.app.repository import Repositories
from app_template.pkg.users import interfaces as users
from app_template.pkg.users.usecase import UserUsecase


@dataclass(frozen=True, slots=True)
class Usecases:
    user: users.Usecase


def new_usecases(repos: Repositories) -> Usecases:
    return Usecases(user=UserUsecase(repos.user))
