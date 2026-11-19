# Code Style

The rules every template in this family shares (go / rust / py / ts), written for Python. Tooling enforces what
it can (ruff `ALL`, mypy `--strict`); the rest is review.

## Imperative, top to bottom

Code reads sequentially: explicit `for` loops, `if` with early return, one thing per line.

* No comprehensions, generator expressions, `map`/`filter`/`functools.reduce` or chained pipelines **for logic**.
* No `any()`/`all()` over a generator — write the loop and return.
* No ternary expressions for control flow.
* No `else` after `return` / `raise` / `continue` (ruff `RET505`–`RET508`).

```python
# Good
def active_ids(users: list[User]) -> list[int]:
    out: list[int] = []
    for user in users:
        if not user.active:
            continue
        out.append(user.id)
    return out


# Bad
def active_ids(users: list[User]) -> list[int]:
    return [u.id for u in users if u.active]
```

Why: the loop has a place for a log line, a breakpoint, an early exit and an error return; the comprehension has
none, and it grows into nested conditionals nobody can debug. ruff's pro-comprehension rules (`PERF401`, `PERF403`,
`SIM108`, `SIM110`, `SIM111`, `FURB118`) are switched off in `pyproject.toml` for this reason.

## Errors are values

Expected failures are returned as `Either` from `app_template.utils.either`; the caller checks `is_left` first and
returns early.

```python
# Good
async def get(self, user_id: int) -> Either[Exception, User]:
    result = await self._repo.get(user_id)
    if is_left(result):
        return result
    user = result.right
    ...
    return right(user)


# Bad — an expected outcome as an exception
async def get(self, user_id: int) -> User:
    user = await self._repo.get(user_id)
    if user is None:
        raise NotFoundError(user_id)
    return user
```

* Never chain: there is no `map`/`bind`, and the `returns` library is banned. Check, return, continue.
* The error side is an `Exception` instance used as a value. Add context where it happens:
  `left(wrap(f"get user {user_id}", exc))` (Go's `fmt.Errorf("...: %w")`), or a domain error with context in its
  message: `left(NotFoundError(f"get user {user_id}: user not found"))`.
* Raise only during initialization (`main`, connector setup) — and convert to `Left` at the connector boundary where
  possible — or for genuine bugs. A bug that escapes a handler becomes a 500 in `RecoveryMiddleware`.
* Catch narrowly, at the boundary where a library raises: `except psycopg.Error` in a repository, `except
  ValidationError` in `env.load`. A broad `except Exception` exists exactly once, in `RecoveryMiddleware`.
* Never return a value together with an error, and never return a half-filled object on failure.

## Interfaces at the consumer

* Interfaces are `typing.Protocol`, declared by the code that **uses** them, containing only the methods it calls.
  The concrete class does not inherit from the Protocol — structural typing matches it, and mypy checks the match
  where the composition root passes it in.
* Accept Protocols in constructors; construct concrete classes only in the composition root (`app/`).
* Constructor injection only. No module-level singletons, no service locators — except the memoized database pool
  and config, mirroring go-template.

```python
class UserGetter(Protocol):  # declared next to the handler that needs it
    async def get(self, user_id: int) -> Either[Exception, User]: ...


class UserExampleHandler:
    def __init__(self, log: Logger, users: UserGetter) -> None: ...
```

## Domain errors

* Defined in the domain package (`pkg/<domain>/errors.py`).
* Repositories translate driver outcomes into them (`fetchone() is None` → `NotFoundError`).
* Handlers map them to status codes with `isinstance` and never import the database driver.

## Data and types

* Entities and value objects: `@dataclass(frozen=True, slots=True)`. pydantic only at the edges — config
  (`pydantic-settings`) and HTTP DTOs.
* Do not pass HTTP DTOs across layers. Small inputs become scalar parameters (`user_id`); large ones become a domain
  dataclass built in the handler.
* Everything is annotated; mypy runs `--strict` over `src/` and `tests/`. `Any` is not used in our own signatures —
  prefer `object` and narrow. `# type: ignore[code]` only with an error code and a reason.
* Check strings for emptiness with `== ""` / `!= ""` and collections with `len(x) == 0`, so the type is visible at
  the comparison (the same rule as go-template). `None` is checked with `is None`.
* Absolute imports only.

## Constructors and visibility

* Handlers, usecases and repositories are classes with an `__init__` that only stores dependencies — no I/O.
* Attributes holding dependencies are private (`self._repo`). Consumers see the Protocol, never the attribute.
* Connectors expose module functions (`connect`, `close`, `new`) and return `Either` from anything that can fail.

## Logging

* Structured: `log.error("get user", user_id=user_id, error=str(err))`. The event is a constant string; values go in
  fields. Never an f-string message.
* Expected outcomes (404) at warning, faults at error with `exc_info=err`.

## Unit testing

* Test names use underscores: `test_get_missing_user_returns_not_found`.
* Mocks are hand-written classes in `tests/pkg/<domain>/mocks.py`, with a `type[Protocol]` assignment so mypy
  checks them against the port. Prefer them over `unittest.mock`, which silently accepts any call.
* Database tests use the `db` fixture (`tests/testdb.py`) — a real Postgres with the real migrations, truncated per
  test. Do not mock SQL.
* Handlers are tested through FastAPI with `httpx.ASGITransport` — status, body and what was logged.

## Long-term support and refactoring

* A TODO always links to the task that will do it:

  ```python
  # Bad
  # TODO: remove this method

  # Good
  # TODO(https://tracker.example.com/TASK-123): remove once clients use /v2/example
  ```

* When something public is going away, mark it first (`warnings.deprecated` / `typing_extensions.deprecated`) and
  keep a fallback until the next major version.
