"""Service « archives » (1.5.0) : ZIP, RAR, 7z, GZIP, BZIP2, XZ, TAR.

* **Sans décompresser** : chaque fichier contenu a son empreinte (étape « Formats et
  archives ») ; on dit s'il existe déjà sur le disque, quel type de fichier c'est, et si
  l'archive est **entièrement présente sur le disque** (déjà décompressée : on peut la
  supprimer sans rien perdre) ou contient des fichiers **absents du disque**.
* **Avec décompression** (choix de l'utilisateur : case « Décompresser les archives… » ou
  bouton sur l'écran Archives) : extraction vérifiée dans un nouveau dossier au nom de
  l'archive, à côté d'elle ; puis l'archive va à la Corbeille du Mac **seulement si tous les
  fichiers ont été extraits et vérifiés**. Une archive protégée, abîmée, piégée ou incomplète
  n'est jamais touchée.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field

from mtlm.app.deletion import DeletionService
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.errors import MtlmError
from mtlm.fs.reader import FileIdentity, path_identity
from mtlm.hashing.sha256 import UnstableFileError, hash_file
from mtlm.store.database import transaction
from mtlm.transfer.extract import ExtractError, extract_verified
from mtlm.transfer.trash import TrashBackend

ENTRY_TYPES = {
    "mq4": "source MQ4",
    "mq5": "source MQ5",
    "ex4": "compilé EX4",
    "ex5": "compilé EX5",
    "mqh": "include",
    "set": "SET",
    "tpl": "modèle",
    "dll": "DLL",
    "zip": "archive",
    "rar": "archive",
    "7z": "archive",
    "png": "image",
    "bmp": "image",
    "jpg": "image",
    "gif": "image",
    "ico": "image",
    "wav": "son",
    "pdf": "document",
    "txt": "document",
}
_DOUBLE_EXTS = (".tar.gz", ".tar.bz2", ".tar.xz")


class ArchiveError(MtlmError):
    """Opération sur les archives impossible."""


@dataclass(frozen=True)
class ArchiveRow:
    file_id: int
    rel_path: str
    format: str
    status: str
    files: int
    on_disk: int
    tools: int
    sets: int
    reason: str | None

    @property
    def unique(self) -> int:
        return self.files - self.on_disk

    @property
    def verdict(self) -> str:
        if self.status == "encrypted":
            return "Protégée par mot de passe : non lue"
        if self.status in ("corrupt", "rejected"):
            return "Abîmée ou illisible"
        if self.status == "not_supported":
            return "Format non pris en charge sur ce Mac"
        if self.files == 0:
            return "Vide"
        if self.unique == 0:
            return "Déjà décompressée : tout est sur le disque"
        return f"Contient {self.unique} fichier(s) absent(s) du disque"


@dataclass
class ExtractSummary:
    extracted: int = 0
    files: int = 0
    trashed: int = 0
    refused: list[tuple[int, str]] = field(default_factory=list)


def _type_of(name: str) -> str:
    return ENTRY_TYPES.get(name.rpartition(".")[2].casefold(), "autre") if "." in name else "autre"


def folder_name(archive_name: str) -> str:
    lowered = archive_name.casefold()
    for double in _DOUBLE_EXTS:
        if lowered.endswith(double):
            return archive_name[: -len(double)] or archive_name
    stem, dot, _ext = archive_name.rpartition(".")
    return stem if dot and stem else archive_name


class ArchiveService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal

    # ---- consultation ------------------------------------------------------------------
    def rows(self, *, only_problems: bool = False) -> list[ArchiveRow]:
        rows = self._conn.execute(
            "SELECT f.id, f.rel_path, a.format, a.status, a.reason,"
            " (SELECT count(*) FROM archive_entry e WHERE e.archive_file_id = f.id"
            "  AND e.is_dir = 0 AND e.status = 'inspected' AND e.depth = 1),"
            " (SELECT count(*) FROM archive_entry e WHERE e.archive_file_id = f.id"
            "  AND e.is_dir = 0 AND e.status = 'inspected' AND e.depth = 1 AND EXISTS"
            "  (SELECT 1 FROM file_record d WHERE d.content_id = e.content_id"
            "   AND d.presence = 'present' AND d.id <> f.id)),"
            " (SELECT count(*) FROM archive_entry e WHERE e.archive_file_id = f.id"
            "  AND e.is_dir = 0 AND (lower(e.inner_path) LIKE '%.mq4' OR lower(e.inner_path)"
            "  LIKE '%.mq5' OR lower(e.inner_path) LIKE '%.ex4' OR lower(e.inner_path)"
            "  LIKE '%.ex5')),"
            " (SELECT count(*) FROM archive_entry e WHERE e.archive_file_id = f.id"
            "  AND e.is_dir = 0 AND lower(e.inner_path) LIKE '%.set')"
            " FROM archive_scan a JOIN file_record f ON f.id = a.file_id"
            " WHERE f.presence = 'present' ORDER BY f.rel_path"
        ).fetchall()
        result = [
            ArchiveRow(
                int(r[0]), r[1], r[2], r[3], int(r[5]), int(r[6]), int(r[7]), int(r[8]), r[4]
            )
            for r in rows
        ]
        if only_problems:
            result = [r for r in result if r.status != "ok"]
        return result

    def entries(self, archive_id: int) -> list[tuple[str, str, int | None, str, str]]:
        """(chemin dans l'archive, type, taille, état, présent sur le disque où ?)."""
        result = []
        for inner, size, status, reason, content_id, is_dir in self._conn.execute(
            "SELECT inner_path, size, status, reason, content_id, is_dir FROM archive_entry"
            " WHERE archive_file_id = ? ORDER BY inner_path",
            (archive_id,),
        ):
            if is_dir:
                continue
            where = "—"
            if content_id is not None:
                found = self._conn.execute(
                    "SELECT rel_path FROM file_record WHERE content_id = ? AND id <> ?"
                    " AND presence = 'present' ORDER BY rel_path LIMIT 1",
                    (content_id, archive_id),
                ).fetchone()
                where = f"oui : {found[0]}" if found else "non (absent du disque)"
            state = "lu" if status == "inspected" else f"{status} : {reason or ''}"
            result.append((inner, _type_of(inner), size, state, where))
        return result

    # ---- décompression ----------------------------------------------------------------
    def eligible(self) -> list[int]:
        """Archives entièrement lues sans problème, présentes, non encore décompressées."""
        return [
            int(r[0])
            for r in self._conn.execute(
                "SELECT a.file_id FROM archive_scan a JOIN file_record f ON f.id = a.file_id"
                " WHERE a.status = 'ok' AND f.presence = 'present' AND f.in_quarantine = 0"
                " AND NOT EXISTS (SELECT 1 FROM archive_extraction x"
                "  WHERE x.archive_file_id = a.file_id)"
                " ORDER BY f.rel_path"
            )
        ]

    def extract(
        self,
        archive_ids: list[int],
        backend: TrashBackend | None,
        *,
        trash_archive: bool,
    ) -> ExtractSummary:
        summary = ExtractSummary()
        deletion = DeletionService(self._conn, self._clock, self._journal, backend)
        for archive_id in dict.fromkeys(archive_ids):
            try:
                files, destination = self._extract_one(archive_id)
            except (ArchiveError, ExtractError) as exc:
                summary.refused.append((archive_id, str(exc)))
                self._journal.append(
                    ACTOR_USER,
                    "archive.extract",
                    f"archive={archive_id}",
                    result="refused",
                    details={"motif": str(exc)},
                )
                continue
            summary.extracted += 1
            summary.files += files
            trashed = False
            if trash_archive and backend is not None:
                trashed = deletion.trash_verified(archive_id, "archives", "extraction", destination)
                summary.trashed += trashed
            with transaction(self._conn):
                self._conn.execute(
                    "INSERT INTO archive_extraction(archive_file_id, destination_bytes, files,"
                    " bytes, archive_trashed, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        archive_id,
                        destination,
                        files,
                        0,
                        int(trashed),
                        iso_utc(self._clock.now()),
                    ),
                )
            self._journal.append(
                ACTOR_USER,
                "archive.extract",
                destination.decode("utf-8", "replace"),
                details={"archive": archive_id, "fichiers": files, "archive_corbeille": trashed},
            )
        return summary

    def trash_redundant(
        self, archive_ids: list[int], backend: TrashBackend | None
    ) -> ExtractSummary:
        """Corbeille des archives **déjà décompressées** : chaque fichier qu'elles contiennent
        existe déjà sur le disque (même empreinte). Les autres sont laissées en place."""
        summary = ExtractSummary()
        deletion = DeletionService(self._conn, self._clock, self._journal, backend)
        redundant = {
            r.file_id: r for r in self.rows() if r.status == "ok" and r.files and not r.unique
        }
        for archive_id in dict.fromkeys(archive_ids):
            if archive_id not in redundant:
                summary.refused.append(
                    (archive_id, "contient des fichiers absents du disque, ou n'est pas lisible")
                )
                continue
            keeper = self._conn.execute(
                "SELECT s.path, d.rel_path_bytes FROM archive_entry e"
                " JOIN file_record d ON d.content_id = e.content_id"
                " JOIN source_root s ON s.id = d.root_id WHERE e.archive_file_id = ?"
                " AND d.presence = 'present' AND d.id <> ? LIMIT 1",
                (archive_id, archive_id),
            ).fetchone()
            keeper_path = os.path.join(os.fsencode(keeper[0]), bytes(keeper[1]))  # noqa: PTH118
            if deletion.trash_verified(archive_id, "archives", "fichier", keeper_path):
                summary.trashed += 1
            else:
                summary.refused.append(
                    (archive_id, "archive modifiée, absente ou Corbeille refusée")
                )
        return summary

    def _extract_one(self, archive_id: int) -> tuple[int, bytes]:
        row = self._conn.execute(
            "SELECT s.path, f.rel_path_bytes, f.name, a.format, a.status, c.sha256, f.size,"
            " f.mtime_ns, f.inode, f.device, f.magic FROM archive_scan a"
            " JOIN file_record f ON f.id = a.file_id JOIN source_root s ON s.id = f.root_id"
            " JOIN content c ON c.id = f.content_id WHERE a.file_id = ? AND f.presence = 'present'",
            (archive_id,),
        ).fetchone()
        if row is None:
            raise ArchiveError("archive absente ou non analysée")
        if row[4] != "ok":
            raise ArchiveError("archive non lue entièrement (protégée, abîmée ou incomplète)")
        path = os.path.join(os.fsencode(row[0]), bytes(row[1]))  # noqa: PTH118
        identity = FileIdentity(int(row[6]), int(row[7]), int(row[8]), int(row[9]))
        try:
            if path_identity(path) != identity or hash_file(path).sha256 != bytes(row[5]):
                raise ArchiveError("archive modifiée depuis l'analyse : relancez-la")
        except (OSError, UnstableFileError) as exc:
            raise ArchiveError(f"archive illisible : {exc}") from exc
        expected = {
            str(inner): bytes(sha)
            for inner, sha in self._conn.execute(
                "SELECT e.inner_path, c.sha256 FROM archive_entry e"
                " JOIN content c ON c.id = e.content_id WHERE e.archive_file_id = ?"
                " AND e.is_dir = 0 AND e.status = 'inspected' AND e.depth = 1",
                (archive_id,),
            )
        }
        parent = os.path.dirname(path)  # noqa: PTH120 — chemins en octets
        base = os.fsencode(folder_name(str(row[2])))
        destination = os.path.join(parent, base)  # noqa: PTH118
        n = 2
        while os.path.lexists(destination):
            destination = os.path.join(parent, base + f" ({n})".encode())  # noqa: PTH118
            n += 1
        kind = str(row[10] or row[3])
        files, _bytes = extract_verified(path, kind, destination, expected)
        return files, destination
