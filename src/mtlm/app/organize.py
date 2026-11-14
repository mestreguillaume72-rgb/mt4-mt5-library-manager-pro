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
* Propositions ciblées (1.3.0), validées par l'utilisateur dans « Familles et versions » :
  dossier d'une famille au nom du robot (:meth:`OrganizeService.preview_family`) et sources
  MQ4/MQ5 isolées avec leurs SET (:meth:`OrganizeService.preview_sources`).

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

from mtlm.app.companions import CompanionService
from mtlm.audit.journal import ACTOR_SYSTEM, ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import TaskControl
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths
from mtlm.fs.reader import FileIdentity
from mtlm.matching.names import logical_key
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
#: Dossiers des fichiers liés dans un dossier de famille (1.3.0).
COMPANION_DIRS = {
    "image": "Images",
    "son": "Sons",
    "document": "Documents",
    "modele": "Modèles",
    "include": "Include",
    "dll": "Bibliothèques",
    "autre": "Autres",
}


@dataclass(frozen=True)
class MqSourceRow:
    file_id: int
    rel_path: str
    detected_type: str
    ext: str
    sets: int
    linked: int
    dependencies: int


@dataclass(frozen=True)
class IsolationCandidate:
    source_id: int
    file_id: int
    rel_path: str
    reason: str


#: Dossiers « conteneurs » : une source qui y est rangée n'a pas de dossier propre.
STANDARD_CONTAINERS = {
    "experts",
    "indicators",
    "scripts",
    "libraries",
    "include",
    "files",
    "presets",
    "images",
    "sounds",
    "templates",
    "services",
    "mql4",
    "mql5",
    "profiles",
    "tester",
    "logs",
    "telechargements",
    "téléchargements",
    "downloads",
    "desktop",
    "bureau",
    "documents",
}
MAX_FOLDER_FILES = 2000


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
        return self._record_plan(
            plan_root,
            planned,
            collisions,
            TEMPLATE,
            {"doublons_inclus": include_duplicates},
            excluded_q,
            excluded_d,
        )

    def _record_plan(
        self,
        plan_root: Path,
        planned: list[PlannedItem],
        collisions: int,
        template: str,
        rules: dict[str, Any],
        excluded_q: int,
        excluded_d: int,
    ) -> Preview:
        total = sum(p.size for p in planned)
        digest = hashlib.sha256(
            f"{plan_root}|{template}|{json.dumps(rules, sort_keys=True)}".encode()
        )
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
                    json.dumps(rules, ensure_ascii=False),
                    collisions,
                    token,
                    template,
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
                "modele": template,
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

    # ---- propositions ciblées (1.3.0) : à valider par l'utilisateur ----------------------------
    def _destination(self, destination: Path) -> Path:
        return check_destination(
            destination,
            self._source_roots(),
            [self._paths.data_dir, self._paths.logs_dir],
            require_existing=True,
        )

    def _files(self, file_ids: list[int]) -> dict[int, tuple[Any, ...]]:
        """Fichiers présents, analysés et lisibles (dans l'ordre demandé)."""
        found: dict[int, tuple[Any, ...]] = {}
        for start in range(0, len(file_ids), 500):
            chunk = file_ids[start : start + 500]
            for r in self._conn.execute(
                "SELECT f.id, s.path, f.rel_path_bytes, f.size, c.sha256, f.mtime_ns, f.inode,"
                " f.device, f.content_id, f.name, f.rel_path, f.in_quarantine FROM file_record f"
                " JOIN source_root s ON s.id = f.root_id JOIN content c ON c.id = f.content_id"
                " WHERE f.presence = 'present' AND f.hash_state = 'validated'"
                " AND f.file_type = 'file' AND s.status = 'ok'"
                f" AND f.id IN ({','.join('?' * len(chunk))})",
                chunk,
            ):
                found[int(r[0])] = tuple(r)
        return {i: found[i] for i in file_ids if i in found}

    @staticmethod
    def _unique_folder(parent: Path, name: str) -> Path:
        candidate = parent / name
        n = 2
        while candidate.exists():
            candidate = parent / f"{name} ({n})"
            n += 1
        return candidate

    def _place(
        self, selection: list[tuple[tuple[Any, ...], str]], *, by_content: bool = True
    ) -> tuple[list[PlannedItem], int, int, int]:
        """Cibles → éléments du plan : quarantaine exclue, un seul exemplaire par contenu,
        collisions de noms résolues par suffixe « (2) »."""
        planned: list[PlannedItem] = []
        taken: dict[str, int] = {}
        seen: set[int] = set()
        collisions = excluded_q = excluded_d = 0
        for r, target in selection:
            if int(r[11]):
                excluded_q += 1
                continue
            identity = int(r[8]) if by_content else -int(r[0])
            if identity in seen:
                excluded_d += 1
                continue
            seen.add(identity)
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
                    os.path.join(os.fsencode(r[1]), bytes(r[2])),  # noqa: PTH118
                    target,
                    int(r[3]),
                    bytes(r[4]),
                    FileIdentity(int(r[3]), int(r[5]), int(r[6]), int(r[7])),
                    collision_of,
                )
            )
        return planned, collisions, excluded_q, excluded_d

    def _linked(self, tool_ids: list[int]) -> dict[int, str]:
        """Fichiers liés (certain ou probable) aux outils donnés : fichier → type."""
        linked: dict[int, str] = {}
        for row in CompanionService(self._conn, self._clock, self._journal).for_tools(tool_ids):
            if row.confidence in ("certain", "probable"):
                linked.setdefault(row.companion_id, row.kind)
        return linked

    def _family_selection(
        self, family_id: int, prefix: str = ""
    ) -> tuple[str, list[tuple[tuple[Any, ...], str]]]:
        """Fichiers d'une famille et tout ce qui va avec, avec leur emplacement cible."""
        head = self._conn.execute(
            "SELECT display_name FROM file_family WHERE id = ?", (family_id,)
        ).fetchone()
        if head is None:
            raise OrganizeError(f"Famille {family_id} inconnue : relancez l'étape « Familles »")
        members = [
            int(r[0])
            for r in self._conn.execute(
                "SELECT fm.file_id FROM family_member fm"
                " LEFT JOIN duplicate_member dm ON dm.file_id = fm.file_id"
                " WHERE fm.family_id = ? ORDER BY coalesce(dm.is_reference, 0) DESC, fm.file_id",
                (family_id,),
            )
        ]
        files = self._files(members)
        selection = []
        for r in files.values():
            folder = str(r[10]).rpartition("/")[0].rpartition("/")[2] or "Racine"
            selection.append((r, f"{prefix}{_component(folder)}/{_component(str(r[9]))}"))
        taken = set(files)
        # Outils dont la famille a besoin : indicateurs appelés, bibliothèques importées.
        companions = CompanionService(self._conn, self._clock, self._journal)
        used: dict[int, str] = {}
        for dep in companions.dependencies(members):
            if dep.user_id in files and dep.used_id not in taken:
                used.setdefault(dep.used_id, dep.kind)
        for used_id, r in self._files(sorted(used)).items():
            folder = "Indicateurs utilisés" if used[used_id] == "icustom" else "Bibliothèques"
            selection.append((r, f"{prefix}{folder}/{_component(str(r[9]))}"))
            taken.add(used_id)
        # Fichiers liés (images, sons, documents, modèles, DLL…) : « certain » ou « probable ».
        linked = self._linked(sorted(taken))
        for companion_id, kind in linked.items():
            if companion_id not in taken:
                for r in self._files([companion_id]).values():
                    folder = COMPANION_DIRS.get(kind, "Autres")
                    selection.append((r, f"{prefix}{folder}/{_component(str(r[9]))}"))
        return str(head[0]), selection

    def preview_family(self, destination: Path, family_id: int) -> Preview:
        """Proposition : toute la famille (versions, copies renommées, compilés, SET associés)
        réunie dans **un dossier au nom du robot**, chaque fichier sous le nom de son dossier
        d'origine (« tous les dossiers ensemble ») ; avec tout ce qui va avec : indicateurs
        utilisés (iCustom), bibliothèques et DLL importées, modèles .tpl, images, sons,
        documents. Copie vérifiée après validation."""
        return self.preview_families(destination, [family_id])

    def preview_families(self, destination: Path, family_ids: list[int]) -> Preview:
        """Une ou plusieurs familles. Une seule : dossier au nom du robot. Plusieurs : un
        dossier « Familles réunies <date> » avec un sous-dossier par robot."""
        ids = list(dict.fromkeys(family_ids))
        if not ids:
            raise OrganizeError("Choisissez au moins une famille.")
        target_root = self._destination(destination)
        selection: list[tuple[tuple[Any, ...], str]] = []
        names: list[str] = []
        for family_id in ids:
            name, items = self._family_selection(
                family_id, "" if len(ids) == 1 else f"{_component(self._family_name(family_id))}/"
            )
            names.append(name)
            selection.extend(items)
        folder = (
            _component(names[0])
            if len(ids) == 1
            else f"Familles réunies {self._clock.now():%Y-%m-%d}"
        )
        plan_root = self._unique_folder(target_root, folder)
        planned, collisions, excluded_q, excluded_d = self._place(selection)
        if not planned:
            raise OrganizeError("Aucun fichier présent dans ces familles.")
        return self._record_plan(
            plan_root,
            planned,
            collisions,
            "famille-v2",
            {"familles": ids, "noms": names},
            excluded_q,
            excluded_d,
        )

    def _family_name(self, family_id: int) -> str:
        row = self._conn.execute(
            "SELECT display_name FROM file_family WHERE id = ?", (family_id,)
        ).fetchone()
        if row is None:
            raise OrganizeError(f"Famille {family_id} inconnue : relancez l'étape « Familles »")
        return str(row[0])

    def mq_sources(
        self, *, text: str | None = None, ext: str | None = None, tool_type: str | None = None
    ) -> list[MqSourceRow]:
        """Sources MQ4/MQ5 présentes, avec ce qui les accompagne (écran « Sources MQ4/MQ5 »)."""
        clauses = ["f.presence = 'present'", "f.ext IN ('mq4', 'mq5')", "f.in_quarantine = 0"]
        params: list[object] = []
        if text:
            clauses.append("f.rel_path LIKE ?")
            params.append(f"%{text}%")
        if ext:
            clauses.append("f.ext = ?")
            params.append(ext)
        if tool_type:
            clauses.append("a.detected_type = ?")
            params.append(tool_type)
        return [
            MqSourceRow(int(r[0]), r[1], r[2] or "", r[3], int(r[4]), int(r[5]), int(r[6]))
            for r in self._conn.execute(
                "SELECT f.id, f.rel_path, a.detected_type, f.ext,"
                " (SELECT count(DISTINCT x.set_file_id) FROM association x"
                "  WHERE x.robot_file_id = f.id AND (x.user_decision = 'accepted'"
                "  OR (x.level = 'forte' AND x.user_decision = 'none'))),"
                " (SELECT count(*) FROM companion_link l WHERE l.tool_file_id = f.id"
                "  AND l.confidence IN ('certain', 'probable')),"
                " (SELECT count(*) FROM tool_dependency d WHERE d.user_file_id = f.id)"
                " FROM file_record f LEFT JOIN file_analysis a ON a.file_id = f.id"
                f" WHERE {' AND '.join(clauses)} ORDER BY f.rel_path LIMIT 20000",
                params,
            )
        ]

    def source_layout(self, source_ids: list[int]) -> dict[int, tuple[str, str]]:
        """Pour chaque source : (« dossier », chemin du dossier propre au robot) si elle est
        rangée dans un dossier qui ne contient qu'elle (et ses versions, compilés, SET,
        images…), sinon (« seul », "") : le fichier est copié seul."""
        rows = (
            self._conn.execute(
                "SELECT id, root_id, rel_path, name FROM file_record WHERE presence = 'present'"
                f" AND id IN ({','.join('?' * len(source_ids))})",
                source_ids,
            ).fetchall()
            if source_ids
            else []
        )
        layout: dict[int, tuple[str, str]] = {}
        for file_id, root_id, rel_path, name in rows:
            directory = str(rel_path).rpartition("/")[0]
            last = directory.rpartition("/")[2].casefold()
            if not directory or last in STANDARD_CONTAINERS:
                layout[int(file_id)] = ("seul", "")
                continue
            prefix = directory + "/"
            inside = self._conn.execute(
                "SELECT count(*) FROM file_record WHERE root_id = ? AND presence = 'present'"
                " AND substr(rel_path, 1, ?) = ?",
                (root_id, len(prefix), prefix),
            ).fetchone()[0]
            tools = {
                logical_key(str(n))
                for (n,) in self._conn.execute(
                    "SELECT name FROM file_record WHERE root_id = ? AND presence = 'present'"
                    " AND substr(rel_path, 1, ?) = ? AND ext IN ('mq4', 'mq5', 'ex4', 'ex5')",
                    (root_id, len(prefix), prefix),
                )
            }
            own = tools == {logical_key(str(name))} and int(inside) <= MAX_FOLDER_FILES
            layout[int(file_id)] = ("dossier", directory) if own else ("seul", "")
        return layout

    def isolation_candidates(self, source_ids: list[int]) -> list[IsolationCandidate]:
        """Fichiers qui peuvent aller avec chaque source (SET associés, fichiers liés,
        indicateurs utilisés, bibliothèques) et qui ne sont pas déjà dans son dossier : ils
        ne sont ajoutés que si l'utilisateur valide le lien."""
        layout = self.source_layout(source_ids)
        inside_of: dict[int, str] = {}
        paths = (
            {
                int(f): (int(root), str(rel))
                for f, root, rel in self._conn.execute(
                    "SELECT id, root_id, rel_path FROM file_record"
                    f" WHERE id IN ({','.join('?' * len(source_ids))})",
                    source_ids,
                )
            }
            if source_ids
            else {}
        )
        for source_id, (mode, directory) in layout.items():
            if mode == "dossier":
                inside_of[source_id] = f"{paths[source_id][0]}:{directory}/"
        found: dict[int, IsolationCandidate] = {}

        def add(source_id: int, file_id: int, reason: str) -> None:
            if file_id in found or file_id in paths:
                return
            row = self._conn.execute(
                "SELECT root_id, rel_path FROM file_record WHERE id = ? AND presence = 'present'",
                (file_id,),
            ).fetchone()
            if row is None:
                return
            prefix = inside_of.get(source_id)
            if prefix and f"{row[0]}:{row[1]}".startswith(prefix):
                return  # déjà copié avec le dossier du robot
            found[file_id] = IsolationCandidate(source_id, file_id, str(row[1]), reason)

        marks = ",".join("?" * len(source_ids))
        for set_id, robot_id, decision in (
            self._conn.execute(
                "SELECT set_file_id, robot_file_id, user_decision FROM association"
                f" WHERE robot_file_id IN ({marks}) AND (user_decision = 'accepted'"
                " OR (level = 'forte' AND user_decision = 'none'))"
                " ORDER BY user_decision = 'accepted' DESC, score DESC",
                source_ids,
            )
            if source_ids
            else []
        ):
            add(
                int(robot_id),
                int(set_id),
                "SET relié (validé par vous)" if decision == "accepted" else "SET relié (forte)",
            )
        companions = CompanionService(self._conn, self._clock, self._journal)
        for row in companions.for_tools(source_ids):
            if row.confidence in ("certain", "probable"):
                add(row.tool_id, row.companion_id, f"fichier lié ({row.confidence})")
        for dep in companions.dependencies(source_ids):
            if dep.user_id in layout:
                add(dep.user_id, dep.used_id, dep.evidence)
        return sorted(found.values(), key=lambda c: (c.source_id, c.rel_path))

    def preview_sources(
        self,
        destination: Path,
        file_ids: list[int] | None = None,
        extras: dict[int, int] | None = None,
    ) -> Preview:
        """Proposition : isoler les sources MQ4/MQ5 (toutes, ou ``file_ids`` choisies).

        * source rangée dans **son propre dossier** : le dossier est copié **complet, tel
          quel** (sous-dossiers compris) dans ``MQ4|MQ5/<nom du dossier>/`` ;
        * source **seule** au milieu d'autres fichiers : le fichier est copié seul dans
          ``MQ4|MQ5/<nom de l'outil>/`` ;
        * ``extras`` (fichier → source) : fichiers qui vont avec, ajoutés **seulement si
          l'utilisateur a validé le lien** (voir :meth:`isolation_candidates`).

        Copie vérifiée après validation ; rien n'est dédoublonné (copie fidèle)."""
        chosen = set(file_ids) if file_ids is not None else None
        if chosen is not None and not chosen:
            raise OrganizeError("Choisissez au moins une source MQ4/MQ5.")
        target_root = self._destination(destination)
        plan_root = self._unique_folder(
            target_root, f"Sources MQ4-MQ5 isolées {self._clock.now():%Y-%m-%d}"
        )
        source_ids = [
            int(r[0])
            for r in self._conn.execute(
                "SELECT id FROM file_record WHERE ext IN ('mq4', 'mq5') AND presence = 'present'"
                " AND in_quarantine = 0 ORDER BY rel_path"
            )
            if chosen is None or int(r[0]) in chosen
        ]
        sources = self._files(source_ids)
        layout = self.source_layout(list(sources))
        folder_of: dict[int, str] = {}
        selection: list[tuple[tuple[Any, ...], str]] = []
        copied_folders: dict[tuple[int, str], str] = {}
        for source_id, r in sources.items():
            platform = "MQ4" if str(r[9]).casefold().endswith(".mq4") else "MQ5"
            mode, directory = layout.get(source_id, ("seul", ""))
            if mode == "dossier":
                root_id = int(
                    self._conn.execute(
                        "SELECT root_id FROM file_record WHERE id = ?", (source_id,)
                    ).fetchone()[0]
                )
                key = (root_id, directory)
                if key not in copied_folders:
                    name = _component(directory.rpartition("/")[2])
                    copied_folders[key] = f"{platform}/{name}"
                    prefix = directory + "/"
                    members = [
                        int(f)
                        for (f,) in self._conn.execute(
                            "SELECT id FROM file_record WHERE root_id = ? AND presence = 'present'"
                            " AND file_type = 'file' AND substr(rel_path, 1, ?) = ?"
                            " ORDER BY rel_path",
                            (root_id, len(prefix), prefix),
                        )
                    ]
                    for member in self._files(members).values():
                        relative = str(member[10])[len(prefix) :]
                        selection.append(
                            (
                                member,
                                f"{copied_folders[key]}/"
                                + "/".join(_component(p) for p in relative.split("/")),
                            )
                        )
                folder_of[source_id] = copied_folders[key]
            else:
                folder = f"{platform}/{_component(Path(str(r[9])).stem)}"
                folder_of[source_id] = folder
                selection.append((r, f"{folder}/{_component(str(r[9]))}"))
        added = 0
        for file_id, source_id in (extras or {}).items():
            if source_id not in folder_of:
                continue
            for r in self._files([file_id]).values():
                selection.append((r, f"{folder_of[source_id]}/{_component(str(r[9]))}"))
                added += 1
        planned, collisions, excluded_q, excluded_d = self._place(selection, by_content=False)
        if not planned:
            raise OrganizeError("Aucune source MQ4/MQ5 analysée.")
        return self._record_plan(
            plan_root,
            planned,
            collisions,
            "mq-isolees-v2",
            {
                "sources": len(sources),
                "dossiers_complets": len(copied_folders),
                "fichiers_valides": added,
            },
            excluded_q,
            excluded_d,
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
