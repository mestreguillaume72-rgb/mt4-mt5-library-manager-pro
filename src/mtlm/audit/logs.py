"""Journaux techniques rotatifs (spécification F12 : « journaux rotatifs »)."""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "mtlm"
LOG_FILE_NAME = "mtlm.log"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10
_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)s %(name)s [%(threadName)s] %(message)s"


class _UtcFormatter(logging.Formatter):
    """Horodatages en UTC."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        return time.strftime(datefmt or "%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))


def setup_logging(
    logs_dir: Path,
    *,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> Path:
    """Configure le journal rotatif de l'application ; idempotent. Retourne le fichier de log."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / LOG_FILE_NAME
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, "_mtlm_handler", False):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(_UtcFormatter(_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))
    handler._mtlm_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level)
    return log_file


def shutdown_logging() -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, "_mtlm_handler", False):
            logger.removeHandler(handler)
            handler.close()
