"""Service d'inventaire (F1, scénario A).

Inventaire en lecture seule d'une source, incrémental :

* fichier nouveau ⇒ inséré ;
* fichier modifié (taille, date de modification ou inode différents) ⇒ mis à jour, son
  empreinte éventuelle passe à l'état « stale » (à recalculer) ;
* fichier inchangé ⇒ seulement marqué « vu » (aucun recalcul ultérieur) ;
* fichier disparu ⇒ « missing » **uniquement si l'inventaire est allé jusqu'au bout**
  (un inventaire annulé ne déclare jamais de fichier manquant).

Les écritures en base se font par lots transactionnels. La source n'est jamais modifiée.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import Cancelled, TaskControl
from mtlm.core.errors import MtlmError
from mtlm.fs.walker import WalkEntry, WalkError, WalkStats, walk
from mtlm.store.database import transaction

log = logging.getLogger("mtlm.scan")

DEFAULT_BATCH = 2000


class ScanError(MtlmError):
    """L'inventaire n'a pas pu être réalisé."""


@dataclass
class ScanSummary:
    job_id: int
    source_id: int
    state: str
    seen: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    missing: int = 0
    errors: int = 0
    directories: int = 0
    cycles_skipped: int = 0
    symlinks: int = 0
    dataless: int = 0


ProgressCallback = Callable[[ScanSummary], None]


@dataclass(frozen=True)
class _Known:
    id: int
    size: int | None
    mtime_ns: int | None
    inode: int | None
    hash_state: str


class ScanService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)

    def scan(
        self,
        source_id: int,
        *,
        control: TaskControl | None = None,
        progress: ProgressCallback | None = None,
        batch_size: int = DEFAULT_BATCH,
    ) -> ScanSummary:
        row = self._conn.execute(
            "SELECT path, status FROM source_root WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise ScanError(f"Source {source_id} inconnue")
        root, status = Path(row[0]), row[1]
        if status == "removed":
            raise ScanError(f"La source {source_id} a été retirée")
        ctl = control or TaskControl()
        job_id = self._jobs.create("scan", {"source_id": source_id, "path": str(root)})
        summary = ScanSummary(job_id=job_id, source_id=source_id, state="running")
        self._journal.append(ACTOR_USER, "scan.start", str(root), details={"job": job_id})
        log.info("Inventaire %d de %s", job_id, root)

        if not root.is_dir():
            self._set_root_status(source_id, "unreachable")
            summary.state = "failed"
            self._finish(summary, root, "failed")
            raise ScanError(f"Source inaccessible : {root} (dossier absent ou disque débranché)")

        known = self._load_known(source_id)
        stats = WalkStats()
        pending_new: list[tuple[object, ...]] = []
        pending_changed: list[tuple[object, ...]] = []
        pending_seen: list[tuple[int, int]] = []
        pending_errors: list[tuple[object, ...]] = []

        def flush() -> None:
            with transaction(self._conn):
                self._insert_new(pending_new, source_id, job_id)
                if pending_changed:
                    self._conn.executemany(
                        "UPDATE file_record SET size = ?, mtime_ns = ?, ctime_ns = ?,"
                        " birthtime_ns = ?, inode = ?, device = ?, mode = ?, is_symlink = ?,"
                        " is_dataless = ?, file_type = ?, presence = 'present',"
                        " hash_state = CASE WHEN hash_state IN ('validated', 'error')"
                        "   THEN 'stale' ELSE hash_state END,"
                        " last_seen_job = ? WHERE id = ?",
                        pending_changed,
                    )
                if pending_seen:
                    self._conn.executemany(
                        "UPDATE file_record SET last_seen_job = ?, presence = 'present'"
                        " WHERE id = ?",
                        pending_seen,
                    )
                if pending_errors:
                    self._conn.executemany(
                        "INSERT INTO scan_error(job_id, root_id, rel_path_bytes, errno, message,"
                        " at) VALUES (?, ?, ?, ?, ?, ?)",
                        pending_errors,
                    )
                self._jobs.progress(job_id, summary.seen, errors=summary.errors)
            pending_new.clear()
            pending_changed.clear()
            pending_seen.clear()
            pending_errors.clear()
            if progress is not None:
                progress(summary)

        try:
            for item in walk(root, stats=stats):
                ctl.checkpoint()
                if isinstance(item, WalkError):
                    summary.errors += 1
                    pending_errors.append(
                        (
                            job_id,
                            source_id,
                            item.rel_path_bytes,
                            item.errno,
                            item.message,
                            iso_utc(self._clock.now()),
                        )
                    )
                else:
                    self._classify(
                        item, known, summary, job_id, pending_new, pending_changed, pending_seen
                    )
                if (
                    len(pending_new)
                    + len(pending_changed)
                    + len(pending_seen)
                    + len(pending_errors)
                ) >= batch_size:
                    flush()
            flush()
        except Cancelled:
            flush()
            summary.directories = stats.directories
            summary.cycles_skipped = stats.cycles_skipped
            summary.state = "cancelled"
            self._finish(summary, root, "cancelled")
            return summary

        summary.missing = self._mark_missing(source_id, job_id)
        summary.directories = stats.directories
        summary.cycles_skipped = stats.cycles_skipped
        summary.state = "completed"
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE source_root SET last_scan_job_id = ?, status = 'ok' WHERE id = ?",
                (job_id, source_id),
            )
        self._finish(summary, root, "completed")
        return summary

    # ------------------------------------------------------------------------------------
    def _classify(
        self,
        item: WalkEntry,
        known: dict[bytes, _Known],
        summary: ScanSummary,
        job_id: int,
        pending_new: list[tuple[object, ...]],
        pending_changed: list[tuple[object, ...]],
        pending_seen: list[tuple[int, int]],
    ) -> None:
        summary.seen += 1
        if item.file_type == "symlink":
            summary.symlinks += 1
        if item.is_dataless:
            summary.dataless += 1
        previous = known.get(item.rel_path_bytes)
        if previous is None:
            summary.new += 1
            pending_new.append(
                (
                    item.rel_path,
                    item.rel_path_bytes,
                    item.name,
                    item.ext,
                    item.size,
                    item.mtime_ns,
                    item.ctime_ns,
                    item.birthtime_ns,
                    item.inode,
                    item.device,
                    item.mode,
                    int(item.file_type == "symlink"),
                    int(item.is_dataless),
                    item.file_type,
                )
            )
        elif (previous.size, previous.mtime_ns, previous.inode) != (
            item.size,
            item.mtime_ns,
            item.inode,
        ):
            summary.changed += 1
            pending_changed.append(
                (
                    item.size,
                    item.mtime_ns,
                    item.ctime_ns,
                    item.birthtime_ns,
                    item.inode,
                    item.device,
                    item.mode,
                    int(item.file_type == "symlink"),
                    int(item.is_dataless),
                    item.file_type,
                    job_id,
                    previous.id,
                )
            )
        else:
            summary.unchanged += 1
            pending_seen.append((job_id, previous.id))

    def _insert_new(self, rows: list[tuple[object, ...]], source_id: int, job_id: int) -> None:
        for row in rows:
            cursor = self._conn.execute(
                "INSERT INTO file_record(root_id, rel_path, rel_path_bytes, name, ext, size,"
                " mtime_ns, ctime_ns, birthtime_ns, inode, device, mode, is_symlink,"
                " is_dataless, file_type, first_seen_job, last_seen_job)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, *row, job_id, job_id),
            )
            self._conn.execute(
                "INSERT INTO search_fts(rowid, name, rel_path) VALUES (?, ?, ?)",
                (cursor.lastrowid, row[2], row[0]),
            )

    def _load_known(self, source_id: int) -> dict[bytes, _Known]:
        rows = self._conn.execute(
            "SELECT id, rel_path_bytes, size, mtime_ns, inode, hash_state FROM file_record"
            " WHERE root_id = ?",
            (source_id,),
        )
        return {bytes(r[1]): _Known(int(r[0]), r[2], r[3], r[4], r[5]) for r in rows}

    def _mark_missing(self, source_id: int, job_id: int) -> int:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE file_record SET presence = 'missing' WHERE root_id = ?"
                " AND presence = 'present' AND (last_seen_job IS NULL OR last_seen_job <> ?)",
                (source_id, job_id),
            )
        return cursor.rowcount

    def _set_root_status(self, source_id: int, status: str) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE source_root SET status = ? WHERE id = ?", (status, source_id)
            )

    def _finish(self, summary: ScanSummary, root: Path, state: str) -> None:
        details = asdict(summary)
        self._jobs.finish(summary.job_id, state, details)
        result = {"completed": "ok", "cancelled": "cancelled", "failed": "failed"}[state]
        self._journal.append(
            ACTOR_USER,
            "scan.end",
            str(root),
            result=result,  # type: ignore[arg-type]
            details=details,
        )
        log.info("Inventaire %d terminé (%s) : %s", summary.job_id, state, details)
