"""Unified structured logging with JSON Lines file + Rich console dual output.

Usage:
    from robocode.services.analytics.logger import setup_logging, get_logger

    setup_logging()                           # call once at startup
    log = get_logger(__name__)                # per-module logger
    log.info("event_name", key=value, ...)    # structured logging
"""

import logging
import structlog
from pathlib import Path
from logging.handlers import RotatingFileHandler

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "log"
_LOG_FILE = _LOG_DIR / "robocode.jsonl"

_initialized = False


def setup_logging(level=logging.INFO):
    """Configure structlog dual output: JSON Lines file + console.

    Must be called once at application startup before get_logger().
    Idempotent — subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return

    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    # JSON Lines file handler (rotating: 10MB × 5 backups)
    file_handler = RotatingFileHandler(
        str(_LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt="iso"),
            ],
        )
    )

    # Console handler (text format) — suppress noisy voice logs from terminal
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    _SUPPRESSED_PREFIXES = ("voice", "experience_manager", "experience_filesystem", "reflector")
    console_handler.addFilter(
        lambda record: not any(record.name.startswith(p) for p in _SUPPRESSED_PREFIXES)
    )
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(),
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
            ],
        )
    )

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _initialized = True


def get_logger(name: str = "robocode") -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger for the given name.

    If setup_logging() hasn't been called, structlog will use its
    default console-only output. Call setup_logging() at startup for
    full dual-output behavior.
    """
    return structlog.get_logger(name)
