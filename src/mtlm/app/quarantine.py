"""Quarantaine par **copie vérifiée** et restauration (F8, D-007, décision du propriétaire).

Déroulement imposé :

1. **Simulation** : liste des doublons exacts admissibles, destination, espace nécessaire,
   rapport enregistré ; un *jeton de confirmation* (empreinte du plan) est calculé.
2. **Confirmation** : l'exécution exige ce jeton ; si un fichier a changé depuis la
   simulation, le plan ne correspond plus et l'exécution est **refusée**.
3. **Exécution** : chaque fichier est copié et vérifié (voir :mod:`mtlm.transfer.copy`) vers
   ``<destination>/<lot>/<source>/<chemin d'origine>`` ; manifeste JSON + journal JSONL
   dans le dossier du lot ; état par fichier ``planned → copying → verified``. Au premier
   doute (fichier modifié, disque plein, empreinte différente) : **arrêt**.
4. Les originaux ne sont **jamais** modifiés, déplacés ni supprimés ; les fichiers en
   quarantaine sont seulement marqués comme tels dans l'index (exclus de la bibliothèque
   organisée). Il n'existe **aucune purge**.
5. **Restauration** : retire la marque « en quarantaine ». Si l'original a disparu entre-temps
   (supprimé hors de l'application), il peut être recopié depuis la quarantaine, sur
   confirmation explicite, sans jamais écraser un fichier existant.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from mtlm.audit.journal import ACTOR_SYSTEM, ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import TaskControl
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths
from mtlm.fs.reader import FileIdentity
from mtlm.store.database import transaction
from mtlm.transfer.copy import CopyError, copy_verified
from mtlm.transfer.guards import check_destination, check_space
from mtlm.transfer.records import append_jsonl, ensure_directory, write_json_atomic

log = logging.getLogger("mtlm.quarantine")

MANIFEST = "manifeste.json"
JOURNAL = "journal.jsonl"


class QuarantineError(MtlmError):
    """Opération de quarantaine refusée ou arrêtée."""


@dataclass(frozen=True)
class PlanEntry:
    file_id: int
    source_root: str
    rel_path: str
    rel_path_bytes: bytes
    sha256: bytes
    size: int
    mtime_ns: int
    inode: int
    device: int
    group_id: int


@dataclass
class Simulation:
    batch_id: int
    token: str
    destination: str
    entries: int
    total_bytes: int
    excluded: list[tuple[int, str]]
    report_path: str


@dataclass
class ExecutionResult:
    batch_id: int
    status: str
    verified: int
    failed: int
    stopped_reason: str | None = None


@dataclass(frozen=True)
class BatchRow:
    id: int
    created_at: str
    destination: str
    status: str
    entries: int
    verified: int
    total_bytes: int


def _plan_token(destination: str, entries: list[PlanEntry]) -> str:
    digest = hashlib.sha256(destination.encode())
    for e in sorted(entries, key=lambda x: x.file_id):
        digest.update(f"{e.file_id}|{e.sha256.hex()}|{e.size}|{e.mtime_ns}|{e.inode}".encode())
    return digest.hexdigest()


def _safe_component(name: str) -> str:
    cleaned = "".join("_" if c in "/\\:\0" else c for c in name).strip() or "source"
    return cleaned[:120]


class QuarantineService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal, paths: AppPaths
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._paths = paths

    def _now(self) -> str:
        return iso_utc(self._clock.now())

    def _source_roots(self) -> list[Path]:
        return [
            Path(r[0])
            for r in self._conn.execute("SELECT path FROM source_root WHERE status <> 'removed'")
        ]

    def _admissible(self, file_ids: list[int] | None) -> list[PlanEntry]:
        sql = (
            "SELECT f.id, s.path, f.rel_path, f.rel_path_bytes, c.sha256, f.size, f.mtime_ns,"
            " f.inode, f.device, m.group_id FROM duplicate_member m"
            " JOIN file_record f ON f.id = m.file_id JOIN source_root s ON s.id = f.root_id"
            " JOIN content c ON c.id = f.content_id"
            " WHERE m.admissible_for_quarantine = 1 AND f.in_quarantine = 0"
            " AND f.presence = 'present' AND f.hash_state = 'validated'"
        )
        rows = self._conn.execute(sql + " ORDER BY f.id").fetchall()
        entries = [
            PlanEntry(
                int(r[0]),
                r[1],
                r[2],
                bytes(r[3]),
                bytes(r[4]),
                int(r[5]),
                int(r[6]),
                int(r[7]),
                int(r[8]),
                int(r[9]),
            )
            for r in rows
        ]
        if file_ids is not None:
            wanted = set(file_ids)
            entries = [e for e in entries if e.file_id in wanted]
        return entries

    # ---- 1. simulation ------------------------------------------------------------------
    def simulate(
        self, destination: Path, *, file_ids: list[int] | None = None, reason: str = ""
    ) -> Simulation:
        target = check_destination(
            destination,
            self._source_roots(),
            [self._paths.data_dir, self._paths.logs_dir],
            require_existing=True,
        )
        entries = self._admissible(file_ids)
        excluded: list[tuple[int, str]] = []
        if file_ids is not None:
            found = {e.file_id for e in entries}
            for file_id in file_ids:
                if file_id not in found:
                    row = self._conn.execute(
                        "SELECT inadmissible_reason FROM duplicate_member WHERE file_id = ?",
                        (file_id,),
                    ).fetchone()
                    excluded.append(
                        (file_id, row[0] if row and row[0] else "pas un doublon exact admissible")
                    )
        if not entries:
            raise QuarantineError(
                "Aucun doublon exact admissible à mettre en quarantaine (lancez « mtlm doublons »)."
            )
        total = sum(e.size for e in entries)
        token = _plan_token(str(target), entries)
        batch_uuid = uuid.uuid4().hex[:12]
        now = self._now()
        reports = self._paths.data_dir / "rapports"
        reports.mkdir(parents=True, exist_ok=True)
        report_path = reports / f"simulation-quarantaine-{batch_uuid}.json"
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO quarantine_batch(created_at, destination_root, dry_run_report_path,"
                " status, batch_uuid, plan_sha256, total_bytes, reason)"
                " VALUES (?, ?, ?, 'simulated', ?, ?, ?, ?)",
                (now, str(target), str(report_path), batch_uuid, token, total, reason),
            )
            batch_id = int(cursor.lastrowid or 0)
            for e in entries:
                dest = os.path.join(  # noqa: PTH118
                    os.fsencode(target),
                    batch_uuid.encode(),
                    os.fsencode(_safe_component(Path(e.source_root).name)),
                    e.rel_path_bytes,
                )
                self._conn.execute(
                    "INSERT INTO quarantine_entry(batch_id, file_id, source_path_bytes,"
                    " dest_path_bytes, sha256, size, source_mtime_ns, decision, reason, state,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'copie', ?, 'planned', ?)",
                    (
                        batch_id,
                        e.file_id,
                        os.path.join(os.fsencode(e.source_root), e.rel_path_bytes),  # noqa: PTH118
                        dest,
                        e.sha256,
                        e.size,
                        e.mtime_ns,
                        f"doublon exact du groupe {e.group_id} (référence conservée)",
                        now,
                    ),
                )
        report = {
            "lot": batch_id,
            "identifiant": batch_uuid,
            "destination": str(target),
            "jeton_de_confirmation": token,
            "fichiers": len(entries),
            "octets": total,
            "mode": "copie vérifiée — les originaux ne sont ni modifiés ni déplacés",
            "elements": [
                {
                    "fichier": e.file_id,
                    "chemin": e.rel_path,
                    "source": e.source_root,
                    "sha256": e.sha256.hex(),
                    "taille": e.size,
                }
                for e in entries
            ],
            "exclus": [{"fichier": f, "motif": m} for f, m in excluded],
        }
        with report_path.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=1)
        self._journal.append(
            ACTOR_USER,
            "quarantine.simulate",
            str(target),
            details={"lot": batch_id, "fichiers": len(entries), "octets": total},
        )
        return Simulation(
            batch_id, token, str(target), len(entries), total, excluded, str(report_path)
        )

    # ---- 2-3. confirmation et exécution --------------------------------------------------
    def execute(
        self, batch_id: int, token: str, *, control: TaskControl | None = None
    ) -> ExecutionResult:
        ctl = control or TaskControl()
        batch = self._conn.execute(
            "SELECT destination_root, plan_sha256, status, batch_uuid FROM quarantine_batch"
            " WHERE id = ?",
            (batch_id,),
        ).fetchone()
        if batch is None:
            raise QuarantineError(f"Lot {batch_id} inconnu")
        destination, expected, status, batch_uuid = batch
        if status in ("completed", "cancelled"):
            raise QuarantineError(f"Le lot {batch_id} est déjà {status}")
        if token != expected:
            self._journal.append(
                ACTOR_USER,
                "quarantine.confirm",
                f"lot={batch_id}",
                result="refused",
                details={"motif": "jeton incorrect"},
            )
            raise QuarantineError(
                "Confirmation refusée : le jeton ne correspond pas à la simulation de ce lot."
            )
        entries = self._conn.execute(
            "SELECT e.id, e.file_id, e.source_path_bytes, e.dest_path_bytes, e.sha256, e.size,"
            " e.state, f.mtime_ns, f.inode, f.device, f.size, f.in_quarantine, f.presence"
            " FROM quarantine_entry e JOIN file_record f ON f.id = e.file_id"
            " WHERE e.batch_id = ? ORDER BY e.id",
            (batch_id,),
        ).fetchall()
        current = [
            PlanEntry(
                int(r[1]), "", "", b"", bytes(r[4]), int(r[10]), int(r[7]), int(r[8]), int(r[9]), 0
            )
            for r in entries
        ]
        if status == "simulated" and _plan_token(destination, current) != expected:
            raise QuarantineError(
                "Plan invalidé : des fichiers ont changé depuis la simulation. "
                "Relancez inventaire, empreintes, doublons puis la simulation."
            )
        check_destination(
            Path(destination),
            self._source_roots(),
            [self._paths.data_dir, self._paths.logs_dir],
            require_existing=True,
        )
        self._verify_references(batch_id)
        remaining = sum(int(r[5]) for r in entries if r[6] != "verified")
        try:
            check_space(Path(destination), remaining)
        except MtlmError as exc:
            raise QuarantineError(str(exc)) from exc
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE quarantine_batch SET status = 'running',"
                " confirmed_at = coalesce(confirmed_at, ?), confirmation_token = ? WHERE id = ?",
                (self._now(), token, batch_id),
            )
        self._journal.append(
            ACTOR_USER, "quarantine.confirm", f"lot={batch_id}", details={"fichiers": len(entries)}
        )
        batch_dir = os.path.join(os.fsencode(destination), str(batch_uuid).encode())  # noqa: PTH118
        try:
            ensure_directory(batch_dir)
        except OSError as exc:
            raise QuarantineError(f"Destination non inscriptible : {exc.strerror or exc}") from exc
        self._write_manifest(batch_id, batch_dir)
        verified = sum(1 for r in entries if r[6] == "verified")
        failed = 0
        stopped: str | None = None
        for row in entries:
            entry_id, file_id, src, dst, sha, size, state = row[:7]
            if state == "verified":
                continue
            if ctl.cancelled:
                stopped = "annulé par l'utilisateur"
                break
            ctl.checkpoint()
            self._set_entry(entry_id, "copying")
            try:
                identity = FileIdentity(int(row[10]), int(row[7]), int(row[8]), int(row[9]))
                if os.path.lexists(bytes(dst)):
                    raise CopyError("une copie existe déjà à la destination (jamais écrasée)")
                copy_verified(
                    bytes(src), bytes(dst), expected_sha256=bytes(sha), expected_identity=identity
                )
            except (CopyError, OSError) as exc:
                failed += 1
                stopped = str(exc)
                self._set_entry(entry_id, "failed", stopped)
                self._log_line(
                    batch_dir,
                    {"entree": entry_id, "fichier": file_id, "etat": "failed", "erreur": stopped},
                )
                self._journal.append(
                    ACTOR_SYSTEM,
                    "quarantine.copy",
                    f"fichier={file_id}",
                    result="failed",
                    details={"lot": batch_id, "erreur": stopped},
                )
                break
            with transaction(self._conn):
                self._set_entry(entry_id, "verified", in_tx=True)
                self._conn.execute(
                    "UPDATE file_record SET in_quarantine = 1 WHERE id = ?", (file_id,)
                )
                self._conn.execute(
                    "UPDATE duplicate_member SET admissible_for_quarantine = 0,"
                    " inadmissible_reason = 'déjà en quarantaine' WHERE file_id = ?",
                    (file_id,),
                )
            verified += 1
            self._log_line(
                batch_dir,
                {
                    "entree": entry_id,
                    "fichier": file_id,
                    "etat": "verified",
                    "sha256": bytes(sha).hex(),
                    "taille": int(size),
                    "a": self._now(),
                },
            )
            self._journal.append(
                ACTOR_SYSTEM,
                "quarantine.copy",
                f"fichier={file_id}",
                details={"lot": batch_id, "sha256": bytes(sha).hex()},
            )
        final = (
            "completed"
            if stopped is None
            else ("cancelled" if stopped == "annulé par l'utilisateur" else "failed")
        )
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE quarantine_batch SET status = ? WHERE id = ?", (final, batch_id)
            )
        self._write_manifest(batch_id, batch_dir)
        self._journal.append(
            ACTOR_USER,
            "quarantine.end",
            f"lot={batch_id}",
            result="ok"
            if final == "completed"
            else "cancelled"
            if final == "cancelled"
            else "failed",
            details={"verifies": verified, "echecs": failed, "motif": stopped},
        )
        return ExecutionResult(batch_id, final, verified, failed, stopped)

    def _verify_references(self, batch_id: int) -> None:
        """Avant toute copie, la référence de chaque groupe concerné (le fichier conservé) doit
        exister et avoir exactement l'empreinte attendue, vérifiée à l'instant même. Sinon les
        membres ne sont plus des doublons prouvés : arrêt."""
        from mtlm.hashing.sha256 import UnstableFileError, hash_file

        rows = self._conn.execute(
            "SELECT DISTINCT g.id, g.sha256, s.path, f.rel_path_bytes, f.rel_path"
            " FROM quarantine_entry e JOIN duplicate_member m ON m.file_id = e.file_id"
            " JOIN duplicate_group g ON g.id = m.group_id"
            " JOIN file_record f ON f.id = g.reference_file_id"
            " JOIN source_root s ON s.id = f.root_id"
            " WHERE e.batch_id = ? AND e.state <> 'verified'",
            (batch_id,),
        ).fetchall()
        for group_id, sha, root, rel, shown in rows:
            path = os.path.join(os.fsencode(root), bytes(rel))  # noqa: PTH118
            try:
                ok = hash_file(path).sha256 == bytes(sha)
            except (OSError, UnstableFileError):
                ok = False
            if not ok:
                self._journal.append(
                    ACTOR_USER,
                    "quarantine.confirm",
                    f"lot={batch_id}",
                    result="refused",
                    details={
                        "motif": "référence modifiée ou absente",
                        "groupe": group_id,
                        "reference": shown,
                    },
                )
                raise QuarantineError(
                    f"Arrêt : la référence conservée « {shown} » (groupe {group_id}) a changé "
                    "ou n'est plus lisible. Les doublons ne sont plus prouvés : relancez "
                    "inventaire, empreintes et doublons."
                )
        missing = self._conn.execute(
            "SELECT count(*) FROM quarantine_entry e LEFT JOIN duplicate_member m"
            " ON m.file_id = e.file_id WHERE e.batch_id = ? AND e.state <> 'verified'"
            " AND m.file_id IS NULL",
            (batch_id,),
        ).fetchone()[0]
        if missing:
            raise QuarantineError(
                "Arrêt : des fichiers du lot ne sont plus des doublons exacts connus "
                "(relancez « mtlm doublons » et une simulation)."
            )

    def _set_entry(
        self, entry_id: int, state: str, error: str | None = None, *, in_tx: bool = False
    ) -> None:
        sql = "UPDATE quarantine_entry SET state = ?, error = ?, updated_at = ? WHERE id = ?"
        if in_tx:
            self._conn.execute(sql, (state, error, self._now(), entry_id))
        else:
            with transaction(self._conn):
                self._conn.execute(sql, (state, error, self._now(), entry_id))

    def _log_line(self, batch_dir: bytes, record: dict[str, object]) -> None:
        """Journal du lot dans la destination. Un échec (ex. disque plein) n'efface pas la
        traçabilité : l'état reste dans la base et le journal d'audit de l'application."""
        try:
            append_jsonl(os.path.join(batch_dir, JOURNAL.encode()), record)  # noqa: PTH118
        except OSError as exc:
            log.warning("Journal du lot non écrit (%s) : %s", exc, record)

    def _write_manifest(self, batch_id: int, batch_dir: bytes) -> None:
        batch = self._conn.execute(
            "SELECT created_at, destination_root, status, batch_uuid, plan_sha256, confirmed_at"
            " FROM quarantine_batch WHERE id = ?",
            (batch_id,),
        ).fetchone()
        entries = [
            {
                "entree": int(r[0]),
                "fichier": int(r[1]),
                "source": bytes(r[2]).decode("utf-8", "replace"),
                "destination": bytes(r[3]).decode("utf-8", "replace"),
                "sha256": bytes(r[4]).hex(),
                "taille": int(r[5]),
                "date_modification_ns": int(r[6]),
                "decision": r[7],
                "raison": r[8],
                "etat": r[9],
                "maj": r[10],
                "erreur": r[11],
            }
            for r in self._conn.execute(
                "SELECT id, file_id, source_path_bytes, dest_path_bytes, sha256, size,"
                " source_mtime_ns, decision, reason, state, updated_at, error"
                " FROM quarantine_entry WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            )
        ]
        manifest = {
            "application": "MT4 MT5 Library Manager PRO",
            "lot": batch_id,
            "identifiant": batch[3],
            "cree_le": batch[0],
            "confirme_le": batch[5],
            "destination": batch[1],
            "etat": batch[2],
            "jeton": batch[4],
            "mode": "copie vérifiée : originaux jamais modifiés, déplacés ni supprimés",
            "restauration": "mtlm quarantaine restaurer LOT (voir docs/utilisateur)",
            "entrees": entries,
        }
        try:
            write_json_atomic(os.path.join(batch_dir, MANIFEST.encode()), manifest)  # noqa: PTH118
        except OSError as exc:
            log.warning("Manifeste du lot %s non écrit : %s", batch_id, exc)
            self._journal.append(
                ACTOR_SYSTEM,
                "quarantine.manifest",
                f"lot={batch_id}",
                result="failed",
                details={"erreur": str(exc)},
            )

    # ---- reprise après fermeture ---------------------------------------------------------
    def mark_interrupted(self) -> list[int]:
        rows = [
            int(r[0])
            for r in self._conn.execute("SELECT id FROM quarantine_batch WHERE status = 'running'")
        ]
        if rows:
            with transaction(self._conn):
                self._conn.executemany(
                    "UPDATE quarantine_batch SET status = 'interrupted' WHERE id = ?",
                    [(i,) for i in rows],
                )
                self._conn.executemany(
                    "UPDATE quarantine_entry SET state = 'planned' WHERE batch_id = ?"
                    " AND state = 'copying'",
                    [(i,) for i in rows],
                )
        return rows

    def cancel(self, batch_id: int) -> None:
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE quarantine_batch SET status = 'cancelled' WHERE id = ?"
                " AND status IN ('simulated', 'interrupted', 'failed')",
                (batch_id,),
            )
        if cursor.rowcount == 0:
            raise QuarantineError(f"Le lot {batch_id} ne peut pas être annulé dans son état")
        self._journal.append(ACTOR_USER, "quarantine.cancel", f"lot={batch_id}")

    # ---- 5. restauration ----------------------------------------------------------------
    def restore(self, batch_id: int, *, recopy_missing: bool = False) -> tuple[int, int, int]:
        """Sort les fichiers du lot de la quarantaine. Retourne (restaurés, recopiés, conflits).

        ``recopy_missing`` : si l'original n'existe plus, il est recopié depuis la quarantaine
        (copie vérifiée, jamais d'écrasement). Si un fichier différent occupe son chemin :
        conflit, rien n'est fait pour ce fichier.
        """
        rows = self._conn.execute(
            "SELECT e.id, e.file_id, e.source_path_bytes, e.dest_path_bytes, e.sha256"
            " FROM quarantine_entry e WHERE e.batch_id = ? AND e.state IN ('verified', 'conflict')",
            (batch_id,),
        ).fetchall()
        if not rows:
            raise QuarantineError(f"Aucun fichier à restaurer dans le lot {batch_id}")
        restored = recopied = conflicts = 0
        for entry_id, file_id, src, dst, sha in rows:
            original, copy = bytes(src), bytes(dst)
            note: str | None = None
            if not os.path.lexists(original):
                if not recopy_missing:
                    self._set_entry(
                        int(entry_id),
                        "conflict",
                        "original absent : relancez avec la recopie autorisée",
                    )
                    conflicts += 1
                    continue
                try:
                    copy_verified(copy, original, expected_sha256=bytes(sha))
                    recopied += 1
                    note = "original recopié depuis la quarantaine"
                except CopyError as exc:
                    self._set_entry(int(entry_id), "conflict", str(exc))
                    conflicts += 1
                    continue
            elif not self._same_content(original, bytes(sha)):
                self._set_entry(
                    int(entry_id),
                    "conflict",
                    "un fichier différent occupe le chemin d'origine : rien n'est fait",
                )
                conflicts += 1
                continue
            with transaction(self._conn):
                self._set_entry(int(entry_id), "restored", note, in_tx=True)
                self._conn.execute(
                    "UPDATE file_record SET in_quarantine = 0 WHERE id = ?", (file_id,)
                )
            restored += 1
            self._journal.append(
                ACTOR_USER,
                "quarantine.restore",
                f"fichier={file_id}",
                details={"lot": batch_id, "note": note},
            )
        destination = self._conn.execute(
            "SELECT destination_root, batch_uuid FROM quarantine_batch WHERE id = ?", (batch_id,)
        ).fetchone()
        batch_dir = os.path.join(os.fsencode(destination[0]), str(destination[1]).encode())  # noqa: PTH118
        if os.path.isdir(batch_dir):  # noqa: PTH112
            self._write_manifest(batch_id, batch_dir)
        return restored, recopied, conflicts

    def _same_content(self, path: bytes, sha: bytes) -> bool:
        from mtlm.hashing.sha256 import UnstableFileError, hash_file

        try:
            return hash_file(path).sha256 == sha
        except (OSError, UnstableFileError):
            return False

    def batches(self) -> list[BatchRow]:
        return [
            BatchRow(int(r[0]), r[1], r[2], r[3], int(r[4]), int(r[5]), int(r[6]))
            for r in self._conn.execute(
                "SELECT b.id, b.created_at, b.destination_root, b.status, count(e.id),"
                " sum(e.state = 'verified'), b.total_bytes FROM quarantine_batch b"
                " LEFT JOIN quarantine_entry e ON e.batch_id = b.id GROUP BY b.id ORDER BY b.id"
            )
        ]

    def entries(self, batch_id: int) -> list[tuple[int, str, str, str | None]]:
        return [
            (int(r[0]), bytes(r[1]).decode("utf-8", "replace"), r[2], r[3])
            for r in self._conn.execute(
                "SELECT file_id, source_path_bytes, state, error FROM quarantine_entry"
                " WHERE batch_id = ? ORDER BY id",
                (batch_id,),
            )
        ]
