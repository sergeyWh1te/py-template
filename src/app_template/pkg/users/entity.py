"""Domain entities of the users domain. No HTTP or database types in here."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    id: int
