"""
Structured JSON logger for the Gate.io futures bot.
"""

import logging
import json
import traceback
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach exception info when present
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))

        # Attach any extra fields passed via `extra=`
        standard_keys = {
            "args", "asctime", "created", "exc_info", "exc_text", "filename",
            "funcName", "levelname", "levelno", "lineno", "message", "module",
            "msecs", "msg", "name", "pathname", "process", "processName",
            "relativeCreated", "stack_info", "thread", "threadName",
        }
        for key, value in record.__dict__.items():
            if key not in standard_keys:
                payload[key] = value

        return json.dumps(payload, default=str)


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Return a logger that writes structured JSON to stdout.

    Parameters
    ----------
    name  : Module/component name (e.g. ``__name__``).
    level : Logging level (default INFO).
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return logger
