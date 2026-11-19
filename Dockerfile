# syntax=docker/dockerfile:1

# uv binary, pinned to the same version as the Makefile / CI.
FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

# Build stage: resolve the locked dependencies and install the app into a venv.
FROM python:3.15.2-slim-trixie AS builder

COPY --from=uv /uv /usr/local/bin/uv

# Compile .pyc at build time (faster start, read-only friendly); copy rather
# than hardlink because the cache mount is a different filesystem.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src

# Dependencies first, without the project itself, so this layer is reused
# whenever only the sources change. --frozen: uv.lock is the source of truth;
# a lock that is out of date with pyproject.toml fails the build.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
# --no-editable: the package is installed *into* the venv, so the runtime image
# needs only /app/.venv — no source tree.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# Run stage
FROM python:3.15.2-slim-trixie

WORKDIR /app

# Passed in by the build (see the docker-build Makefile target). The .git
# directory is excluded from the build context, so the commit cannot be read
# here; it is baked into the image environment and shown in build_info.
ARG COMMIT=unknown
ENV COMMIT=${COMMIT} \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    READ_ENV_FROM_SHELL=true

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /app/.venv /app/.venv
COPY db/migrations ./db/migrations

EXPOSE 8080

USER app

# Exec form: the Python process is PID 1 and receives SIGTERM directly, which
# is what triggers the graceful drain.
CMD ["/app/.venv/bin/app-template"]
