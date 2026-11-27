"""Service « archives » (1.5.0) : ZIP, RAR, 7z, GZIP, BZIP2, XZ, TAR.

* **Sans décompresser** : chaque fichier contenu a son empreinte (étape « Formats et
  archives ») ; on dit s'il existe déjà sur le disque, quel type de fichier c'est, et si
  l'archive est **entièrement présente sur le disque** (déjà décompressée : on peut la
  supprimer sans rien perdre) ou contient des fichiers **absents du disque**.
* **Avec décompression** (choix de l'utilisateur : case « Décompresser les archives… » ou
  bouton sur l'écran Archives) : extraction vérifiée dans un nouveau dossier au nom de
  l'archive, à côté d'elle ; puis l'archive va à la Corbeille **seulement si tous les
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
from mtlm.core.i18n import tr
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
TOOL_LABELS = {
    "ea": "Robot",
    "indicator": "Indicateur",
    "script": "Script",
    "library": "Bibliothèque",
    "service": "Service",
}
#: Outils d'un type donné dans l'archive : type lu dans l'archive, sinon celui du même
#: fichier sur le disque. Compte par nom (source et compilé du même outil = 1).
_TOOL_COUNT = (
    "SELECT count(DISTINCT lower(substr(e.inner_path, 1, length(e.inner_path) - 4)))"
    " FROM archive_entry e WHERE e.archive_file_id = f.id AND e.is_dir = 0"
    " AND coalesce(coalesce(e.detected_type, (SELECT a.detected_type FROM file_record d"
    "  JOIN file_analysis a ON a.file_id = d.id WHERE d.content_id = e.content_id"
    "  AND d.presence = 'present' LIMIT 1)), '') {test}"
    " AND (lower(e.inner_path) LIKE '%.mq4' OR lower(e.inner_path) LIKE '%.mq5'"
    "  OR lower(e.inner_path) LIKE '%.ex4' OR lower(e.inner_path) LIKE '%.ex5')"
)
_ROBOT_COUNT = _TOOL_COUNT.format(test="= 'ea'")
_INDICATOR_COUNT = _TOOL_COUNT.format(test="= 'indicator'")
_OTHER_COUNT = _TOOL_COUNT.format(test="NOT IN ('ea', 'indicator')")
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
    robots: int = 0
    indicators: int = 0
    other_tools: int = 0
    encrypted_entries: int = 0

    @property
    def protected(self) -> bool:
        """Protégée par mot de passe, en entier ou en partie."""
        return self.status == "encrypted" or self.encrypted_entries > 0

    @property
    def contents(self) -> str:
        """Ce que contient l'archive, en mots : « 2 robots, 1 indicateur »."""
        parts = []
        if self.robots:
            parts.append(f"{self.robots} robot{'s' if self.robots > 1 else ''}")
        if self.indicators:
            parts.append(f"{self.indicators} indicateur{'s' if self.indicators > 1 else ''}")
        if self.other_tools:
            parts.append(
                tr("{other_tools} autre(s) (script ou non reconnu)", other_tools=self.other_tools)
            )
        return ", ".join(parts) or "—"

    @property
    def unique(self) -> int:
        return self.files - self.on_disk

    @property
    def verdict(self) -> str:
        if self.status == "encrypted":
            return tr("Protégée par mot de passe : non lue")
        if self.encrypted_entries:
            return tr(
                "Partiellement protégée par mot de passe : {encrypted_entries} "
                "fichier(s) non lu(s)",
                encrypted_entries=self.encrypted_entries,
            )
        if self.status in ("corrupt", "rejected"):
            return tr("Abîmée ou illisible")
        if self.status == "not_supported":
            return tr("Format non pris en charge sur ce Mac")
        if self.files == 0:
            return tr("Vide")
        if self.unique == 0:
            return tr("Déjà décompressée : tout est sur le disque")
        return tr("Contient {unique} fichier(s) absent(s) du disque", unique=self.unique)


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
    def rows(
        self, *, only_problems: bool = False, only_protected: bool = False
    ) -> list[ArchiveRow]:
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
            "  AND e.is_dir = 0 AND lower(e.inner_path) LIKE '%.set'),"
            f" ({_ROBOT_COUNT}), ({_INDICATOR_COUNT}), ({_OTHER_COUNT}),"
            " (SELECT count(*) FROM archive_entry e WHERE e.archive_file_id = f.id"
            "  AND (e.status = 'encrypted' OR e.is_encrypted = 1))"
            " FROM archive_scan a JOIN file_record f ON f.id = a.file_id"
            " WHERE f.presence = 'present' ORDER BY f.rel_path"
        ).fetchall()
        result = [
            ArchiveRow(
                int(r[0]),
                r[1],
                r[2],
                r[3],
                int(r[5]),
                int(r[6]),
                int(r[7]),
                int(r[8]),
                r[4],
                int(r[9]),
                int(r[10]),
                int(r[11]),
                int(r[12]),
            )
            for r in rows
        ]
        if only_problems:
            result = [r for r in result if r.status != "ok" or r.protected]
        if only_protected:
            result = [r for r in result if r.protected]
        return result

    def entries(self, archive_id: int) -> list[tuple[str, str, int | None, str, str]]:
        """(chemin dans l'archive, type, taille, état, présent sur le disque où ?)."""
        result = []
        for (
            inner,
            size,
            status,
            reason,
            content_id,
            is_dir,
            tool_type,
            disk_type,
        ) in self._conn.execute(
            "SELECT e.inner_path, e.size, e.status, e.reason, e.content_id, e.is_dir,"
            " e.detected_type, (SELECT a.detected_type FROM file_record d"
            "  JOIN file_analysis a ON a.file_id = d.id WHERE d.content_id = e.content_id"
            "  AND d.presence = 'present' AND a.detected_type IN"
            "  ('ea', 'indicator', 'script', 'library', 'service') LIMIT 1)"
            " FROM archive_entry e WHERE e.archive_file_id = ? ORDER BY e.inner_path",
            (archive_id,),
        ):
            if is_dir:
                continue
            kind = tool_type or disk_type
            where = "—"
            if content_id is not None:
                found = self._conn.execute(
                    "SELECT rel_path FROM file_record WHERE content_id = ? AND id <> ?"
                    " AND presence = 'present' ORDER BY rel_path LIMIT 1",
                    (content_id, archive_id),
                ).fetchone()
                where = tr("oui : {v}", v=found[0]) if found else tr("non (absent du disque)")
            state = "lu" if status == "inspected" else f"{status} : {reason or ''}"
            label = _type_of(inner)
            if kind in TOOL_LABELS:
                label = f"{TOOL_LABELS[kind]} ({label})"
            result.append((inner, label, size, state, where))
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
                    (
                        archive_id,
                        tr("contient des fichiers absents du disque, ou n'est pas lisible"),
                    )
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
                    (archive_id, tr("archive modifiée, absente ou Corbeille refusée"))
                )
        return summary

    def _extract_one(self, archive_id: int) -> tuple[int, bytes]:
        row = self._conn.execute(
            "SELECT s.path, f.rel_path_bytes, f.name, a.format, a.status, c.sha256, f.size,"
            " f.mtime_ns, f.inode, f.device, f.magic FROM archive_scan a"
            " JOIN file_record f ON f.id = a.file_id JOIN source_root s ON s.id = f.root_id"
            " LEFT JOIN content c ON c.id = f.content_id"
            " WHERE a.file_id = ? AND f.presence = 'present'",
            (archive_id,),
        ).fetchone()
        if row is None:
            raise ArchiveError(tr("archive absente ou non analysée"))
        if row[4] != "ok":
            raise ArchiveError(tr("archive non lue entièrement (protégée, abîmée ou incomplète)"))
        path = os.path.join(os.fsencode(row[0]), bytes(row[1]))  # noqa: PTH118
        identity = FileIdentity(int(row[6]), int(row[7]), int(row[8]), int(row[9]))
        try:
            if path_identity(path) != identity:
                raise ArchiveError(tr("archive modifiée depuis l'analyse : relancez-la"))
            if row[5] is not None and hash_file(path).sha256 != bytes(row[5]):
                raise ArchiveError(tr("archive modifiée depuis l'analyse : relancez-la"))
        except (OSError, UnstableFileError) as exc:
            raise ArchiveError(tr("archive illisible : {exc}", exc=exc)) from exc
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
