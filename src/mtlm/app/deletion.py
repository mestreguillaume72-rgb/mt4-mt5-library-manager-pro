"""Mise à la Corbeille des doublons et versions choisis par l'utilisateur (1.3.0).

Décision du propriétaire : les doublons passent en quarantaine (copie vérifiée), puis
l'utilisateur **valide** leur suppression ; il peut aussi supprimer directement depuis
« Doublons » ou « Familles et versions ». La suppression envoie le fichier dans la
**Corbeille du Mac** (récupérable), jamais d'effacement définitif.

Garde-fous appliqués à **chaque** fichier, juste avant de le retirer :

1. il est présent, c'est un fichier ordinaire (pas un lien), et il est **inchangé** depuis
   l'analyse (taille, date, inode) et son empreinte SHA-256 est relue ;
2. une **copie identique est conservée** et vérifiée **octet par octet** : la référence de son
   groupe de doublons, une autre copie présente, ou sa copie en quarantaine. Une copie retirée
   pendant la même opération ne compte jamais comme copie conservée ;
3. sans copie identique (exemplaire unique, ex. une version d'une famille), la suppression
   est refusée, sauf si l'utilisateur l'a autorisée explicitement (``allow_unique``) ;
4. chaque retrait est enregistré (registre ``deletion_record`` + journal d'audit) et peut être
   annulé par « Remettre en place » tant que la Corbeille n'a pas été vidée.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field

from mtlm.app.duplicates import same_bytes
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.errors import MtlmError
from mtlm.fs.reader import FileIdentity, path_identity
from mtlm.hashing.sha256 import UnstableFileError, hash_file
from mtlm.store.database import transaction
from mtlm.transfer.trash import TrashBackend, TrashError, put_back

ORIGINS = ("doublons", "quarantaine", "familles", "archives")


class DeletionError(MtlmError):
    """Mise à la Corbeille impossible (fonction indisponible ou demande invalide)."""


@dataclass
class DeletionResult:
    trashed: int = 0
    trashed_bytes: int = 0
    unique: int = 0
    refused: list[tuple[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class DeletionRow:
    id: int
    file_id: int
    origin: str
    original_path: str
    trash_path: str
    size: int
    keeper: str
    state: str
    created_at: str


@dataclass(frozen=True)
class _File:
    file_id: int
    path: bytes
    sha256: bytes
    size: int
    identity: FileIdentity
    content_id: int


def _decode(path: bytes) -> str:
    return path.decode("utf-8", "replace")


class DeletionService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        clock: Clock,
        journal: AuditJournal,
        backend: TrashBackend | None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._backend = backend

    @property
    def available(self) -> bool:
        return self._backend is not None

    # ---- sélection --------------------------------------------------------------------------
    def surplus_of_group(self, group_id: int) -> list[int]:
        """Membres d'un groupe de doublons exacts, sauf la référence conservée."""
        reference = self._conn.execute(
            "SELECT reference_file_id FROM duplicate_group WHERE id = ?", (group_id,)
        ).fetchone()
        if reference is None or reference[0] is None:
            raise DeletionError(f"Groupe {group_id} inconnu ou sans référence conservée")
        return [
            int(r[0])
            for r in self._conn.execute(
                "SELECT file_id FROM duplicate_member WHERE group_id = ? AND file_id <> ?"
                " ORDER BY file_id",
                (group_id, int(reference[0])),
            )
        ]

    def originals_of_batch(self, batch_id: int) -> list[int]:
        """Originaux d'un lot de quarantaine dont la copie a été vérifiée."""
        return [
            int(r[0])
            for r in self._conn.execute(
                "SELECT file_id FROM quarantine_entry WHERE batch_id = ? AND state = 'verified'"
                " ORDER BY id",
                (batch_id,),
            )
        ]

    # ---- mise à la Corbeille --------------------------------------------------------------
    def _file(self, file_id: int) -> _File | None:
        row = self._conn.execute(
            "SELECT s.path, f.rel_path_bytes, c.sha256, f.size, f.mtime_ns, f.inode, f.device,"
            " f.content_id FROM file_record f JOIN source_root s ON s.id = f.root_id"
            " JOIN content c ON c.id = f.content_id WHERE f.id = ? AND f.presence = 'present'"
            " AND f.file_type = 'file' AND f.is_symlink = 0 AND f.hash_state = 'validated'"
            " AND s.status = 'ok'",
            (file_id,),
        ).fetchone()
        if row is None:
            return None
        return _File(
            file_id,
            os.path.join(os.fsencode(row[0]), bytes(row[1])),  # noqa: PTH118
            bytes(row[2]),
            int(row[3]),
            FileIdentity(int(row[3]), int(row[4]), int(row[5]), int(row[6])),
            int(row[7]),
        )

    def _unchanged(self, item: _File) -> bool:
        try:
            if path_identity(item.path) != item.identity:
                return False
            return hash_file(item.path, expected=item.identity).sha256 == item.sha256
        except (OSError, UnstableFileError):
            return False

    def _keeper(self, item: _File, excluded: set[int]) -> tuple[str, int | None, bytes] | None:
        """Copie identique conservée, vérifiée octet par octet (référence en priorité)."""
        candidates = self._conn.execute(
            "SELECT f.id, s.path, f.rel_path_bytes FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id"
            " LEFT JOIN duplicate_member m ON m.file_id = f.id"
            " WHERE f.content_id = ? AND f.id <> ? AND f.presence = 'present'"
            " AND f.file_type = 'file' AND f.is_symlink = 0 AND s.status = 'ok'"
            " ORDER BY coalesce(m.is_reference, 0) DESC, f.id",
            (item.content_id, item.file_id),
        ).fetchall()
        for other_id, root, rel in candidates:
            if int(other_id) in excluded:
                continue
            other = os.path.join(os.fsencode(root), bytes(rel))  # noqa: PTH118
            if same_bytes(item.path, other):
                return "fichier", int(other_id), other
        for (copy,) in self._conn.execute(
            "SELECT dest_path_bytes FROM quarantine_entry WHERE file_id = ? AND state = 'verified'"
            " ORDER BY id DESC",
            (item.file_id,),
        ):
            if copy is not None and same_bytes(item.path, bytes(copy)):
                return "quarantaine", None, bytes(copy)
        return None

    def trash(
        self, file_ids: list[int], origin: str, *, allow_unique: bool = False
    ) -> DeletionResult:
        if origin not in ORIGINS:
            raise DeletionError(f"Origine inconnue : {origin}")
        if self._backend is None:
            raise DeletionError("La mise à la Corbeille n'est disponible que sur Mac.")
        result = DeletionResult()
        removed: set[int] = set()
        for file_id in dict.fromkeys(file_ids):
            item = self._file(file_id)
            if item is None:
                result.refused.append((file_id, "fichier absent, non analysé ou non ordinaire"))
                continue
            if not self._unchanged(item):
                result.refused.append((file_id, "fichier modifié depuis l'analyse : relancez-la"))
                continue
            keeper = self._keeper(item, removed | {file_id})
            if keeper is None and not allow_unique:
                result.refused.append(
                    (file_id, "exemplaire unique : aucune copie identique n'est conservée")
                )
                continue
            try:
                location = self._backend(item.path)
            except (TrashError, OSError) as exc:
                result.refused.append((file_id, f"Corbeille : {exc}"))
                self._journal.append(
                    ACTOR_USER,
                    "trash.file",
                    f"fichier={file_id}",
                    result="failed",
                    details={"origine": origin, "erreur": str(exc)},
                )
                continue
            kind, keeper_id, keeper_path = keeper if keeper else ("aucun", None, None)
            now = iso_utc(self._clock.now())
            with transaction(self._conn):
                self._conn.execute(
                    "INSERT INTO deletion_record(file_id, origin, original_path_bytes,"
                    " trash_path_bytes, sha256, size, keeper_kind, keeper_file_id,"
                    " keeper_path_bytes, state, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'trashed', ?)",
                    (
                        file_id,
                        origin,
                        item.path,
                        location,
                        item.sha256,
                        item.size,
                        kind,
                        keeper_id,
                        keeper_path,
                        now,
                    ),
                )
                self._conn.execute(
                    "UPDATE file_record SET presence = 'missing' WHERE id = ?", (file_id,)
                )
                self._forget_duplicate(file_id)
            removed.add(file_id)
            result.trashed += 1
            result.trashed_bytes += item.size
            result.unique += keeper is None
            self._journal.append(
                ACTOR_USER,
                "trash.file",
                _decode(item.path),
                details={
                    "fichier": file_id,
                    "origine": origin,
                    "corbeille": _decode(location),
                    "sha256": item.sha256.hex(),
                    "copie_conservee": _decode(keeper_path) if keeper_path else None,
                    "exemplaire_unique": keeper is None,
                },
            )
        return result

    def trash_verified(
        self, file_id: int, origin: str, keeper_kind: str, keeper_path: bytes
    ) -> bool:
        """Corbeille d'un fichier dont la garantie a déjà été vérifiée par l'appelant (ex. une
        archive dont tout le contenu vient d'être décompressé et vérifié). Le fichier doit
        être inchangé depuis l'analyse. Retourne vrai s'il est parti à la Corbeille."""
        if self._backend is None or origin not in ORIGINS:
            return False
        item = self._file(file_id)
        if item is None or not self._unchanged(item):
            return False
        try:
            location = self._backend(item.path)
        except (TrashError, OSError) as exc:
            self._journal.append(
                ACTOR_USER,
                "trash.file",
                f"fichier={file_id}",
                result="failed",
                details={"origine": origin, "erreur": str(exc)},
            )
            return False
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO deletion_record(file_id, origin, original_path_bytes,"
                " trash_path_bytes, sha256, size, keeper_kind, keeper_file_id,"
                " keeper_path_bytes, state, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 'trashed', ?)",
                (
                    file_id,
                    origin,
                    item.path,
                    location,
                    item.sha256,
                    item.size,
                    keeper_kind,
                    keeper_path,
                    iso_utc(self._clock.now()),
                ),
            )
            self._conn.execute(
                "UPDATE file_record SET presence = 'missing' WHERE id = ?", (file_id,)
            )
            self._forget_duplicate(file_id)
        self._journal.append(
            ACTOR_USER,
            "trash.file",
            _decode(item.path),
            details={
                "fichier": file_id,
                "origine": origin,
                "corbeille": _decode(location),
                "garantie": _decode(keeper_path),
            },
        )
        return True

    def _forget_duplicate(self, file_id: int) -> None:
        """Le fichier quitte son groupe de doublons ; un groupe d'un seul fichier disparaît."""
        row = self._conn.execute(
            "SELECT group_id FROM duplicate_member WHERE file_id = ?", (file_id,)
        ).fetchone()
        if row is None:
            return
        group_id = int(row[0])
        self._conn.execute("DELETE FROM duplicate_member WHERE file_id = ?", (file_id,))
        left = int(
            self._conn.execute(
                "SELECT count(*) FROM duplicate_member WHERE group_id = ?", (group_id,)
            ).fetchone()[0]
        )
        if left < 2:
            self._conn.execute("DELETE FROM duplicate_member WHERE group_id = ?", (group_id,))
            self._conn.execute("DELETE FROM duplicate_group WHERE id = ?", (group_id,))
        else:
            self._conn.execute(
                "UPDATE duplicate_group SET member_count = ? WHERE id = ?", (left, group_id)
            )

    # ---- remise en place -------------------------------------------------------------------
    def put_back(self, deletion_id: int) -> None:
        row = self._conn.execute(
            "SELECT file_id, original_path_bytes, trash_path_bytes, sha256, state"
            " FROM deletion_record WHERE id = ?",
            (deletion_id,),
        ).fetchone()
        if row is None:
            raise DeletionError(f"Retrait {deletion_id} inconnu")
        if row[4] != "trashed":
            raise DeletionError("Ce fichier a déjà été remis en place")
        file_id, original, trashed, sha = int(row[0]), bytes(row[1]), bytes(row[2]), bytes(row[3])
        try:
            if hash_file(trashed).sha256 != sha:
                raise DeletionError("Le fichier de la Corbeille a changé : rien n'est fait")
            put_back(trashed, original)
        except (TrashError, OSError, UnstableFileError) as exc:
            self._journal.append(
                ACTOR_USER,
                "trash.put_back",
                f"retrait={deletion_id}",
                result="failed",
                details={"erreur": str(exc)},
            )
            raise DeletionError(str(exc)) from exc
        identity = path_identity(original)
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE deletion_record SET state = 'restored', restored_at = ? WHERE id = ?",
                (iso_utc(self._clock.now()), deletion_id),
            )
            self._conn.execute(
                "UPDATE file_record SET presence = 'present', mtime_ns = ?, inode = ?,"
                " device = ? WHERE id = ?",
                (identity.mtime_ns, identity.inode, identity.device, file_id),
            )
        self._journal.append(
            ACTOR_USER,
            "trash.put_back",
            _decode(original),
            details={"retrait": deletion_id, "fichier": file_id},
        )

    def records(self, limit: int = 2000) -> list[DeletionRow]:
        labels = {
            "fichier": "copie identique conservée",
            "quarantaine": "copie en quarantaine",
            "extraction": "contenu décompressé et vérifié",
        }
        return [
            DeletionRow(
                int(r[0]),
                int(r[1]),
                r[2],
                _decode(bytes(r[3])),
                _decode(bytes(r[4])),
                int(r[5]),
                labels.get(r[6], "aucune (exemplaire unique)"),
                r[7],
                r[8],
            )
            for r in self._conn.execute(
                "SELECT id, file_id, origin, original_path_bytes, trash_path_bytes, size,"
                " keeper_kind, state, created_at FROM deletion_record ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        ]
