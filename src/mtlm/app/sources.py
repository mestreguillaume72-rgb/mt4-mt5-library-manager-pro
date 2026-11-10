"""Gestion des racines sources (F1, scénario A).

Ajouter une source n'écrit **rien** dans le dossier : l'application enregistre seulement
son chemin dans sa propre base. Retirer une source ne supprime aucun fichier : la source
passe à l'état « removed » (historique conservé).
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths
from mtlm.fs.paths import identity, overlaps
from mtlm.store.database import transaction


class SourceError(MtlmError):
    """Source refusée ou introuvable."""


@dataclass(frozen=True)
class SourceRoot:
    id: int
    path: str
    display_name: str
    added_at: str
    status: str
    last_scan_job_id: int | None


class SourceService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal, paths: AppPaths
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._paths = paths

    def list(self, include_removed: bool = False) -> list[SourceRoot]:
        sql = "SELECT id, path, display_name, added_at, status, last_scan_job_id FROM source_root"
        if not include_removed:
            sql += " WHERE status <> 'removed'"
        rows = self._conn.execute(sql + " ORDER BY id").fetchall()
        return [SourceRoot(int(r[0]), r[1], r[2], r[3], r[4], r[5]) for r in rows]

    def get(self, source_id: int) -> SourceRoot:
        for source in self.list(include_removed=True):
            if source.id == source_id:
                return source
        raise SourceError(f"Source {source_id} inconnue")

    def add(self, path: Path, display_name: str | None = None) -> SourceRoot:
        raw = Path(path).expanduser()
        if not raw.exists():
            self._refuse(raw, "le dossier n'existe pas")
        if not raw.is_dir():
            self._refuse(raw, "ce n'est pas un dossier")
        if not os.access(raw, os.R_OK | os.X_OK):
            self._refuse(raw, "le dossier n'est pas lisible (permission refusée)")
        resolved = Path(os.path.realpath(raw))
        for app_dir in (self._paths.data_dir, self._paths.logs_dir):
            if overlaps(resolved, app_dir):
                self._refuse(
                    raw,
                    "il contient (ou est contenu dans) les dossiers de l'application ; "
                    "la base et les journaux ne doivent jamais se trouver dans une source",
                )
        for existing in self.list():
            if overlaps(resolved, Path(existing.path)):
                self._refuse(
                    raw,
                    f"il chevauche la source n° {existing.id} ({existing.path}) ; "
                    "les fichiers seraient comptés deux fois",
                )
        removed = self._conn.execute(
            "SELECT id FROM source_root WHERE path = ? AND status = 'removed'", (str(resolved),)
        ).fetchone()
        ident = identity(resolved)
        name = display_name or resolved.name or str(resolved)
        with transaction(self._conn):
            if removed:
                source_id = int(removed[0])
                self._conn.execute(
                    "UPDATE source_root SET status = 'ok', display_name = ?, device = ?"
                    " WHERE id = ?",
                    (name, ident[0] if ident else None, source_id),
                )
            else:
                cursor = self._conn.execute(
                    "INSERT INTO source_root(path, display_name, added_at, device, status)"
                    " VALUES (?, ?, ?, ?, 'ok')",
                    (str(resolved), name, iso_utc(self._clock.now()), ident[0] if ident else None),
                )
                source_id = int(cursor.lastrowid or 0)
        self._journal.append(ACTOR_USER, "source.add", str(resolved), details={"id": source_id})
        return self.get(source_id)

    def remove(self, source_id: int) -> SourceRoot:
        source = self.get(source_id)
        if source.status == "removed":
            raise SourceError(f"La source {source_id} est déjà retirée")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE source_root SET status = 'removed' WHERE id = ?", (source_id,)
            )
        self._journal.append(
            ACTOR_USER,
            "source.remove",
            source.path,
            details={"id": source_id, "note": "aucun fichier supprimé"},
        )
        return self.get(source_id)

    def _refuse(self, path: Path, reason: str) -> NoReturn:
        self._journal.append(
            ACTOR_USER, "source.add", str(path), result="refused", details={"raison": reason}
        )
        raise SourceError(f"Source refusée : {path} — {reason}")
