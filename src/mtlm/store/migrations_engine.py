"""Migrations versionnées du schéma (D-003).

Principes :

* chaque migration est un script SQL numéroté, appliqué **dans une seule transaction** :
  en cas d'erreur, la base reste exactement dans son état précédent ;
* l'empreinte SHA-256 de chaque script appliqué est enregistrée ; si un script déjà
  appliqué est modifié ensuite, l'application refuse de continuer
  (:class:`MigrationIntegrityError`) ;
* une base créée par une version plus récente de l'application n'est jamais modifiée
  (:class:`DatabaseTooNewError`) ;
* une sauvegarde vérifiée est faite avant toute migration d'une base existante.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from mtlm.core.clock import Clock, iso_utc
from mtlm.core.errors import DatabaseTooNewError, MigrationError, MigrationIntegrityError
from mtlm.store.database import transaction, user_version

log = logging.getLogger("mtlm.store.migrations")

_FILE_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version      INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    checksum     TEXT NOT NULL,
    applied_at   TEXT NOT NULL,
    app_version  TEXT NOT NULL
) STRICT
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationStatus:
    current_version: int
    latest_version: int
    applied: tuple[int, ...]
    pending: tuple[int, ...]

    @property
    def up_to_date(self) -> bool:
        return not self.pending


def packaged_migrations() -> list[Migration]:
    """Migrations livrées avec l'application, triées et contiguës à partir de 1."""
    folder = resources.files("mtlm.store.migrations")
    found: list[Migration] = []
    for entry in folder.iterdir():
        match = _FILE_RE.match(entry.name)
        if match:
            found.append(
                Migration(int(match.group(1)), match.group(2), entry.read_text(encoding="utf-8"))
            )
    return validate_sequence(found)


def validate_sequence(migrations: Sequence[Migration]) -> list[Migration]:
    ordered = sorted(migrations, key=lambda m: m.version)
    for expected, migration in enumerate(ordered, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"Séquence de migrations invalide : version {expected} attendue, "
                f"{migration.version} trouvée"
            )
    return ordered


def split_statements(sql: str) -> list[str]:
    """Découpe un script en instructions complètes (gère les blocs ``BEGIN … END`` des triggers)."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if _has_code(buffer):
                statements.append(buffer.strip())
            buffer = ""
    if _has_code(buffer):
        raise MigrationError("Script de migration incomplet : instruction non terminée par « ; »")
    return statements


def _has_code(chunk: str) -> bool:
    for line in chunk.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


BackupHook = Callable[[sqlite3.Connection, str], Path]


class Migrator:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        clock: Clock,
        app_version: str,
        migrations: Sequence[Migration] | None = None,
        backup: BackupHook | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._app_version = app_version
        self._migrations = (
            validate_sequence(migrations) if migrations is not None else packaged_migrations()
        )
        self._backup = backup

    @property
    def latest_version(self) -> int:
        return self._migrations[-1].version if self._migrations else 0

    def _applied_rows(self) -> list[tuple[int, str, str]]:
        exists = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migration'"
        ).fetchone()
        if not exists:
            return []
        rows = self._conn.execute(
            "SELECT version, name, checksum FROM schema_migration ORDER BY version"
        ).fetchall()
        return [(int(v), str(n), str(c)) for v, n, c in rows]

    def verify(self) -> None:
        """Vérifie que la base est compatible et que les migrations appliquées sont intactes."""
        current = user_version(self._conn)
        if current > self.latest_version:
            raise DatabaseTooNewError(
                f"La base est en version de schéma {current}, mais cette application ne connaît "
                f"que la version {self.latest_version}. Mettez l'application à jour ; "
                "la base n'a pas été modifiée."
            )
        known = {m.version: m for m in self._migrations}
        for version, name, checksum in self._applied_rows():
            migration = known.get(version)
            if migration is None:
                raise DatabaseTooNewError(
                    f"La base contient la migration {version} ({name}), "
                    "inconnue de cette application."
                )
            if migration.checksum != checksum:
                raise MigrationIntegrityError(
                    f"La migration {version} ({name}) a été modifiée depuis son application "
                    "(empreinte différente). Arrêt par sécurité."
                )

    def status(self) -> MigrationStatus:
        self.verify()
        applied = tuple(v for v, _, _ in self._applied_rows())
        current = user_version(self._conn)
        pending = tuple(m.version for m in self._migrations if m.version > current)
        return MigrationStatus(current, self.latest_version, applied, pending)

    def migrate(self) -> list[int]:
        """Applique les migrations en attente. Retourne les versions appliquées."""
        status = self.status()
        if status.up_to_date:
            return []
        if status.current_version > 0 and self._backup is not None:
            path = self._backup(self._conn, f"avant-migration-v{status.latest_version}")
            log.info("Sauvegarde avant migration : %s", path)
        applied: list[int] = []
        for migration in self._migrations:
            if migration.version <= status.current_version:
                continue
            self._apply(migration)
            applied.append(migration.version)
        return applied

    def _apply(self, migration: Migration) -> None:
        log.info("Application de la migration %04d_%s", migration.version, migration.name)
        try:
            with transaction(self._conn):
                self._conn.execute(BOOTSTRAP_SQL)
                for statement in split_statements(migration.sql):
                    self._conn.execute(statement)
                self._conn.execute(
                    "INSERT INTO schema_migration(version, name, checksum, applied_at, app_version)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                        iso_utc(self._clock.now()),
                        self._app_version,
                    ),
                )
                self._conn.execute(f"PRAGMA user_version = {int(migration.version)}")
        except sqlite3.Error as exc:
            log.error("Échec de la migration %04d : %s", migration.version, exc)
            raise MigrationError(
                f"La migration {migration.version} ({migration.name}) a échoué : {exc}. "
                "La base est restée dans son état précédent."
            ) from exc
        fk_problems = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_problems:
            raise MigrationError(
                f"Contrôle des clés étrangères en échec après la migration {migration.version}"
            )
