"""Service « formats » : signatures binaires et inspection des archives (F3, phase 4).

1. Signature : les 4 096 premiers octets de chaque fichier ordinaire présent sont lus
   (lecture seule) pour identifier son format réel et signaler les extensions trompeuses.
2. Archives : ZIP, RAR, 7z, GZIP, BZIP2, XZ et TAR sont inspectés sans extraction (voir
   :mod:`mtlm.formats.archives` et :mod:`mtlm.formats.libarchive`) : chaque fichier contenu
   reçoit son empreinte. Une archive déjà inspectée avec le même contenu et la même version
   du moteur n'est pas ré-inspectée.

Une archive en erreur n'arrête jamais le traitement : le motif est enregistré et journalisé.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass

from mtlm import ENGINE_VERSION
from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import TaskControl
from mtlm.formats.archives import ArchiveLimits, ArchiveReport, inspect_archive
from mtlm.formats.signatures import HEAD_SIZE, sniff
from mtlm.fs.reader import ReadOnlyFile
from mtlm.store.database import transaction

log = logging.getLogger("mtlm.formats")

ARCHIVE_KINDS = {"zip", "rar", "7z", "gzip", "bzip2", "xz", "tar"}
ARCHIVE_EXTS = {"zip", "rar", "7z", "gz", "tgz", "bz2", "xz", "tar"}


@dataclass
class FormatSummary:
    job_id: int
    state: str
    signatures: int = 0
    signature_errors: int = 0
    misleading: int = 0
    archives: int = 0
    archives_ok: int = 0
    archives_problem: int = 0
    archive_entries: int = 0


def _abs(root: str, rel: bytes) -> bytes:
    return os.path.join(os.fsencode(root), rel)  # noqa: PTH118 — chemins en octets


class FormatService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        journal: AuditJournal,
        limits: ArchiveLimits | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._limits = limits or ArchiveLimits()
        self._jobs = JobStore(conn, clock)

    def run(
        self,
        source_id: int | None = None,
        *,
        control: TaskControl | None = None,
        progress: Callable[[FormatSummary], None] | None = None,
    ) -> FormatSummary:
        ctl = control or TaskControl()
        job_id = self._jobs.create("archives", {"source_id": source_id})
        summary = FormatSummary(job_id=job_id, state="running")
        source_clause = " AND f.root_id = ?" if source_id is not None else ""
        params: tuple[object, ...] = (source_id,) if source_id is not None else ()

        # 1. Signatures des fichiers qui n'en ont pas encore.
        rows = self._conn.execute(
            "SELECT f.id, s.path, f.rel_path_bytes, f.ext FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id WHERE s.status = 'ok'"
            " AND f.presence = 'present' AND f.file_type = 'file' AND f.is_dataless = 0"
            " AND f.magic IS NULL" + source_clause + " ORDER BY f.id",
            params,
        ).fetchall()
        updates: list[tuple[str, int]] = []
        for file_id, root, rel, _ext in rows:
            ctl.checkpoint()
            try:
                with ReadOnlyFile(_abs(root, bytes(rel))) as handle:
                    head = next(handle.chunks(HEAD_SIZE), b"")
            except OSError as exc:
                summary.signature_errors += 1
                log.warning("Signature illisible (fichier %s) : %s", file_id, exc)
                continue
            updates.append((sniff(head).kind, int(file_id)))
            summary.signatures += 1
            if len(updates) >= 1000:
                self._save_magic(updates)
                if progress is not None:
                    progress(summary)
        self._save_magic(updates)
        summary.misleading = self.count_misleading(source_id)

        # 2. Archives.
        archives = self._conn.execute(
            "SELECT f.id, s.path, f.rel_path_bytes, f.magic, f.content_id, a.content_id,"
            " a.engine_version FROM file_record f JOIN source_root s ON s.id = f.root_id"
            " LEFT JOIN archive_scan a ON a.file_id = f.id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.file_type = 'file'"
            " AND f.hash_state = 'validated'"
            f" AND (f.magic IN ({','.join('?' * len(ARCHIVE_KINDS))})"
            f" OR f.ext IN ({','.join('?' * len(ARCHIVE_EXTS))}))"
            + source_clause
            + " ORDER BY f.id",
            (*sorted(ARCHIVE_KINDS), *sorted(ARCHIVE_EXTS), *params),
        ).fetchall()
        for file_id, root, rel, magic, content_id, done_content, done_engine in archives:
            ctl.checkpoint()
            summary.archives += 1
            if done_content == content_id and done_engine == ENGINE_VERSION:
                summary.archives_ok += 1
                continue
            report = inspect_archive(_abs(root, bytes(rel)), magic or "other", self._limits)
            self._save_archive(int(file_id), content_id, report)
            summary.archive_entries += len(report.entries)
            if report.status == "ok":
                summary.archives_ok += 1
            else:
                summary.archives_problem += 1
                log.warning("Archive %s : %s (%s)", file_id, report.status, report.reason)
            if progress is not None:
                progress(summary)

        summary.state = "completed"
        self._jobs.finish(job_id, "completed", asdict(summary))
        self._journal.append(
            ACTOR_USER, "formats.run", f"source={source_id or 'toutes'}", details=asdict(summary)
        )
        return summary

    def count_misleading(self, source_id: int | None = None) -> int:
        from mtlm.formats.signatures import EXPECTED

        rows = self._conn.execute(
            "SELECT ext, magic FROM file_record WHERE magic IS NOT NULL AND presence = 'present'"
            + (" AND root_id = ?" if source_id is not None else ""),
            (source_id,) if source_id is not None else (),
        )
        return sum(
            1
            for ext, magic in rows
            if magic != "empty" and ext in EXPECTED and magic not in EXPECTED[ext]
        )

    def _save_magic(self, updates: list[tuple[str, int]]) -> None:
        if not updates:
            return
        with transaction(self._conn):
            self._conn.executemany("UPDATE file_record SET magic = ? WHERE id = ?", updates)
        updates.clear()

    def _save_archive(self, file_id: int, content_id: int | None, report: ArchiveReport) -> None:
        now = iso_utc(self._clock.now())
        with transaction(self._conn):
            self._conn.execute("DELETE FROM archive_entry WHERE archive_file_id = ?", (file_id,))
            for entry in report.entries:
                entry_content = None
                if entry.sha256 is not None and entry.size is not None:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO content(sha256, size) VALUES (?, ?)",
                        (entry.sha256, entry.size),
                    )
                    entry_content = self._conn.execute(
                        "SELECT id FROM content WHERE sha256 = ?", (entry.sha256,)
                    ).fetchone()[0]
                self._conn.execute(
                    "INSERT INTO archive_entry(archive_file_id, inner_path, depth, size,"
                    " compressed_size, is_encrypted, is_dir, content_id, status, reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        file_id,
                        entry.inner_path,
                        entry.depth,
                        entry.size,
                        entry.compressed_size,
                        int(entry.is_encrypted),
                        int(entry.is_dir),
                        entry_content,
                        entry.status,
                        entry.reason,
                    ),
                )
            self._conn.execute(
                "INSERT INTO archive_scan(file_id, content_id, format, status, entries_total,"
                " entries_read, bytes_read, reason, engine_version, inspected_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(file_id) DO UPDATE SET"
                " content_id = excluded.content_id, format = excluded.format,"
                " status = excluded.status, entries_total = excluded.entries_total,"
                " entries_read = excluded.entries_read, bytes_read = excluded.bytes_read,"
                " reason = excluded.reason, engine_version = excluded.engine_version,"
                " inspected_at = excluded.inspected_at",
                (
                    file_id,
                    content_id,
                    report.format,
                    report.status,
                    report.entries_total,
                    report.entries_read,
                    report.bytes_read,
                    report.reason,
                    ENGINE_VERSION,
                    now,
                ),
            )
