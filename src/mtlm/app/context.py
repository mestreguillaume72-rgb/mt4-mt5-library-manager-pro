"""Ouverture de l'application : dossiers, journaux, base, migrations, audit.

Point d'entrée unique utilisé par la CLI (et plus tard l'interface graphique).
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

from mtlm import ENGINE_VERSION, __version__
from mtlm.app.jobs import JobStore
from mtlm.app.quarantine import QuarantineService
from mtlm.audit.journal import ACTOR_SYSTEM, AuditJournal
from mtlm.audit.logs import setup_logging
from mtlm.core.clock import Clock, SystemClock
from mtlm.core.paths import AppPaths
from mtlm.store.backup import backup_database
from mtlm.store.database import connect, transaction
from mtlm.store.migrations_engine import Migrator

log = logging.getLogger("mtlm.app")


@dataclass
class AppContext:
    paths: AppPaths
    clock: Clock
    conn: sqlite3.Connection
    journal: AuditJournal
    migrator: Migrator
    log_file: Path
    applied_migrations: list[int] = field(default_factory=list)

    def backup(self, label: str) -> Path:
        return backup_database(self.conn, self.paths.backups_dir, self.clock, label)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> AppContext:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def open_app(paths: AppPaths, clock: Clock | None = None, *, recover: bool = True) -> AppContext:
    """Prépare les dossiers de l'application, ouvre la base et applique les migrations.

    N'accède à aucun dossier source : uniquement aux dossiers propres à l'application.
    """
    used_clock = clock or SystemClock()
    paths.ensure()
    log_file = setup_logging(paths.logs_dir)
    log.info("Démarrage %s (moteur %s), base %s", __version__, ENGINE_VERSION, paths.database)
    conn = connect(paths.database)
    try:
        migrator = Migrator(
            conn,
            clock=used_clock,
            app_version=__version__,
            backup=lambda c, label: backup_database(c, paths.backups_dir, used_clock, label),
        )
        applied = migrator.migrate()
        journal = AuditJournal(conn, used_clock)
        if applied:
            journal.append(
                ACTOR_SYSTEM,
                "db.migrate",
                str(paths.database),
                details={"versions": applied, "app_version": __version__},
            )
        if recover:  # désactivé pour les connexions secondaires (tâches de fond)
            interrupted = JobStore(conn, used_clock).mark_interrupted()
            interrupted_batches = QuarantineService(
                conn, used_clock, journal, paths
            ).mark_interrupted()
            with transaction(conn):
                cursor = conn.execute(
                    "UPDATE organize_plan SET status = 'interrupted' WHERE status = 'running'"
                )
            if interrupted_batches or cursor.rowcount:
                journal.append(
                    ACTOR_SYSTEM,
                    "transfer.interrupted",
                    "démarrage",
                    details={
                        "lots_quarantaine": interrupted_batches,
                        "plans_organisation": cursor.rowcount,
                    },
                )
            if interrupted:
                journal.append(
                    ACTOR_SYSTEM,
                    "job.interrupted",
                    "démarrage",
                    details={"jobs": interrupted, "note": "tâches interrompues par une fermeture"},
                )
    except BaseException:
        conn.close()
        raise
    return AppContext(paths, used_clock, conn, journal, migrator, log_file, applied)
