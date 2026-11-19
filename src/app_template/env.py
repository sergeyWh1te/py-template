"""Configuration, read from ``.env`` or the shell environment.

Every variable is listed in ``sample.env``; add new ones there too.

``READ_ENV_FROM_SHELL=true`` skips the file and takes config from the process
environment only — that is how the service runs in Docker and CI, where no
``.env`` exists. A missing ``.env`` is tolerated either way (pydantic-settings
ignores a file that is not there), so the shell can always supply the values.
"""

import os
import threading
from dataclasses import dataclass

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app_template.utils.either import Either, is_left, left, right

DEFAULT_ENV_FILE = ".env"

_MAX_PORT = 65535


class AppConfig(BaseSettings):
    # extra="ignore": .env holds PG_* and other keys this class does not own.
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    name: str = Field(validation_alias="APP_NAME", min_length=1)
    env: str = Field(default="local", validation_alias="ENV")
    port: int = Field(default=8080, validation_alias="PORT", ge=1, le=_MAX_PORT)
    # "json" selects the JSON renderer; anything else gives logfmt-style text.
    log_format: str = Field(default="text", validation_alias="LOG_FORMAT")
    # Parsed leniently by connectors.logger: an unknown value means info.
    log_level: str = Field(default="info", validation_alias="LOG_LEVEL")
    # Stamped into the image at build time (Dockerfile ARG COMMIT -> ENV COMMIT)
    # and shown in the build_info metric. Not something to set by hand.
    commit: str = Field(default="", validation_alias="COMMIT")


class PgConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    host: str = Field(validation_alias="PG_HOST", min_length=1)
    port: int = Field(validation_alias="PG_PORT", ge=1, le=_MAX_PORT)
    username: str = Field(validation_alias="PG_USERNAME", min_length=1)
    # SecretStr: printing or logging the config shows '**********', not the password.
    password: SecretStr = Field(validation_alias="PG_PASSWORD")
    database: str = Field(validation_alias="PG_DATABASE", min_length=1)
    schema_name: str = Field(default="public", validation_alias="PG_SCHEMA")
    ssl_mode: str = Field(default="disable", validation_alias="PG_SSLMODE")


@dataclass(frozen=True, slots=True)
class Config:
    app: AppConfig
    pg: PgConfig


def read_from_shell() -> bool:
    # Same truthy spellings as Go's strconv.ParseBool, which go-template's viper uses.
    raw = os.environ.get("READ_ENV_FROM_SHELL", "").strip().lower()
    return raw in {"1", "t", "true"}


def load(env_file: str | None = DEFAULT_ENV_FILE) -> Either[Exception, Config]:
    """Build a Config without memoizing it. ``env_file=None`` means shell only."""
    source = env_file
    if read_from_shell():
        source = None

    try:
        app = AppConfig(_env_file=source)
        pg = PgConfig(_env_file=source)
    except ValidationError as exc:
        return left(exc)

    return right(Config(app=app, pg=pg))


_lock = threading.Lock()
_config: Config | None = None


def read() -> Either[Exception, Config]:
    """Return the process-wide Config, loading it on first success.

    A failed load is *not* cached (unlike ``functools.cache`` on a function that
    returned an error value, or Go's ``sync.Once``): the next call tries again.
    """
    global _config  # noqa: PLW0603 — the memoized config is one of the two sanctioned globals.

    with _lock:
        if _config is not None:
            return right(_config)

        result = load()
        if is_left(result):
            return result

        _config = result.right
        return result
