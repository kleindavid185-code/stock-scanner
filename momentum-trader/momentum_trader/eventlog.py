"""Logging: every signal, order, fill and error goes to a file.

Two files, both in logs/ and rotated daily (kept 90 days):

  logs/trader.log    -- human-readable, one line per event
  logs/events.jsonl  -- one JSON object per line, easy to analyse later

Use `log_event(kind, **details)` for trading events. `kind` is one of
EVENT_KINDS. Anything that looks like a secret is scrubbed before writing.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .paths import LOG_DIR

EVENT_KINDS = ("signal", "order", "fill", "error", "risk", "auth", "system")

_SECRET_KEYS = re.compile(r"(token|secret|password|app_key|authorization)", re.I)
_configured_dir: Path | None = None


def _scrub(value):
    if isinstance(value, dict):
        return {k: ("***" if _SECRET_KEYS.search(str(k)) else _scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "kind": getattr(record, "kind", "system"),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        details = getattr(record, "details", None)
        if details:
            payload["details"] = details
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(log_dir: Path = LOG_DIR, console: bool = True) -> logging.Logger:
    """Configure the 'momentum_trader' logger. Safe to call more than once."""
    global _configured_dir
    logger = logging.getLogger("momentum_trader")
    if _configured_dir == log_dir:
        return logger
    for h in list(logger.handlers):
        logger.removeHandler(h)
        h.close()

    log_dir.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    text = TimedRotatingFileHandler(log_dir / "trader.log", when="midnight",
                                    backupCount=90, encoding="utf-8")
    text.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(kind)s] %(message)s", defaults={"kind": "system"}))
    logger.addHandler(text)

    jsonl = TimedRotatingFileHandler(log_dir / "events.jsonl", when="midnight",
                                     backupCount=90, encoding="utf-8")
    jsonl.setFormatter(_JsonFormatter())
    logger.addHandler(jsonl)

    if console:
        con = logging.StreamHandler(sys.stderr)
        con.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        con.setLevel(logging.WARNING)
        logger.addHandler(con)

    _configured_dir = log_dir
    return logger


def log_event(kind: str, message: str, level: int = logging.INFO, exc_info=None, **details) -> None:
    if kind not in EVENT_KINDS:
        raise ValueError(f"Unknown event kind {kind!r}; use one of {EVENT_KINDS}")
    logger = logging.getLogger("momentum_trader")
    if not logger.handlers:
        setup_logging()
    details = _scrub(details)
    suffix = (" " + json.dumps(details, default=str)) if details else ""
    logger.log(level, message + suffix, exc_info=exc_info,
               extra={"kind": kind, "details": details})


def log_error(message: str, exc: BaseException | None = None, **details) -> None:
    log_event("error", message, level=logging.ERROR,
              exc_info=(type(exc), exc, exc.__traceback__) if exc else None, **details)
