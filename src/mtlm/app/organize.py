"""Bibliothèque organisée (F9, scénario D) : prévisualisation puis copie vérifiée.

* La **prévisualisation** calcule l'arborescence cible (règles ci-dessous), les collisions de
  noms (résolues par suffixe déterministe « (2) », « (3) »… et rapportées), l'espace
  nécessaire et un jeton de confirmation.
* L'**exécution** copie chaque fichier avec vérification par empreinte (voir
  :mod:`mtlm.transfer.copy`) dans un **nouveau dossier** de la destination (jamais de mélange
  avec des fichiers existants, jamais d'écrasement). Elle peut être reprise : les éléments déjà
  vérifiés sont sautés. Au premier doute, elle s'arrête.
* Les originaux ne sont jamais modifiés. Les fichiers en quarantaine sont exclus ; par défaut,
  chaque contenu n'est copié qu'une fois (la référence de son groupe de doublons).

Règles par défaut (modèle ``standard``) :

* code : ``<Plateforme>/<Experts|Indicators|Scripts|Libraries|Include|Services>/<Famille>/
  [v<version>/]<nom>`` ;
* SET : ``<Plateforme>/SET/<associés|à vérifier|orphelins>/<Famille ou nom>/<nom>`` ;
* DLL : ``<Plateforme>/Libraries/<nom>`` ; modèles : ``Templates/<nom>`` ;
* annexes : ``Annexes/<extension>/<nom>`` ; inconnus : ``Inconnus/<extension>/<nom>``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mtlm.audit.journal import ACTOR_SYSTEM, ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import TaskControl
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths
from mtlm.fs.reader import FileIdentity
from mtlm.store.database import transaction
from mtlm.transfer.copy import CopyError, copy_verified
from mtlm.transfer.guards import check_destination, check_space
from mtlm.transfer.records import ensure_directory, write_json_atomic

TEMPLATE = "standard-v1"
PLATFORM_DIRS = {"mt4": "MT4", "mt5": "MT5", "unknown": "Plateforme inconnue"}
TYPE_DIRS = {
    "ea": "Experts",
    "indicator": "Indicators",
    "script": "Scripts",
    "library": "Libraries",
    "include": "Include",
    "service": "Services",
}
SET_STATUS_DIRS = {"associated": "associés", "to_check": "à vérifier", "orphan": "orphelins"}


class OrganizeError(MtlmError):
    """Prévisualisation ou copie organisée refusée ou arrêtée."""


@dataclass(frozen=True)
class PlannedItem:
    file_id: int
    source: bytes
    target: str
    size: int
    sha256: bytes
    identity: FileIdentity
    collision_of: int | None


@dataclass
class Preview:
    plan_id: int
    token: str
    destination: str
    items: int
    total_bytes: int
    collisions: int
    excluded_quarantine: int
    excluded_duplicates: int
    tree: dict[str, int] = field(default_factory=dict)


@dataclass
class OrganizeResult:
    plan_id: int
    status: str
    verified: int
    skipped: int
    failed: int
    stopped_reason: str | None = None


def _component(text: str) -> str:
    cleaned = "".join("_" if c in "/\\:\0" else c for c in text).strip().strip(".")
    return (cleaned or "_")[:120]


def _with_suffix(path: str, n: int) -> str:
    directory, _, name = path.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    renamed = f"{stem} ({n}).{ext}" if dot and stem else f"{name} ({n})"
    return f"{directory}/{renamed}" if directory else renamed


class OrganizeService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal, paths: AppPaths
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._paths = paths

    def _source_roots(self) -> list[Path]:
        return [
            Path(r[0])
            for r in self._conn.execute("SELECT path FROM source_root WHERE status <> 'removed'")
        ]

    def _set_status(self) -> dict[int, str]:
        status: dict[int, str] = {}
        for set_id, decision, level in self._conn.execute(
            "SELECT set_file_id, user_decision, level FROM association"
        ):
            current = status.get(int(set_id))
            if decision == "accepted" or (level == "forte" and decision == "none"):
                status[int(set_id)] = "associated"
            elif decision != "rejected" and current != "associated":
                status[int(set_id)] = "to_check"
        return status

    def _families(self) -> dict[int, tuple[str, str | None, bool]]:
        """fichier → (nom de famille, version estimée, famille à plusieurs versions)."""
        multi = {
            int(r[0])
            for r in self._conn.execute(
                "SELECT family_id FROM family_member WHERE relation IN ('version_variant',"
                " 'homonym_different') GROUP BY family_id HAVING count(*) > 1"
            )
        }
        result: dict[int, tuple[str, str | None, bool]] = {}
        for file_id, family_id, name, version in self._conn.execute(
            "SELECT fm.file_id, fm.family_id, ff.display_name, fm.estimated_version"
            " FROM family_member fm JOIN file_family ff ON ff.id = fm.family_id"
            " ORDER BY fm.family_id"
        ):
            result.setdefault(int(file_id), (name, version, int(family_id) in multi))
        return result

    def _target(
        self,
        row: tuple[Any, ...],
        families: dict[int, tuple[str, str | None, bool]],
        set_status: dict[int, str],
    ) -> str:
        file_id, name, ext, detected, platform = (
            int(row[0]),
            str(row[1]),
            str(row[2] or ""),
            row[3],
            row[4],
        )
        plat = PLATFORM_DIRS.get(str(platform), PLATFORM_DIRS["unknown"])
        family, version, multi = families.get(file_id, (None, None, False))
        file_name = _component(name)
        if detected in TYPE_DIRS:
            parts = [plat, TYPE_DIRS[str(detected)], _component(family or Path(name).stem)]
            if multi and version and not version.startswith("n°"):
                parts.append(_component(f"v{version}"))
            return "/".join([*parts, file_name])
        if detected == "set":
            status = SET_STATUS_DIRS[set_status.get(file_id, "orphan")]
            group = family or Path(name).stem
            return "/".join([plat, "SET", status, _component(group), file_name])
        if detected == "dll":
            return "/".join([plat, "Libraries", file_name])
        if detected == "template":
            return f"Templates/{file_name}"
        if detected == "resource":
            return f"Annexes/{_component(ext or 'sans extension')}/{file_name}"
        if ext in ("ex4", "ex5"):
            return "/".join([plat, "Compilés non classés", file_name])
        return f"Inconnus/{_component(ext or 'sans extension')}/{file_name}"

    # ---- prévisualisation -------------------------------------------------------------
    def preview(self, destination: Path, *, include_duplicates: bool = False) -> Preview:
        target_root = check_destination(
            destination,
            self._source_roots(),
            [self._paths.data_dir, self._paths.logs_dir],
            require_existing=True,
        )
        folder = f"Bibliotheque-organisee-{self._clock.now():%Y%m%d}-{uuid.uuid4().hex[:6]}"
        plan_root = target_root / folder
        rows = self._conn.execute(
            "SELECT f.id, f.name, f.ext, a.detected_type, coalesce(a.platform, 'unknown'),"
            " s.path, f.rel_path_bytes, f.size, c.sha256, f.mtime_ns, f.inode, f.device,"
            " f.in_quarantine, f.content_id FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id JOIN content c ON c.id = f.content_id"
            " LEFT JOIN file_analysis a ON a.file_id = f.id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.hash_state = 'validated'"
            " AND f.file_type = 'file' ORDER BY f.id"
        ).fetchall()
        references = {
            int(r[0])
            for r in self._conn.execute(
                "SELECT reference_file_id FROM duplicate_group WHERE reference_file_id IS NOT NULL"
            )
        }
        families = self._families()
        # Même contenu = même programme : on retient la meilleure reconnaissance des copies.
        best: dict[int, tuple[str, str]] = {}
        rank = {"certain": 0, "probable": 1, "possible": 2, "unknown": 3}
        best_rank: dict[int, int] = {}
        for content_id, detected, platform, certainty in self._conn.execute(
            "SELECT f.content_id, a.detected_type, a.platform, a.certainty FROM file_analysis a"
            " JOIN file_record f ON f.id = a.file_id WHERE f.content_id IS NOT NULL"
        ):
            level = rank.get(certainty, 3)
            if detected != "unknown" and level < best_rank.get(int(content_id), 9):
                best_rank[int(content_id)] = level
                best[int(content_id)] = (detected, platform)
        set_status = self._set_status()
        seen_content: dict[int, int] = {}
        excluded_q = excluded_d = 0
        # Les références de doublons passent en premier : c'est la copie conservée.
        rows.sort(key=lambda r: (0 if int(r[0]) in references else 1, int(r[0])))
        planned: list[PlannedItem] = []
        taken: dict[str, int] = {}
        collisions = 0
        for r in rows:
            if int(r[12]):
                excluded_q += 1
                continue
            content_id = int(r[13])
            if not include_duplicates and content_id in seen_content:
                excluded_d += 1
                continue
            seen_content.setdefault(content_id, int(r[0]))
            row = list(r)
            if (row[3] in (None, "unknown")) and content_id in best:
                row[3], row[4] = best[content_id]
            target = self._target(tuple(row), families, set_status)
            key = unicodedata.normalize("NFC", target).casefold()
            collision_of = None
            if key in taken:
                collisions += 1
                collision_of = taken[key]
                n = 2
                while unicodedata.normalize("NFC", _with_suffix(target, n)).casefold() in taken:
                    n += 1
                target = _with_suffix(target, n)
                key = unicodedata.normalize("NFC", target).casefold()
            taken[key] = int(r[0])
            planned.append(
                PlannedItem(
                    int(r[0]),
                    os.path.join(os.fsencode(r[5]), bytes(r[6])),  # noqa: PTH118
                    target,
                    int(r[7]),
                    bytes(r[8]),
                    FileIdentity(int(r[7]), int(r[9]), int(r[10]), int(r[11])),
                    collision_of,
                )
            )
        if not planned:
            raise OrganizeError("Rien à organiser : lancez d'abord inventaire et empreintes.")
        total = sum(p.size for p in planned)
        digest = hashlib.sha256(f"{plan_root}|{TEMPLATE}|{include_duplicates}".encode())
        for p in planned:
            digest.update(f"{p.file_id}|{p.sha256.hex()}|{p.target}|{p.identity}".encode())
        token = digest.hexdigest()
        tree: dict[str, int] = {}
        for p in planned:
            top = "/".join(p.target.split("/")[:2])
            tree[top] = tree.get(top, 0) + 1
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO organize_plan(created_at, destination_root, rules_json, status,"
                " collisions_count, plan_sha256, template, total_bytes)"
                " VALUES (?, ?, ?, 'preview', ?, ?, ?, ?)",
                (
                    iso_utc(self._clock.now()),
                    str(plan_root),
                    json.dumps({"doublons_inclus": include_duplicates}),
                    collisions,
                    token,
                    TEMPLATE,
                    total,
                ),
            )
            plan_id = int(cursor.lastrowid or 0)
            self._conn.executemany(
                "INSERT INTO organize_item(plan_id, file_id, target_rel_path, collision_of,"
                " state, size, sha256_expected) VALUES (?, ?, ?, ?, 'planned', ?, ?)",
                [(plan_id, p.file_id, p.target, p.collision_of, p.size, p.sha256) for p in planned],
            )
        self._journal.append(
            ACTOR_USER,
            "organize.preview",
            str(plan_root),
            details={
                "plan": plan_id,
                "fichiers": len(planned),
                "collisions": collisions,
                "octets": total,
            },
        )
        return Preview(
            plan_id,
            token,
            str(plan_root),
            len(planned),
            total,
            collisions,
            excluded_q,
            excluded_d,
            dict(sorted(tree.items())),
        )

    def items(self, plan_id: int, limit: int = 1000) -> list[tuple[int, str, str, int | None]]:
        return [
            (int(r[0]), r[1], r[2], r[3])
            for r in self._conn.execute(
                "SELECT file_id, target_rel_path, state, collision_of FROM organize_item"
                " WHERE plan_id = ? ORDER BY target_rel_path LIMIT ?",
                (plan_id, limit),
            )
        ]

    # ---- exécution ---------------------------------------------------------------------------
    def execute(
        self, plan_id: int, token: str, *, control: TaskControl | None = None
    ) -> OrganizeResult:
        ctl = control or TaskControl()
        plan = self._conn.execute(
            "SELECT destination_root, plan_sha256, status FROM organize_plan WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if plan is None:
            raise OrganizeError(f"Plan {plan_id} inconnu")
        destination, expected, status = plan
        if status in ("completed", "cancelled"):
            raise OrganizeError(f"Le plan {plan_id} est déjà {status}")
        if token != expected:
            self._journal.append(
                ACTOR_USER,
                "organize.confirm",
                f"plan={plan_id}",
                result="refused",
                details={"motif": "jeton incorrect"},
            )
            raise OrganizeError(
                "Confirmation refusée : le jeton ne correspond pas à la "
                "prévisualisation de ce plan."
            )
        root = Path(destination)
        # Le dossier choisi par l'utilisateur (parent du dossier du plan) doit toujours exister.
        check_destination(
            root.parent,
            self._source_roots(),
            [self._paths.data_dir, self._paths.logs_dir],
            require_existing=True,
        )
        rows = self._conn.execute(
            "SELECT i.file_id, i.target_rel_path, i.state, i.size, i.sha256_expected, s.path,"
            " f.rel_path_bytes, f.size, f.mtime_ns, f.inode, f.device FROM organize_item i"
            " JOIN file_record f ON f.id = i.file_id JOIN source_root s ON s.id = f.root_id"
            " WHERE i.plan_id = ? ORDER BY i.target_rel_path",
            (plan_id,),
        ).fetchall()
        remaining = sum(int(r[3] or 0) for r in rows if r[2] != "verified")
        try:
            check_space(root.parent if not root.exists() else root, remaining)
        except MtlmError as exc:
            raise OrganizeError(str(exc)) from exc
        root_bytes = os.fsencode(root)
        try:
            ensure_directory(root_bytes)
        except OSError as exc:
            raise OrganizeError(f"Destination non inscriptible : {exc.strerror or exc}") from exc
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE organize_plan SET status = 'running' WHERE id = ?", (plan_id,)
            )
        self._journal.append(
            ACTOR_USER, "organize.confirm", f"plan={plan_id}", details={"fichiers": len(rows)}
        )
        verified = skipped = failed = 0
        stopped: str | None = None
        for row in rows:
            file_id, target, state = int(row[0]), str(row[1]), row[2]
            if state == "verified":
                skipped += 1
                continue
            if ctl.cancelled:
                stopped = "annulé par l'utilisateur"
                break
            ctl.checkpoint()
            source = os.path.join(os.fsencode(row[5]), bytes(row[6]))  # noqa: PTH118
            dest = os.path.join(root_bytes, os.fsencode(target))  # noqa: PTH118
            identity = FileIdentity(int(row[7]), int(row[8]), int(row[9]), int(row[10]))
            try:
                copy_verified(
                    source, dest, expected_sha256=bytes(row[4]), expected_identity=identity
                )
            except (CopyError, OSError) as exc:
                failed += 1
                stopped = str(exc)
                self._set_item(plan_id, file_id, "failed", stopped)
                self._journal.append(
                    ACTOR_SYSTEM,
                    "organize.copy",
                    f"fichier={file_id}",
                    result="failed",
                    details={"plan": plan_id, "erreur": stopped},
                )
                break
            self._set_item(plan_id, file_id, "verified", None, bytes(row[4]))
            verified += 1
        final = (
            "completed"
            if stopped is None
            else ("cancelled" if stopped == "annulé par l'utilisateur" else "failed")
        )
        with transaction(self._conn):
            self._conn.execute("UPDATE organize_plan SET status = ? WHERE id = ?", (final, plan_id))
        try:
            self._write_manifest(plan_id, root_bytes)
        except OSError as exc:  # ex. disque plein : l'état reste dans la base et l'audit
            self._journal.append(
                ACTOR_SYSTEM,
                "organize.manifest",
                f"plan={plan_id}",
                result="failed",
                details={"erreur": str(exc)},
            )
        self._journal.append(
            ACTOR_USER,
            "organize.end",
            f"plan={plan_id}",
            result="ok"
            if final == "completed"
            else "cancelled"
            if final == "cancelled"
            else "failed",
            details={
                "verifies": verified,
                "deja_faits": skipped,
                "echecs": failed,
                "motif": stopped,
            },
        )
        return OrganizeResult(plan_id, final, verified, skipped, failed, stopped)

    def _set_item(
        self, plan_id: int, file_id: int, state: str, error: str | None, sha: bytes | None = None
    ) -> None:
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE organize_item SET state = ?, error = ?, sha256_dest = ?"
                " WHERE plan_id = ? AND file_id = ?",
                (state, error, sha, plan_id, file_id),
            )

    def _write_manifest(self, plan_id: int, root: bytes) -> None:
        items = [
            {
                "fichier": int(r[0]),
                "source": r[1],
                "cible": r[2],
                "etat": r[3],
                "sha256": bytes(r[4]).hex() if r[4] else None,
                "collision_avec": r[5],
                "erreur": r[6],
            }
            for r in self._conn.execute(
                "SELECT i.file_id, f.rel_path, i.target_rel_path, i.state, i.sha256_expected,"
                " i.collision_of, i.error FROM organize_item i JOIN file_record f"
                " ON f.id = i.file_id WHERE i.plan_id = ? ORDER BY i.target_rel_path",
                (plan_id,),
            )
        ]
        plan = self._conn.execute(
            "SELECT created_at, status, collisions_count, template FROM organize_plan WHERE id = ?",
            (plan_id,),
        ).fetchone()
        write_json_atomic(
            os.path.join(root, b"manifeste-organisation.json"),  # noqa: PTH118
            {
                "application": "MT4 MT5 Library Manager PRO",
                "plan": plan_id,
                "cree_le": plan[0],
                "etat": plan[1],
                "modele": plan[3],
                "collisions_de_noms": plan[2],
                "note": "copie vérifiée par empreinte ; originaux jamais modifiés",
                "elements": items,
            },
        )

    def plans(self) -> list[tuple[int, str, str, int, int, int]]:
        return [
            (int(r[0]), r[1], r[2], int(r[3]), int(r[4] or 0), int(r[5]))
            for r in self._conn.execute(
                "SELECT p.id, p.destination_root, p.status, count(i.file_id),"
                " sum(i.state = 'verified'), p.collisions_count FROM organize_plan p"
                " LEFT JOIN organize_item i ON i.plan_id = p.id GROUP BY p.id ORDER BY p.id"
            )
        ]
