# py-template

A production-ready Python service skeleton for building HTTP APIs quickly and correctly. It comes pre-wired with
Postgres, structured logging, Prometheus metrics, database migrations and a clean layered architecture — the Python
sibling of `go-template`, with the same layers, endpoints, shutdown behaviour and `make` targets.

Errors are values (a small fp-ts-style `Either`), code is imperative, interfaces are `typing.Protocol` declared by
their consumers, and everything is wired in one composition root. `mypy --strict` and ruff (`ALL` rules) gate CI.

## What's included

| Concern | Library |
|---|---|
| Runtime / packaging | Python 3.15, [uv](https://docs.astral.sh/uv/) (`uv.lock`, `src/` layout) |
| HTTP | [FastAPI](https://fastapi.tiangolo.com/) on [uvicorn](https://www.uvicorn.org/) |
| Database | [psycopg 3](https://www.psycopg.org/psycopg3/) + psycopg_pool (async, raw SQL, no ORM) |
| Migrations | [golang-migrate](https://github.com/golang-migrate/migrate) via the `migrate/migrate` image |
| Config | [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) (`.env` or shell) |
| Logger | [structlog](https://www.structlog.org/) (JSON or logfmt text, via `LOG_FORMAT`) |
| Metrics | [prometheus_client](https://github.com/prometheus/client_python) |
| Errors | own `app_template.utils.either` (`Left`/`Right`/`is_left`) |
| Tests | pytest, pytest-asyncio, pytest-cov, httpx |
| Lint / format / types | [ruff](https://docs.astral.sh/ruff/), [mypy](https://mypy.readthedocs.io/) `--strict` |
| Vulnerabilities | [pip-audit](https://github.com/pypa/pip-audit) |

## Quick start

```sh
# 1. Create the venv with all tools (needs uv; Python 3.15 is fetched if missing)
make tools

# 2. Configure environment
cp sample.env .env

# 3. Start Postgres (host port 5434)
make test-db-up

# 4. Apply migrations
make migrate

# 5. Run
make serve
```

The service starts on `http://localhost:8082`.

**Endpoints out of the box:**

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check — `{"status":"ok"}` |
| GET | `/metrics` | Prometheus metrics, incl. `py_template_metric_build_info_total` |
| GET | `/example` | User id 1 — `200 {"id":1}`, `404 {"error":"user not found"}`, `500 {"error":"internal server error"}` |

## Running with Docker

```sh
make up        # start postgres + service (http://localhost:8082)
make migrate   # apply migrations
make logs      # follow the logs
make down      # stop the stack
```

The service waits for Postgres to become healthy before starting and has a healthcheck of its own against
`/health`. `.env` points `PG_HOST` at `127.0.0.1` for host-side tooling; compose overrides it with the `postgres`
service name inside the network. `make up-rebuild` rebuilds the image with the current git commit stamped into the
build_info metric.

## Development

```sh
make full-lint          # format + ruff + mypy --strict
make test               # unit tests; DB tests skip without a database
make test-integration   # everything, against the database — fails if it is missing
make cover              # integration run with coverage (fails under 70%)
make vulncheck          # pip-audit over uv.lock
make actionlint         # validate the GitHub workflow
```

## Project structure

```
py-template/
├── src/app_template/
│   ├── main.py              # entry point
│   ├── env.py               # config
│   ├── app/                 # composition root: server, routes, repository + usecase factories
│   ├── connectors/          # postgres, logger, metrics
│   ├── http/handlers/       # one package per endpoint
│   ├── http/middleware/     # request id, access log, recovery, timeout
│   ├── pkg/users/           # example domain: interfaces, entity, errors, usecase, repository
│   └── utils/               # either, errors, deps (Logger protocol), shutdown
├── tests/                   # mirrors src/, plus testdb.py and hand-written mocks
├── db/migrations/
├── infra/postgres/          # local DB data (bind mount, git-ignored)
└── docs/                    # structure.md, code_style.md
```

See [docs/structure.md](docs/structure.md) for the full layout and how to add a domain,
[docs/code_style.md](docs/code_style.md) for the rules, and [CLAUDE.md](CLAUDE.md) for the reasoning behind every
decision.

## Side-by-side with the other templates

| template | postgres host port | app host port | container prefix |
|---|---|---|---|
| go | 5432 | 8080 | `go_template_` |
| rust | 5433 | 8081 | `rust_template_` |
| **py** | **5434** | **8082** | **`py_template_`** |
| ts | 5435 | 8083 | `ts_template_` |
