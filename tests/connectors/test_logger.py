import io
import json
import logging

import pytest

from app_template.connectors import logger
from app_template.env import AppConfig


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("debug", logging.DEBUG),
        ("info", logging.INFO),
        ("warn", logging.WARNING),
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
        ("  DEBUG ", logging.DEBUG),
        ("Error", logging.ERROR),
        ("", logging.INFO),
        ("verbose", logging.INFO),
        ("error+2", logging.INFO),
    ],
)
def test_parse_level(raw: str, expected: int) -> None:
    assert logger.parse_level(raw) == expected


def app_config(log_format: str, log_level: str) -> AppConfig:
    return AppConfig.model_validate({"APP_NAME": "test", "LOG_FORMAT": log_format, "LOG_LEVEL": log_level})


@pytest.mark.usefixtures("clean_env")
def test_json_format_writes_one_json_object_per_line() -> None:
    out = io.StringIO()
    log = logger.new(app_config("json", "info"), stream=out)

    log.info("get user", user_id=1)

    record = json.loads(out.getvalue())
    assert record["event"] == "get user"
    assert record["level"] == "info"
    assert record["user_id"] == 1
    assert "timestamp" in record


@pytest.mark.usefixtures("clean_env")
def test_text_format_writes_key_value_pairs() -> None:
    out = io.StringIO()
    log = logger.new(app_config("text", "info"), stream=out)

    log.warning("get user", user_id=1)

    line = out.getvalue()
    assert "level=warning" in line
    assert 'event="get user"' in line
    assert "user_id=1" in line


@pytest.mark.usefixtures("clean_env")
def test_level_filters_lower_records() -> None:
    out = io.StringIO()
    log = logger.new(app_config("json", "warn"), stream=out)

    log.info("dropped")
    log.error("kept")

    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "kept"


@pytest.mark.usefixtures("clean_env")
def test_unknown_level_falls_back_to_info() -> None:
    out = io.StringIO()
    log = logger.new(app_config("json", "nonsense"), stream=out)

    log.debug("dropped")
    log.info("kept")

    assert len(out.getvalue().splitlines()) == 1


@pytest.mark.usefixtures("clean_env")
def test_exception_is_rendered() -> None:
    out = io.StringIO()
    log = logger.new(app_config("json", "info"), stream=out)

    log.error("boom", exc_info=ValueError("bad value"))

    record = json.loads(out.getvalue())
    assert "ValueError: bad value" in record["exception"]
