"""Application logger: structlog, key/value, JSON or logfmt text.

The logger is built as an *instance* with ``structlog.wrap_logger`` and passed
down by constructor injection. ``structlog.configure`` is never called: it
mutates process-global state, which is exactly what the composition-root rule
keeps out of the code (and it would leak between tests).
"""

import logging
import sys
from typing import TextIO

import structlog
from structlog.typing import FilteringBoundLogger, Processor

from app_template.env import AppConfig

_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def parse_level(raw: str) -> int:
    """Map ``LOG_LEVEL`` to a stdlib level number.

    An unset or unrecognized value falls back to info rather than failing startup —
    losing the service over a typo in a log setting is worse than logging at the
    wrong level.
    """
    level = _LEVELS.get(raw.strip().lower())
    if level is None:
        return logging.INFO
    return level


def new(cfg: AppConfig, stream: TextIO | None = None) -> FilteringBoundLogger:
    out = stream
    if out is None:
        out = sys.stdout

    processors: list[Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        # Turns exc_info=... into a formatted "exception" field, so a traceback
        # survives in both renderers instead of being dropped.
        structlog.processors.format_exc_info,
    ]
    if cfg.log_format.strip().lower() == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.processors.LogfmtRenderer(key_order=["timestamp", "level", "event"]))

    log: FilteringBoundLogger = structlog.wrap_logger(
        structlog.PrintLogger(file=out),
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(parse_level(cfg.log_level)),
        cache_logger_on_first_use=False,
    )
    return log
