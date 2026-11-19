from dataclasses import dataclass

from app_template.connectors.postgres import Pool
from app_template.pkg.users import interfaces as users
from app_template.pkg.users.repository import UserRepository


@dataclass(frozen=True, slots=True)
class Repositories:
    user: users.Repository


def new_repositories(pool: Pool) -> Repositories:
    return Repositories(user=UserRepository(pool))
