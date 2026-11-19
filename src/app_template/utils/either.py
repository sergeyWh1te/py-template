"""A minimal Either, named after fp-ts so the shape reads the same across the templates.

Expected failures are returned, not raised::

    result = await repo.get(user_id)
    if is_left(result):
        return result          # or map the error, log it, ...
    user = result.right        # narrowed to Right[User] here

The module is deliberately tiny: there is no ``map``/``bind``/``fold``. Chaining
combinators is exactly what the imperative style rules out (docs/code_style.md) —
the caller checks ``is_left`` first, returns early, and carries on with plain code.
That is also why the third-party ``returns`` library is banned in pyproject.toml.
"""

from dataclasses import dataclass
from typing import TypeIs


@dataclass(frozen=True, slots=True)
class Left[E]:
    """The failure branch. ``left`` holds the error value."""

    left: E


@dataclass(frozen=True, slots=True)
class Right[A]:
    """The success branch. ``right`` holds the result value."""

    right: A


type Either[E, A] = Left[E] | Right[A]


def left[E](value: E) -> Left[E]:
    return Left(value)


def right[A](value: A) -> Right[A]:
    return Right(value)


def is_left[E, A](either: Either[E, A]) -> TypeIs[Left[E]]:
    # TypeIs (not TypeGuard) narrows both branches: after `if is_left(x): return`
    # the type checker knows `x` is a Right.
    return isinstance(either, Left)


def is_right[E, A](either: Either[E, A]) -> TypeIs[Right[A]]:
    return isinstance(either, Right)
