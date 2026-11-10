"""Écriture des manifestes et journaux dans un dossier de destination (quarantaine,
bibliothèque organisée) — jamais dans une source."""

from __future__ import annotations

import json
import os
from typing import Any


def ensure_directory(path: bytes) -> None:
    os.makedirs(path, exist_ok=True)


def write_json_atomic(path: bytes, document: Any) -> None:
    """Écrit un JSON par fichier temporaire + renommage : jamais de manifeste à moitié écrit."""
    temp = path + b".tmp"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, json.dumps(document, ensure_ascii=False, indent=1).encode())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)


def append_jsonl(path: bytes, record: dict[str, Any]) -> None:
    """Ajoute une ligne à un journal JSONL (ajout seul, synchronisé sur disque)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
