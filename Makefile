#!make
# `-include` (not `include`): a missing .env must not break targets that do not
# need it, such as `make tools` on a fresh checkout.
-include .env
export

# Tool versions. Python packages (ruff, mypy, pytest, pip-audit) are pinned in
# pyproject.toml's dev group and locked in uv.lock; these are the tools that
# live outside the venv. Mirrored in .github/workflows/checks.yml and Dockerfile.
UV_VERSION         := 0.13.6
MIGRATE_IMAGE      := migrate/migrate:v4.20.1
ACTIONLINT_VERSION := 1.7.12

COMMIT := $(shell git rev-parse HEAD 2>/dev/null || echo unknown)

# --frozen: never rewrite uv.lock as a side effect of running a tool. Changing
# dependencies is an explicit `uv add` / `make lock`.
UV_RUN := uv run --frozen

# migrate runs inside the compose network (see the `migrate` service), so the
# database host is the `postgres` service on its container port, not PG_HOST.
MIGRATE_DATABASE_URL := postgres://$(PG_USERNAME):$(PG_PASSWORD)@postgres:5432/$(PG_DATABASE)?sslmode=$(PG_SSLMODE)
MIGRATE := docker compose run --rm migrate -path=/migrations -database "$(MIGRATE_DATABASE_URL)"

### Tools
.PHONY: tools
tools:
	@uv --version | grep -q "$(UV_VERSION)" || echo "warning: expected uv $(UV_VERSION), got $$(uv --version)"
	uv sync --frozen

.PHONY: lock
lock:
	uv lock

.PHONY: outdated
outdated:
	uv tree --outdated --depth 1 --frozen

# Audits every locked package (runtime + dev) against the PyPI/OSV advisories.
# --disable-pip --require-hashes: audit the exact hashed lock, without pip
# resolving or installing anything.
.PHONY: vulncheck
vulncheck:
	uv export --frozen --all-groups --no-emit-project --format requirements-txt --quiet \
		| $(UV_RUN) pip-audit --strict --disable-pip --require-hashes --progress-spinner off -r /dev/stdin

.PHONY: build
build:
	uv build --wheel --out-dir dist

# Run the service on the host against the compose Postgres (make test-db-up).
.PHONY: serve
serve:
	COMMIT=$(COMMIT) $(UV_RUN) app-template

### Formatting and linting
.PHONY: fmt
fmt:
	$(UV_RUN) ruff check --select I --fix .
	$(UV_RUN) ruff format .

# Fails when anything is not formatted, without rewriting files (for CI).
.PHONY: check-format
check-format:
	$(UV_RUN) ruff format --check --diff .
	$(UV_RUN) ruff check --select I .

.PHONY: typecheck
typecheck:
	$(UV_RUN) mypy

.PHONY: lint
lint:
	$(UV_RUN) ruff check .
	$(UV_RUN) mypy

.PHONY: fix-lint
fix-lint:
	$(UV_RUN) ruff check --fix .

# Kept as the pre-commit entry point.
.PHONY: full-lint
full-lint: fmt lint

# Static validation of the GitHub workflow (it cannot be run locally).
.PHONY: actionlint
actionlint:
	docker run --rm -v "$(PWD):/repo" -w /repo rhysd/actionlint:$(ACTIONLINT_VERSION) -color

### Tests
# Tests needing Postgres skip themselves when none is reachable, so `make test`
# stays green on a machine with nothing running. Bring one up with test-db-up to
# actually exercise them.
# unexport: the Makefile does `export`, and exporting this would make every
# `make test` run look like a configured database, turning skips into failures.
TEST_PG_DSN ?= postgresql://postgres:postgres@127.0.0.1:5434/master?sslmode=disable
unexport TEST_PG_DSN

.PHONY: test
test:
	$(UV_RUN) pytest

# Fails, rather than skips, if the database is missing — for CI and for checking
# the database-backed tests really ran.
.PHONY: test-integration
test-integration:
	TEST_PG_DSN="$(TEST_PG_DSN)" $(UV_RUN) pytest

# Coverage over unit + database tests, so it needs the database too (same
# fail-not-skip rule as test-integration). Fails under the floor set by
# [tool.coverage.report] fail_under in pyproject.toml. Writes coverage.xml.
.PHONY: cover
cover:
	TEST_PG_DSN="$(TEST_PG_DSN)" $(UV_RUN) pytest --cov --cov-report=term --cov-report=xml

# Just the database, without the service — what the tests need locally.
.PHONY: test-db-up
test-db-up:
	docker compose up -d postgres
	@echo "waiting for postgres..."
	@until docker compose exec -T postgres pg_isready -U postgres -d master >/dev/null 2>&1; do sleep 1; done
	@echo "postgres is ready — run: make test-integration"

.PHONY: test-db-down
test-db-down:
	docker compose stop postgres

# The data lives in a bind mount, so `docker compose down -v` does not clear it
# (-v only removes named volumes). Removing the directory is the reset. It is
# written by the container's postgres user, hence docker rather than plain rm.
.PHONY: test-db-reset
test-db-reset:
	docker compose rm -sf postgres
	docker run --rm -v "$(PWD)/infra/postgres:/data" alpine:3.24 \
		sh -c 'rm -rf /data/pgdata'
	$(MAKE) test-db-up

### Migrations (golang-migrate, via the migrate/migrate image)
.PHONY: migrate
migrate:
	$(MIGRATE) up

.PHONY: migrate-down
migrate-down:
	$(MIGRATE) down -all

.PHONY: migrate-step-down
migrate-step-down:
	$(MIGRATE) down 1

.PHONY: migrate-version
migrate-version:
	$(MIGRATE) version

.PHONY: migrate-force
migrate-force:
	$(MIGRATE) force $(v)

# Timestamped (YYYYMMDDhhmmss, UTC) to match the existing 20220526091432_users
# files: `-seq` would try to continue that number as a sequence and refuse it
# ("at most 6 digits"). Runs as the host user so the files are not owned by root.
.PHONY: migrate-create
migrate-create:
	docker compose run --rm --no-deps --user "$$(id -u):$$(id -g)" migrate \
		create -ext sql -dir /migrations -format 20060102150405 -tz UTC $(name)

.PHONY: migrate-drop
migrate-drop:
	$(MIGRATE) drop -f

### Docker
.PHONY: docker-build
docker-build:
	docker build --build-arg COMMIT=$(COMMIT) -t py-template:stable -f Dockerfile .

.PHONY: up
up:
	docker compose up -d

.PHONY: up-rebuild
up-rebuild:
	COMMIT=$(COMMIT) docker compose up -d --build

.PHONY: down
down:
	docker compose down

.PHONY: logs
logs:
	docker compose logs -f --tail=100

.PHONY: run
run:
	$(MAKE) up && $(MAKE) migrate
