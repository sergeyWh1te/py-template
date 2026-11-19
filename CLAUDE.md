# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It is the Python sibling of `go-template` (and of `rust-template` / `ts-template`): the same layers, endpoints,
shutdown behaviour and tooling targets, expressed in idiomatic-but-strict Python. Where a decision differs from Go,
the reason is written down here.

## Commands

**Setup (first time):**
```sh
make tools           # uv sync --frozen: Python 3.15 venv in .venv with runtime + dev tools (ruff, mypy, pytest, pip-audit)
cp sample.env .env   # the Makefile does `-include .env`; migration targets and `make serve` need the PG_* vars
make up              # docker compose up -d (postgres + service)
make migrate         # apply migrations (migrate/migrate image, on the compose network)
```

**Build and run:**
```sh
make serve      # run the service on the host (uv run app-template), stamping COMMIT from git
make build      # uv build --wheel -> dist/ (proves the package builds; the image does its own install)
make run        # make up + make migrate
make up / down / logs / up-rebuild    # docker compose lifecycle
make docker-build                     # build the image with the COMMIT build-arg
```
Inside the venv the entry point is the `app-template` console script, or `python -m app_template`. Never run
`python src/app_template/main.py`: it puts the package directory on `sys.path`, and the `app_template.http`
subpackage would shadow the stdlib `http` module.

**Linting and formatting:**
```sh
make full-lint     # fmt + lint — use this before committing
make fmt           # ruff import sorting + ruff format (rewrites files)
make check-format  # same, but --check/--diff and non-rewriting (what CI runs)
make lint          # ruff check (ALL rules, short opt-out list) + mypy --strict over src/ and tests/
make typecheck     # mypy alone
make fix-lint      # ruff check --fix
make vulncheck     # pip-audit over every locked package (runtime + dev), from the hashed uv.lock export
make outdated      # direct dependencies with newer releases
make actionlint    # static check of .github/workflows (rhysd/actionlint image)
```

**Tests:**
```sh
make test-db-up        # start just Postgres (host port 5434) — fixtures need a real database
make test-integration  # run everything against it — fails if the DB is missing
make test              # same tests, but DB-backed ones skip when none is running
make cover             # test-integration + coverage (term + coverage.xml), fails under the floor
make test-db-down      # stop it
make test-db-reset     # wipe the data directory and start fresh
```

Single file / single test: `uv run pytest tests/pkg/users/test_repository.py`,
`uv run pytest -k get_missing_user`. Add `TEST_PG_DSN=...` to make DB tests mandatory.

Postgres data is a **bind mount** at `infra/postgres/`, not a named volume, so the local database is visible in the
working tree. Consequences: `docker compose down -v` does **not** clear it (`-v` only removes named volumes) — use
`make test-db-reset`; `PGDATA` points at the `pgdata` subdirectory so Postgres creates it with the ownership initdb
requires; and `infra/postgres/.gitignore` ignores everything but itself, so the mount point exists on a fresh clone
while the data never enters git. `infra` is in `.dockerignore` — otherwise the database would be sent as build
context.

**Ports.** All four templates run side by side: this one publishes Postgres on **5434** and the app on **8082**,
container names are prefixed `py_template_`. Inside containers the app listens on 8080 and Postgres on 5432 as
usual; only the host mappings and `sample.env` defaults differ.

**Database migrations** (all target `db/migrations`, run by the `migrate/migrate` image as the compose `migrate`
service, URL assembled from `PG_*` in `.env`):
```sh
make migrate                    # apply all pending migrations
make migrate-down               # roll back all migrations
make migrate-step-down          # roll back one migration
make migrate-version            # print current migration version
make migrate-force v=<version>  # force-set version (recover from dirty state)
make migrate-create name=<name> # create a new timestamped up/down migration pair (owned by your user)
make migrate-drop               # drop everything in the database
```
The migration files are golang-migrate format and identical to go-template's. The binary runs in Docker so nobody
has to install Go tooling for a Python project; the `migrate` service sits behind a compose profile, so
`docker compose up` never starts it. Credentials in `PG_*` go into a URL here — avoid `@`, `/`, `:` in the local
password or URL-encode it.

**Mocks:** none are generated. Test doubles are small hand-written classes in `tests/pkg/users/mocks.py`, statically
checked against the Protocols (see "Tests").

## Architecture

Clean Architecture / ports-and-adapters, mirroring go-template. The request flow is:

```
src/app_template/main.py
  → app_template/app/                 (composition root — wires everything)
    → app_template/http/handlers/     (HTTP handlers)
      → app_template/pkg/<domain>/usecase.py     (business logic)
        → app_template/pkg/<domain>/repository.py (DB access, raw SQL)
```

### Key structural conventions

**`app/`** — the composition root, and the **only** place concrete classes are constructed. `server.py` defines `App`
and `run_http_server`; `routes.py` builds the FastAPI router, registers middleware and routes and constructs the
handlers; `repository.py` and `usecase.py` are factory modules (`new_repositories(pool)`, `new_usecases(repos)`)
returning frozen dataclasses whose fields are typed as the domain **Protocols**, not the concrete classes. When
adding a domain, wire it in all three. Go splits `App`'s methods across files of one package; Python cannot, so
`routes.register_routes(api, log, metrics, usecases)` is a function and `App.register_routes` delegates to it (this
also avoids a `server` ↔ `routes` import cycle).

**`pkg/<domain>/`** — one package per domain (`users` is the reference implementation):
- `interfaces.py` — `Repository` and `Usecase` as `typing.Protocol`. `Repository` lives here because its consumer
  (the usecase) lives here; `Usecase` is the domain's published port, the type the composition root stores.
- `entity.py` — domain dataclasses (`frozen=True, slots=True`). No pydantic, no HTTP, no DB types.
- `errors.py` — domain errors (`NotFoundError`). Returned inside `Left`, never raised.
- `usecase.py` — `UserUsecase(repo: Repository)`.
- `repository.py` — `UserRepository(pool)`, raw SQL over the psycopg pool. This is where driver exceptions stop:
  `psycopg.Error` (pool timeouts included) becomes `left(wrap("get user 1", exc))`, "no row" becomes
  `left(NotFoundError(...))`. Never a value together with an error, never a raised expected failure.

**`http/handlers/<name>/handler.py`** — one package per endpoint. A handler is a class with constructor-injected
dependencies and an `async def handle(self) -> Response`. It depends on the `Logger` protocol and on a **narrow
Protocol it declares itself** — `UserExampleHandler` asks for `UserGetter` (just `get`), not the whole `Usecase`.
`routes.py` passes `usecases.user` (typed `users.Usecase`) into it, so mypy proves the two are compatible exactly at
the wiring point. Handlers convert entities to response DTOs (`UserResponse`, pydantic) and map errors:

| `Left` value | status | body | log level |
|---|---|---|---|
| `NotFoundError` | 404 | `{"error":"user not found"}` | warning |
| anything else | 500 | `{"error":"internal server error"}` | error (with traceback) |

Handlers never import psycopg — the domain error is the contract.

**`http/middleware/`** — pure ASGI middleware (not Starlette's `BaseHTTPMiddleware`, which wraps bodies in extra
tasks and breaks contextvars/cancellation): `RequestIDMiddleware` (reuses a sane incoming `X-Request-Id`, else
uuid4, echoes it in the response, stores it in `scope["state"]`), `AccessLogMiddleware` (one structured line per
request), `RecoveryMiddleware` (any exception from a handler → logged with traceback, generic JSON 500 — chi's
`Recoverer`), `TimeoutMiddleware` (10s per request → 503). `add_middleware` *prepends*, so `routes.py` adds them in
reverse; the effective order is RequestID → AccessLog → Recovery → Timeout → route, which is why the access log
sees both the id and the recovered status.

**`connectors/`** — infrastructure adapters: `postgres` (psycopg 3 `AsyncConnectionPool`), `logger` (structlog),
`metrics` (prometheus_client registry + build-info counter).

Two rules hold across the connectors, and both exist because breaking them hides outages:
- **Never cache a failed connection.** The shared pool is memoized behind an `asyncio.Lock` and stored only after
  `pool.open(wait=True, timeout=5)` succeeded; on failure the pool is closed and `connect` returns `Left`, so the
  next call dials again. `functools.cache`/`lru_cache` are wrong for this (they would happily memoize a returned
  error value — the Python face of Go's `sync.Once` bug). `postgres.close()` clears the handle, so a later `connect`
  dials a fresh pool instead of returning the closed one. `env.read()` follows the same rule.
- **Register metrics into the app registry**, via `registry=`. prometheus_client's default is the global `REGISTRY`,
  which `/metrics` does not serve — the metric silently never appears. The process, platform and GC collectors are
  registered into the app registry explicitly for the same reason. `/metrics` is a plain route over
  `generate_latest(registry)` rather than `make_asgi_app` mounted at `/metrics`, because a Starlette `Mount`
  redirects `/metrics` → `/metrics/`.

Pool settings mirror go's `database/sql` limits: `max_size=25` (max open), `min_size=10` (kept while idle — psycopg's
closest equivalent to `MaxIdleConns`), `max_lifetime=30m`, `max_idle=5m`, checkout timeout 5s (below the 10s request
timeout, so a saturated pool shows up as a logged 500, not a timeout), `check=check_connection` on checkout.
Prepared statements stay **on**: psycopg sends parameters with the extended protocol and auto-prepares after
`prepare_threshold` (default 5) runs. Set `prepare_threshold=None` only behind a transaction-mode pooler such as
pgbouncer. The DSN is built with `psycopg.conninfo.make_conninfo`, which quotes and escapes every value — a password
with spaces, quotes or `@` cannot break or inject into the connection string. `PgConfig.password` is a `SecretStr`,
so printing the config never shows it.

`logger.new(cfg)` returns a structlog `FilteringBoundLogger` **instance** built with `structlog.wrap_logger`;
`structlog.configure` is never called, because it is process-global state (and leaks between tests). An unrecognized
`LOG_LEVEL` falls back to info rather than refusing to start. The build commit is read from the `COMMIT` environment
variable, which the Dockerfile bakes into the image from the `COMMIT` build-arg (`make docker-build`, `make
up-rebuild`, CI pass `git rev-parse HEAD`); `make serve` exports it from git. Python has no link-time stamping, so
the image environment is the equivalent of go's `-ldflags -X`. `COMMIT` is deliberately **not** in `sample.env`: an
empty `COMMIT=` line would reach the container through `env_file` and blank the baked-in value.

**`utils/`**
- `either.py` — the project's `Either` (see "Errors are values").
- `errors.py` — `wrap(context, cause)`: Go's `fmt.Errorf("%s: %w")`. `str()` reads `"get user 1: connection refused"`
  and `__cause__` keeps the original for the traceback.
- `deps.py` — the `Logger` Protocol (`debug/info/warning/error(event, **kw)`), the slog-shaped interface handlers
  and middleware accept (go's `deps.Logger`). structlog's logger satisfies it structurally; tests pass `FakeLogger`.
- `shutdown.py` — `Shutdown`, the bridge from signals to the server (see "Concurrency model").

**`env.py`** — pydantic-settings, two `BaseSettings` classes (`AppConfig`, `PgConfig`) with explicit
`validation_alias` per variable, combined in a frozen `Config`. `load(env_file)` builds it and returns
`Either[Exception, Config]` (a `ValidationError` is a `Left`, not an exception escaping into `main`); `read()` is the
memoized, process-wide version (success only — see above). Every variable is listed in `sample.env`; add new ones
there too. Required: `APP_NAME`, `PG_HOST/PORT/USERNAME/PASSWORD/DATABASE`; everything else has a default.

`READ_ENV_FROM_SHELL=true` (`1`/`t`/`true`, Go's `ParseBool` spellings) skips the file entirely and takes config
from the environment — that is how the service runs in Docker and CI, where no `.env` exists. A missing `.env` is
tolerated either way. Shell variables override the file. `extra="ignore"` because one `.env` feeds both classes.

**`tests/testdb.py`** — fixtures for tests that need a real database, exposed as the `db` fixture in
`tests/conftest.py`. Each test gets a pool onto a schema with `db/migrations/*.up.sql` applied and every table
truncated with `restart identity cascade`, so ids are predictable. It applies the real migrations rather than a copy
of the DDL, so the test schema cannot drift from production. The chosen migration mechanism: executing the
`*.up.sql` files in version order inside one transaction under `pg_advisory_xact_lock`, recorded in a
**golang-migrate-compatible** `schema_migrations (version bigint, dirty boolean)` single-row table. No extra
dependency, no Docker inside tests, and `make migrate-version` reads a test database correctly (and vice versa). A
dirty row fails the test with a pointer to `make migrate-force`.

Its skip/fail split is deliberate: with no database reachable and `TEST_PG_DSN` unset the test **skips**, so
`make test` passes on a laptop with nothing running; when `TEST_PG_DSN` *is* set but the database is unusable it
**fails**, so a broken CI service container can never look like a green run. CI therefore runs with `TEST_PG_DSN`
set (`make cover`), never plain `make test`.

`TEST_PG_DSN` is deliberately `unexport`ed in the Makefile — the Makefile does a blanket `export`, and exporting it
would make every plain `make test` look like a configured database, turning the skips into failures. The same
blanket export pushes `.env` into the test process, which is why config tests use the `clean_env` fixture.

### Errors are values

Expected failures — not found, database down, invalid config — are **returned** as `Either[Exception, T]` from
`utils/either.py`, never raised:

```python
result = await self._repo.get(user_id)
if is_left(result):
    return result  # early return; nothing else on this path
user = result.right  # TypeIs narrowed it to Right[User]
```

- fp-ts naming on purpose (`Left`/`Right`, `left()`/`right()`, `is_left()`/`is_right()`, `.left`/`.right`), so the
  code reads the same as ts-template's `E.isLeft(x)` and the pattern transfers across the four templates.
- `is_left` returns `TypeIs[Left[E]]` (not `TypeGuard`), so mypy narrows **both** branches — after the early return
  `.right` type-checks without a cast. `match`/`case Left(left=err)` works too.
- The module has no `map`/`bind`/`fold` and the `returns` library is banned in `pyproject.toml`
  (`flake8-tidy-imports.banned-api`): combinator pipelines are exactly what the imperative style rules out.
- The error side is an `Exception` instance used as a value — it carries a message, `__cause__` and a traceback for
  the log, and `isinstance(err, NotFoundError)` is the `errors.Is` of this codebase. Repositories put context into
  the error (`"get user 1: user not found"`), so a domain error never needs unwrapping.
- Exceptions are for the two places that cannot return a value: initialization (`main`, connectors — and even there
  they are converted to `Left` at the connector boundary) and bugs. A bug that escapes a handler is caught by
  `RecoveryMiddleware` and answered with a 500.

### Logging

structlog, key/value. Log an event name plus fields: `log.error("get user", user_id=1, error=str(err))`, never an
f-string message. `LOG_FORMAT=json` selects `JSONRenderer`; anything else gives logfmt-style text
(`LogfmtRenderer`, the closest thing to slog's `TextHandler`). Processors: level, ISO-8601 UTC timestamp,
`format_exc_info` (so `exc_info=err` renders a traceback in both formats). `LOG_LEVEL` is
`debug`/`info`/`warn`/`warning`/`error`, case-insensitive. uvicorn's own access log is off (`access_log=False`)
and `log_config=None` stops it from installing its logging config; `logging.basicConfig` is banned by ruff.

### Concurrency model

`main.run()` is the whole lifecycle on one asyncio loop: signal handlers → `env.read()` → logger → `postgres.connect`
→ wire → `App.run_http_server` → release signals → `postgres.close()`. Three details, each a real bug in the go
version at some point, and each with a Python-specific twist:

- **uvicorn must not own the signals.** Stock `uvicorn.Server.serve()` traps SIGINT/SIGTERM itself and, after it
  returns, **re-raises the captured signal** — with SIGTERM's default disposition that kills the process before the
  pool is closed, and SIGINT under `asyncio.run` cancels `main`. `app/server.py` subclasses `Server` with a no-op
  `capture_signals`; `main` installs `loop.add_signal_handler(SIGINT/SIGTERM, shutdown.request)` instead.
- **A fresh drain budget.** The first signal sets `server.should_exit`; uvicorn stops accepting, then waits up to
  `timeout_graceful_shutdown=15` *counted from that moment* for in-flight requests (`DEFAULT_SHUTDOWN_TIMEOUT_S`),
  and cancels whatever is left. There is no already-cancelled context to accidentally reuse. A second signal during
  the drain cancels in-flight requests at once (`force_exit` alone is not enough — uvicorn's final `wait_closed()`
  still waits for open connections — so `_watch` cancels the request tasks, exactly what uvicorn does when the budget
  runs out).
- **Release the signal handlers after the drain, then close the pool.** `release_signals` removes the loop handlers
  and sets `SIG_DFL` (not Python's `default_int_handler`, whose `KeyboardInterrupt` could be caught), so a further
  Ctrl-C during cleanup kills the process outright. Only then `postgres.close()`: handlers still finishing would
  otherwise lose their connections. A `try/finally` closes the pool on the exceptional path too.

A failed bind is `sys.exit(1)` inside uvicorn; `run_http_server` catches that `SystemExit` and returns it as a `Left`.
The 10s read/write timeouts of go's `http.Server` have no uvicorn equivalent; `TimeoutMiddleware` enforces a 10s
budget per request instead (503, like Go's `http.TimeoutHandler`), and `timeout_keep_alive=60` is the idle timeout.
Slow-header (slowloris) protection belongs to the reverse proxy in front of uvicorn.

**`stop_grace_period` in docker-compose must exceed `DEFAULT_SHUTDOWN_TIMEOUT_S`.** Docker's default grace period
is 10s against the app's 15s drain budget, so Docker would SIGKILL the container mid-drain; the compose file sets
30s. A clean stop shows exit code 0, not 137. The Dockerfile uses exec-form `CMD`, so Python is PID 1 and receives
SIGTERM directly.

For new background work, run it as a task created in `main` (or in a connector), give it the `Shutdown` events to
watch, and await/cancel it before `postgres.close()` — the same ordering rule as the HTTP server.

### Dependencies

uv manages everything: `.python-version` pins the interpreter (3.15), `pyproject.toml` pins direct dependencies
**exactly** (`==`; this is an application, there are no downstream consumers to stay compatible with), and `uv.lock`
pins the transitive tree with hashes. All Makefile/CI invocations use `uv run --frozen` / `UV_FROZEN=1`, so a tool
run never rewrites the lock and a stale lock fails loudly. Change dependencies with `uv add pkg==X.Y.Z` (or edit
`pyproject.toml` + `make lock`), then `make vulncheck`. `make outdated` lists newer releases.

Stack: FastAPI + uvicorn (h11), psycopg 3 + psycopg_pool (async, raw SQL — no ORM, like sqlx), pydantic-settings,
structlog, prometheus_client; dev: pytest + pytest-asyncio (auto mode) + pytest-cov + httpx, ruff, mypy, pip-audit.

## Code style rules (from `docs/code_style.md`)

- **Imperative.** Explicit `for` loops and `if`/early return. No comprehensions, `map`/`filter`/`reduce`,
  `any()/all()` over generator expressions or chained pipelines for logic. No ternaries for control flow. No `else`
  after `return` (ruff `RET505` enforces it). ruff rules that push the other way (`PERF401`, `PERF403`, `SIM108`,
  `SIM110`, `SIM111`, `FURB118`) are switched off on purpose — the comprehension ban itself is a review rule, ruff
  cannot express it.
- **Errors are values** (above). Raise only during initialization or for bugs. Never raise an expected failure from a
  repository, usecase or handler; never catch broadly except at the HTTP boundary (`RecoveryMiddleware`).
- **Interfaces at the consumer.** `typing.Protocol`, declared by the code that *uses* it, as narrow as that code
  needs. Accept Protocols in constructors; construct concretes only in `app/`. Constructor injection only, no module
  globals — except the memoized pool (`connectors/postgres.py`) and config (`env.py`), mirroring go.
- **No HTTP DTOs across layers.** Handlers build domain values from requests and response DTOs from entities.
- Domain errors live in the domain package; repositories translate driver errors into them; handlers never import
  the driver.
- Frozen, slotted dataclasses for entities and value objects; pydantic only at the edges (config, HTTP DTOs).
- Absolute imports only (`ban-relative-imports = "all"`).
- TODO comments must include a link to the tracking task.
- Test names use underscores (`test_get_missing_user_returns_not_found`), which pytest requires anyway.

## Linting notes

ruff with `select = ["ALL"]` and a short, commented opt-out list in `pyproject.toml`: missing-docstring rules (D1xx —
docstrings are written where they explain a *why*), the formatter conflicts (`COM812`, `ISC001`), `CPY`, the
pro-comprehension rules listed above, and `TC` (type-checking-only imports: FastAPI and pydantic read annotations at
runtime, so moving imports under `TYPE_CHECKING` or making them `lazy` breaks them invisibly). Tests additionally
allow `assert` (`S101`), literal expected values (`PLR2004`), private access (`SLF001`) and the throwaway test DB
credentials (`S105`/`S106`). Line length 120. Any new ignore needs a reason next to it.

ruff's formatter also formats ```` ```python ```` blocks inside Markdown (`README.md`, `CLAUDE.md`, `docs/`), so
`make check-format` covers the documentation examples too — run `make fmt` after editing them.

mypy runs with `strict = true` plus `warn_unreachable` and the `redundant-expr`, `truthy-bool`,
`possibly-undefined`, `ignore-without-code` error codes, over **both `src/` and `tests/`** — test doubles are typed
too. The pydantic mypy plugin is on (`init_typed`, `init_forbid_extra`). A `# type: ignore` needs an error code and,
in review, a reason.

## Tests

- **Domain against a real DB:** `tests/pkg/users/test_repository.py` — the four go cases (create returns id 1, get
  returns the created user, missing user is `NotFoundError`, each test starts clean) plus driver errors becoming
  `Left` — the worked example of the `db` fixture.
- **Usecase with a mocked repository**, **handler 200/404/500 with a mocked usecase** (httpx `ASGITransport`, no
  server), middleware, routes wiring (with fakes, and full-stack against the DB), the server's drain and forced
  shutdown on a real port, `main.run()` end-to-end (real DB, SIGTERM → drain → exit 0 → pool closed → `SIG_DFL`),
  logger level parsing and rendering, config loading and memoization, connectors.
- Mocks are hand-written dataclasses in `tests/pkg/users/mocks.py` with canned results and recorded calls, not
  `unittest.mock`: `_usecase_check: type[users.Usecase] = UsecaseMock` makes mypy fail the moment a mock drifts from
  its Protocol, which `create_autospec`/`MagicMock` would hide. `tests/utils/fake_logger.py` records log calls.
- pytest runs with `filterwarnings = error`, `--strict-markers`, `--strict-config`; asyncio tests need no marker
  (`asyncio_mode = "auto"`), each with its own loop.

## CI

`.github/workflows/checks.yml` runs five jobs on PRs and pushes to `main`: `format` (`make check-format`), `lint`
(`make lint`: ruff + mypy), `vulncheck` (`make vulncheck`), `test` and `docker`. uv comes from
`astral-sh/setup-uv` pinned to the Makefile's `UV_VERSION`; Python comes from `.python-version`. Validate edits with
`make actionlint`.

`test` is gated behind `vulncheck` (`needs:`) so runner time is not spent on a tree with known vulnerable
dependencies. It brings up a Postgres service container, sets `TEST_PG_DSN` and runs **`make cover`** — the
integration run (never plain `make test`, which would let the DB tests skip silently) with coverage. The total goes
into `$GITHUB_STEP_SUMMARY` (`coverage report --format=total`) and `coverage.xml` is uploaded with
`actions/upload-artifact` — no external coverage service, no token. **Coverage floor: 70%**
(`[tool.coverage.report] fail_under` in `pyproject.toml`); the suite is at ~95% with the database and ~87% without it.
The floor is deliberately modest — it catches large untested additions or a suite that mostly stopped running, not
every untested line; raise it if you want it to ratchet. Skipped database tests are *not* its job: with
`TEST_PG_DSN` set they fail outright (see `tests/testdb.py`).

`docker` builds the image with buildx and the GHA cache (no push), asserts `/app/.venv/bin/app-template` exists,
then starts Postgres plus the image on a private network and curls `/health` and checks `/metrics` for the
build_info series.

Tool versions in the workflow `env:` block must stay in step with the Makefile variables and the Dockerfile.
