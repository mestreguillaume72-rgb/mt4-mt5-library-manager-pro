"""Écriture des exports CSV / JSON vers un fichier choisi par l'utilisateur (F10).

* jamais d'écrasement (création exclusive) ;
* CSV : UTF-8 avec BOM (ouverture directe dans Excel), séparateur « ; » (usage français),
  échappement conforme RFC 4180 ;
* fichier écrit puis synchronisé ; en cas d'erreur, le fichier partiel est supprimé.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from mtlm.core.errors import ExportError


def _create(path: Path) -> int:
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ExportError(f"Le fichier existe déjà, il ne sera pas écrasé : {path}") from exc
    except OSError as exc:
        raise ExportError(f"Export impossible : {exc.strerror or exc}") from exc


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    fd = _create(path)
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            writer.writerow(header)
            for row in rows:
                writer.writerow(["" if v is None else v for v in row])
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        os.unlink(path)
        raise ExportError(f"Export interrompu : {exc.strerror or exc}") from exc
    return count


def write_json(path: Path, document: Any) -> None:
    fd = _create(path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        os.unlink(path)
        raise ExportError(f"Export interrompu : {exc.strerror or exc}") from exc
