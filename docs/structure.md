# Project structure

How this template is laid out, and where to put new code. The roles match go-template one to one; the names follow
Python packaging (a `src/` layout with one top-level package, `app_template`).

## This repository

```text
py-template/
├── src/app_template/               # the application package (installed into the venv by uv)
│   ├── main.py                     # entry point: signals → config → logger → db → wire → serve → drain → close db
│   ├── __main__.py                 # `python -m app_template`
│   ├── env.py                      # config (pydantic-settings), .env or shell
│   │
│   ├── app/                        # composition root — the only place concretes are constructed
│   │   ├── server.py               # App, run_http_server (uvicorn, drain, forced shutdown)
│   │   ├── routes.py               # router, middleware, routes, handler construction
│   │   ├── repository.py           # repository factory
│   │   └── usecase.py              # usecase factory
│   │
│   ├── connectors/                 # infrastructure adapters
│   │   ├── logger.py               # structlog (json / logfmt text)
│   │   ├── metrics.py              # Prometheus registry + build_info
│   │   └── postgres.py             # psycopg 3 async pool, memoized
│   │
│   ├── http/
│   │   ├── handlers/               # one package per endpoint
│   │   │   ├── health/
│   │   │   ├── metrics/
│   │   │   └── user_example/
│   │   └── middleware/             # request id, access log, recovery, timeout (pure ASGI)
│   │
│   ├── pkg/                        # domain packages, one per domain
│   │   └── users/                  # the reference implementation
│   │       ├── interfaces.py       # Repository + Usecase (typing.Protocol)
│   │       ├── entity.py           # domain dataclasses
│   │       ├── errors.py           # NotFoundError
│   │       ├── usecase.py          # business logic
│   │       └── repository.py       # raw SQL
│   │
│   └── utils/
│       ├── either.py               # Left / Right / is_left / is_right
│       ├── errors.py               # wrap(): context + cause
│       ├── deps.py                 # Logger protocol
│       └── shutdown.py             # signal → shutdown bridge
│
├── tests/                          # mirrors src/app_template/
│   ├── conftest.py                 # `db` and `clean_env` fixtures
│   ├── testdb.py                   # real-Postgres fixture: migrations + truncate, skip/fail split
│   ├── pkg/users/mocks.py          # hand-written, type-checked test doubles
│   └── utils/fake_logger.py
│
├── db/migrations/                  # golang-migrate SQL, up/down pairs (same files as go-template)
├── infra/postgres/                 # local database files (git-ignored, bind-mounted)
├── docs/
│   ├── structure.md                # this file
│   └── code_style.md
├── .github/workflows/checks.yml
├── Dockerfile / docker-compose.yml / Makefile
├── pyproject.toml / uv.lock / .python-version
└── sample.env
```

## Request flow

Each layer depends on a Protocol, never on the implementation below it. That is what keeps handlers and usecases
testable with ten-line fakes.

```text
main.py
    │  builds config, logger, pool, metrics; owns the signals
    ▼
app/                               composition root
    │  routes.py constructs handlers and registers them
    ▼
http/handlers/<name>/              request → domain call → response DTO; maps Left to 404/500
    │  depends on a narrow Protocol it declares (UserGetter)
    ▼
pkg/<domain>/usecase.py            business logic, Either in / Either out
    │  depends on pkg/<domain>/interfaces.Repository
    ▼
pkg/<domain>/repository.py         SQL; driver exceptions → Left, no row → NotFoundError
    │
    ▼
                                   Postgres
```

## Adding a domain

1. Create `src/app_template/pkg/<domain>/` next to `users/`:
   - `entity.py` — frozen, slotted dataclasses
   - `errors.py` — the domain's error classes
   - `interfaces.py` — `Repository` and `Usecase` Protocols, returning `Either`
   - `repository.py` and `usecase.py` — the implementations
2. Wire it into the composition root: a field in `Repositories` (`app/repository.py`) and in `Usecases`
   (`app/usecase.py`), typed as the Protocol.
3. Add a handler in `src/app_template/http/handlers/<name>/handler.py`, declaring the narrow Protocol it needs, and
   register its route in `app/routes.py`.
4. Add a migration (`make migrate-create name=<name>`), then tests: `tests/pkg/<domain>/test_repository.py` with
   the `db` fixture, `mocks.py` with type-checked fakes, usecase and handler tests.

For an external API client, add `src/app_template/clients/<name>/client.py`: it catches the HTTP library's
exceptions and returns `Either`, like a repository does for the database.

## Reference layout

Folders this template does not have yet. Add one only when something needs it — an empty directory is worse than
no directory.

```text
project/
├── api/                  # OpenAPI, protobuf and other schema definitions
├── deployments/          # Kubernetes manifests, Helm charts, Terraform
├── scripts/              # shell helpers
├── src/app_template/
│   ├── clients/          # outbound API clients
│   ├── grpc/             # gRPC handlers, mirroring http/
│   └── workers/          # background consumers, started from main like the HTTP server
└── tests/e2e/            # black-box tests against the running container
```
