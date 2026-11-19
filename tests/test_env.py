from pathlib import Path

import pytest
from pydantic import ValidationError

from app_template import env
from app_template.utils.either import is_left, is_right

ENV_FILE = """\
APP_NAME=from-file
ENV=test
PORT=9000
LOG_FORMAT=json
LOG_LEVEL=warn
PG_HOST=db.local
PG_PORT=6543
PG_USERNAME=app
PG_PASSWORD=s3cr3t
PG_DATABASE=appdb
UNRELATED_KEY=ignored
"""


def write_env(tmp_path: Path, content: str = ENV_FILE) -> str:
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.mark.usefixtures("clean_env")
def test_load_reads_the_env_file(tmp_path: Path) -> None:
    result = env.load(write_env(tmp_path))

    assert is_right(result)
    cfg = result.right
    assert cfg.app.name == "from-file"
    assert cfg.app.env == "test"
    assert cfg.app.port == 9000
    assert cfg.app.log_format == "json"
    assert cfg.app.log_level == "warn"
    assert cfg.app.commit == ""
    assert cfg.pg.host == "db.local"
    assert cfg.pg.port == 6543
    assert cfg.pg.username == "app"
    assert cfg.pg.password.get_secret_value() == "s3cr3t"
    assert cfg.pg.database == "appdb"
    assert cfg.pg.schema_name == "public"
    assert cfg.pg.ssl_mode == "disable"


def test_shell_overrides_the_file(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_NAME", "from-shell")

    result = env.load(write_env(tmp_path))

    assert is_right(result)
    assert result.right.app.name == "from-shell"


def test_read_env_from_shell_ignores_the_file(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("READ_ENV_FROM_SHELL", "true")

    result = env.load(write_env(tmp_path))

    # The file has every required value, but it must not be read.
    assert is_left(result)
    assert isinstance(result.left, ValidationError)


def test_read_env_from_shell_takes_the_environment(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("READ_ENV_FROM_SHELL", "1")
    for line in ENV_FILE.splitlines():
        key, _, value = line.partition("=")
        clean_env.setenv(key, value)

    result = env.load("/does/not/exist/.env")

    assert is_right(result)
    assert result.right.app.name == "from-file"


@pytest.mark.usefixtures("clean_env")
def test_missing_env_file_is_tolerated_but_required_values_are_not(tmp_path: Path) -> None:
    result = env.load(str(tmp_path / "missing.env"))

    assert is_left(result)
    assert isinstance(result.left, ValidationError)
    assert "APP_NAME" in str(result.left)


@pytest.mark.usefixtures("clean_env")
def test_invalid_port_is_an_error(tmp_path: Path) -> None:
    result = env.load(write_env(tmp_path, ENV_FILE.replace("PORT=9000", "PORT=70000")))

    assert is_left(result)


@pytest.mark.usefixtures("clean_env")
def test_password_is_not_printed(tmp_path: Path) -> None:
    result = env.load(write_env(tmp_path))

    assert is_right(result)
    assert "s3cr3t" not in repr(result.right)


def test_read_memoizes_success_but_not_failure(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    clean_env.chdir(tmp_path)

    # No .env in the working directory and nothing in the shell: a failure...
    first = env.read()
    assert is_left(first)

    # ...which is not cached: once the file appears, the next call succeeds.
    write_env(tmp_path)
    second = env.read()
    assert is_right(second)

    # And success is cached: changing the file no longer matters.
    write_env(tmp_path, ENV_FILE.replace("from-file", "changed"))
    third = env.read()
    assert is_right(third)
    assert third.right is second.right
