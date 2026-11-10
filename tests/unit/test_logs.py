from __future__ import annotations

import logging
import re
from pathlib import Path

from mtlm.audit.logs import LOGGER_NAME, setup_logging, shutdown_logging


def mtlm_handlers() -> list[logging.Handler]:
    return [
        h for h in logging.getLogger(LOGGER_NAME).handlers if getattr(h, "_mtlm_handler", False)
    ]


def test_rotation(tmp_path: Path) -> None:
    log_file = setup_logging(tmp_path, max_bytes=2000, backup_count=3)
    logger = logging.getLogger("mtlm.test")
    for i in range(200):
        logger.info("message de test numéro %d avec du texte pour remplir", i)
    shutdown_logging()
    rotated = sorted(p.name for p in tmp_path.iterdir())
    assert log_file.name in rotated
    assert "mtlm.log.1" in rotated
    assert len(rotated) <= 4  # fichier courant + 3 archives maximum


def test_configuration_idempotente(tmp_path: Path) -> None:
    setup_logging(tmp_path)
    setup_logging(tmp_path)
    assert len(mtlm_handlers()) == 1
    shutdown_logging()
    assert mtlm_handlers() == []


def test_format_horodatage_utc(tmp_path: Path) -> None:
    log_file = setup_logging(tmp_path)
    logging.getLogger("mtlm.test").warning("bonjour é")
    shutdown_logging()
    line = log_file.read_text(encoding="utf-8").splitlines()[-1]
    assert re.match(
        r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z WARNING mtlm\.test \[.+\] bonjour é$", line
    )
