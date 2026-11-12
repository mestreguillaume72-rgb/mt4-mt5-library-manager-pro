"""Services SET (F5, phase 6) : analyse des SET, associations robot↔SET, validation.

* Analyse : chaque SET présent et dont l'empreinte est validée est lu (lecture seule,
  ≤ 2 Mio), vérifié contre son empreinte, décodé et structuré (paramètres bruts + normalisés).
* Associations : calculées par :mod:`mtlm.matching.associations` à partir de candidats
  trouvés par index (noms de paramètres, nom logique, dossier) — jamais un produit cartésien.
  Les décisions de l'utilisateur (acceptée/rejetée) sont **conservées** lors d'un recalcul.
* Validation : seule l'action explicite de l'utilisateur change ``user_decision`` ; chaque
  décision est inscrite au journal d'audit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass

from mtlm import ENGINE_VERSION
from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import TaskControl
from mtlm.core.errors import MtlmError
from mtlm.fs.reader import ReadOnlyFile
from mtlm.matching.associations import (
    METHOD_VERSION,
    Candidate,
    RobotInfo,
    SetInfo,
    rank_candidates,
)
from mtlm.matching.names import logical_key
from mtlm.matching.together import creation_batches
from mtlm.metatrader.encoding import decode_text
from mtlm.setfiles.parser import ParamDiff, SetDocument, compare_sets, parse_set, robot_named
from mtlm.store.database import transaction

log = logging.getLogger("mtlm.sets")

MAX_SET_BYTES = 2 * 1024 * 1024
ROBOT_TYPES = ("ea", "indicator", "script")
LEVEL_LABELS = {
    "forte": "forte",
    "moyenne": "moyenne",
    "faible": "faible",
    "a_verifier": "à vérifier",
}


class AssociationError(MtlmError):
    """Association inconnue ou décision invalide."""


@dataclass
class SetSummary:
    job_id: int
    state: str
    parsed: int = 0
    errors: int = 0
    with_warnings: int = 0
    mt4: int = 0
    mt5: int = 0
    unknown_format: int = 0


@dataclass
class AssociationSummary:
    job_id: int
    state: str
    sets: int = 0
    robots: int = 0
    associations: int = 0
    by_level: dict[str, int] | None = None
    orphans: int = 0
    decisions_kept: int = 0


@dataclass(frozen=True)
class AssociationRow:
    id: int
    robot_file_id: int
    robot_path: str
    set_file_id: int
    set_path: str
    score: float
    level: str
    user_decision: str
    placement: str = ""


#: Où se trouve un SET par rapport au robot proposé (information : ne change pas le score).
PLACEMENT_LABELS = {
    "avec_son_robot": "Rangé avec son robot",
    "en_vrac": "En vrac — correspondance trouvée",
    "avec_autre_robot": "Rangé avec un autre robot",
}


def placement_of(
    set_root: int, set_dir: str, robot_root: int, robot_dir: str, robot_dirs: set[tuple[int, str]]
) -> str:
    """« avec_son_robot » : même dossier que le robot proposé ; « avec_autre_robot » : dans le
    dossier d'un autre robot (peut-être mal rangé) ; sinon « en_vrac »."""
    if (set_root, set_dir) == (robot_root, robot_dir):
        return "avec_son_robot"
    if (set_root, set_dir) in robot_dirs:
        return "avec_autre_robot"
    return "en_vrac"


def _dir(rel_path: str) -> str:
    return rel_path.rpartition("/")[0]


def _abs(root: str, rel: bytes) -> bytes:
    return os.path.join(os.fsencode(root), rel)  # noqa: PTH118 — chemins en octets


class SetService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)

    # ---- analyse des SET -----------------------------------------------------------------
    def parse_all(
        self, source_id: int | None = None, *, control: TaskControl | None = None
    ) -> SetSummary:
        ctl = control or TaskControl()
        job_id = self._jobs.create("sets", {"source_id": source_id})
        summary = SetSummary(job_id=job_id, state="running")
        sql = (
            "SELECT f.id, s.path, f.rel_path_bytes, f.content_id, c.sha256 FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id JOIN content c ON c.id = f.content_id"
            " LEFT JOIN set_file sf ON sf.file_id = f.id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.hash_state = 'validated'"
            " AND f.ext = 'set' AND (sf.file_id IS NULL OR sf.engine_version IS NOT ?"
            "      OR sf.content_id IS NOT f.content_id)"
        )
        params: list[object] = [ENGINE_VERSION]
        if source_id is not None:
            sql += " AND f.root_id = ?"
            params.append(source_id)
        rows = self._conn.execute(sql + " ORDER BY f.id", params).fetchall()
        for start in range(0, len(rows), 200):
            ctl.checkpoint()
            with transaction(self._conn):
                for file_id, root, rel, content_id, sha in rows[start : start + 200]:
                    try:
                        data = self._read(_abs(root, bytes(rel)))
                    except (OSError, ValueError) as exc:
                        summary.errors += 1
                        log.warning("SET %s illisible : %s", file_id, exc)
                        continue
                    if hashlib.sha256(data).digest() != bytes(sha):
                        summary.errors += 1
                        log.warning("SET %s modifié depuis l'empreinte : ignoré", file_id)
                        continue
                    decoded = decode_text(data)
                    doc = parse_set(decoded.text, encoding=decoded.encoding)
                    if decoded.confidence < 0.5:
                        doc.warnings.append(f"encodage incertain ({decoded.encoding})")
                    self._store(int(file_id), int(content_id), decoded.encoding, doc)
                    summary.parsed += 1
                    summary.with_warnings += bool(doc.warnings)
                    if doc.format == "mt4":
                        summary.mt4 += 1
                    elif doc.format == "mt5":
                        summary.mt5 += 1
                    else:
                        summary.unknown_format += 1
        summary.state = "completed"
        self._jobs.finish(job_id, "completed", asdict(summary))
        self._journal.append(
            ACTOR_USER, "sets.parse", f"source={source_id or 'toutes'}", details=asdict(summary)
        )
        return summary

    def _read(self, path: bytes) -> bytes:
        chunks, total = [], 0
        with ReadOnlyFile(path) as handle:
            for chunk in handle.chunks():
                total += len(chunk)
                if total > MAX_SET_BYTES:
                    raise ValueError("SET trop volumineux (> 2 Mio)")
                chunks.append(chunk)
        return b"".join(chunks)

    def _store(self, file_id: int, content_id: int, encoding: str, doc: SetDocument) -> None:
        self._conn.execute("DELETE FROM set_parameter WHERE file_id = ?", (file_id,))
        self._conn.execute(
            "INSERT INTO set_file(file_id, format, encoding, line_count, param_count,"
            " duplicate_keys_json, warnings_json, normalized_sha256, content_id, engine_version,"
            " format_basis, robot_named) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(file_id) DO UPDATE SET format = excluded.format,"
            " encoding = excluded.encoding, line_count = excluded.line_count,"
            " param_count = excluded.param_count,"
            " duplicate_keys_json = excluded.duplicate_keys_json,"
            " warnings_json = excluded.warnings_json,"
            " normalized_sha256 = excluded.normalized_sha256, content_id = excluded.content_id,"
            " engine_version = excluded.engine_version, format_basis = excluded.format_basis,"
            " robot_named = excluded.robot_named",
            (
                file_id,
                doc.format,
                encoding,
                doc.line_count,
                len(doc.params),
                json.dumps(doc.duplicate_keys, ensure_ascii=False),
                json.dumps(doc.warnings, ensure_ascii=False),
                doc.normalized_sha256,
                content_id,
                ENGINE_VERSION,
                doc.format_basis,
                robot_named(doc.comments),
            ),
        )
        self._conn.executemany(
            "INSERT INTO set_parameter(file_id, ordinal, name, raw_value, normalized_value,"
            " estimated_type, opt_start, opt_step, opt_stop, opt_enabled, comment, line)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    file_id,
                    p.ordinal,
                    p.name,
                    p.raw_value,
                    p.normalized_value,
                    p.estimated_type,
                    p.opt_start,
                    p.opt_step,
                    p.opt_stop,
                    None if p.opt_enabled is None else int(p.opt_enabled),
                    p.comment,
                    p.line,
                )
                for p in doc.params
            ],
        )
        self._conn.execute(
            "UPDATE search_fts SET set_params = ? WHERE rowid = ?",
            (" ".join(p.name for p in doc.params), file_id),
        )

    def document(self, file_id: int) -> SetDocument | None:
        """Reconstitue le SET analysé depuis la base (pour l'affichage et la comparaison)."""
        from mtlm.setfiles.parser import SetParam

        row = self._conn.execute(
            "SELECT format, format_basis, duplicate_keys_json, warnings_json, line_count"
            " FROM set_file WHERE file_id = ?",
            (file_id,),
        ).fetchone()
        if row is None:
            return None
        doc = SetDocument(
            format=row[0],
            format_basis=row[1] or "",
            duplicate_keys=json.loads(row[2]),
            warnings=json.loads(row[3]),
            line_count=row[4] or 0,
        )
        for r in self._conn.execute(
            "SELECT ordinal, name, raw_value, normalized_value, estimated_type, line, opt_start,"
            " opt_step, opt_stop, opt_enabled, comment FROM set_parameter WHERE file_id = ?"
            " ORDER BY ordinal",
            (file_id,),
        ):
            doc.params.append(
                SetParam(
                    int(r[0]),
                    r[1],
                    r[2],
                    r[3],
                    r[4],
                    int(r[5] or 0),
                    r[6],
                    r[7],
                    r[8],
                    None if r[9] is None else bool(r[9]),
                    r[10],
                )
            )
        return doc

    def compare(self, a: int, b: int) -> list[ParamDiff] | None:
        """Comparaison paramètre par paramètre de deux SET analysés (None si l'un manque)."""
        left, right = self.document(a), self.document(b)
        if left is None or right is None:
            return None
        return compare_sets(left, right)


class AssociationService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)

    def _batches(self) -> dict[int, tuple[int, int]]:
        """Petits lots de fichiers datés du même instant (indice « créés ensemble »)."""
        return creation_batches(
            [
                (int(f), int(m or 0))
                for f, m in self._conn.execute(
                    "SELECT id, mtime_ns FROM file_record WHERE presence = 'present'"
                    " AND file_type = 'file'"
                )
            ]
        )

    def _robots(self, batches: dict[int, tuple[int, int]] | None = None) -> list[RobotInfo]:
        batches = batches or {}
        rows = self._conn.execute(
            "SELECT f.id, f.rel_path, f.root_id, a.platform, f.content_id, f.ext"
            " FROM file_record f JOIN file_analysis a ON a.file_id = f.id"
            " JOIN source_root s ON s.id = f.root_id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.in_quarantine = 0 AND"
            " (a.detected_type IN ('ea', 'indicator', 'script')"
            "  OR (f.ext IN ('ex4', 'ex5') AND a.detected_type = 'unknown'))"
        ).fetchall()
        inputs: dict[int, dict[str, tuple[str, str | None]]] = defaultdict(dict)
        for content_id, name, mql_type, default in self._conn.execute(
            "SELECT content_id, name, mql_type, default_raw FROM mql_input"
        ):
            inputs[int(content_id)][name] = (mql_type or "", default)
        robots = []
        for file_id, rel_path, root_id, platform, content_id, ext in rows:
            directory, _, name = str(rel_path).rpartition("/")
            has_source = ext in ("mq4", "mq5")
            robots.append(
                RobotInfo(
                    int(file_id),
                    name,
                    directory,
                    int(root_id),
                    platform,
                    content_id,
                    has_source,
                    inputs.get(int(content_id), {})
                    if has_source and content_id is not None
                    else {},
                    batches.get(int(file_id)),
                )
            )
        return robots

    def _sets(self, batches: dict[int, tuple[int, int]] | None = None) -> list[SetInfo]:
        batches = batches or {}
        params: dict[int, dict[str, tuple[str, str | None, str]]] = defaultdict(dict)
        for file_id, name, raw, normalized, estimated in self._conn.execute(
            "SELECT file_id, name, raw_value, normalized_value, estimated_type FROM set_parameter"
            " ORDER BY file_id, ordinal"
        ):
            params[int(file_id)][name] = (raw, normalized, estimated)
        result = []
        for file_id, rel_path, root_id, fmt, named in self._conn.execute(
            "SELECT f.id, f.rel_path, f.root_id, sf.format, sf.robot_named FROM set_file sf"
            " JOIN file_record f ON f.id = sf.file_id JOIN source_root s ON s.id = f.root_id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.in_quarantine = 0"
        ):
            directory, _, name = str(rel_path).rpartition("/")
            result.append(
                SetInfo(
                    int(file_id),
                    name,
                    directory,
                    int(root_id),
                    fmt,
                    params.get(int(file_id), {}),
                    named,
                    batches.get(int(file_id)),
                )
            )
        return result

    def compute(self, *, control: TaskControl | None = None) -> AssociationSummary:
        ctl = control or TaskControl()
        job_id = self._jobs.create("match", {"method": METHOD_VERSION})
        batches = self._batches()
        robots = self._robots(batches)
        sets = self._sets(batches)
        summary = AssociationSummary(
            job_id=job_id, state="running", sets=len(sets), robots=len(robots)
        )
        by_param: dict[str, list[RobotInfo]] = defaultdict(list)
        by_key: dict[str, list[RobotInfo]] = defaultdict(list)
        by_dir: dict[tuple[int, str], list[RobotInfo]] = defaultdict(list)
        by_batch: dict[int, list[RobotInfo]] = defaultdict(list)
        for robot in robots:
            for name in robot.inputs:
                by_param[name].append(robot)
            by_key[logical_key(robot.name)].append(robot)
            by_dir[(robot.root_id, robot.directory)].append(robot)
            if robot.batch is not None:
                by_batch[robot.batch[0]].append(robot)
        levels: dict[str, int] = defaultdict(int)
        for start in range(0, len(sets), 200):
            ctl.checkpoint()
            with transaction(self._conn):
                for set_info in sets[start : start + 200]:
                    candidates: dict[int, RobotInfo] = {}
                    for name in set_info.params:
                        for robot in by_param.get(name, ()):
                            candidates[robot.file_id] = robot
                    key = logical_key(set_info.name)
                    for length in range(3, len(key) + 1):
                        for robot in by_key.get(key[:length], ()):
                            candidates[robot.file_id] = robot
                    for robot in by_dir.get((set_info.root_id, set_info.directory), ()):
                        candidates[robot.file_id] = robot
                    if set_info.named_robot:
                        for robot in by_key.get(logical_key(set_info.named_robot), ()):
                            candidates[robot.file_id] = robot
                    if set_info.batch is not None:
                        for robot in by_batch.get(set_info.batch[0], ()):
                            candidates[robot.file_id] = robot
                    ranked = rank_candidates(set_info, list(candidates.values()))
                    summary.decisions_kept += self._save(set_info, ranked)
                    if not ranked:
                        summary.orphans += 1
                    for candidate in ranked:
                        levels[candidate.level] += 1
                        summary.associations += 1
        summary.by_level = dict(levels)
        summary.state = "completed"
        self._jobs.finish(job_id, "completed", asdict(summary))
        self._journal.append(
            ACTOR_USER, "associations.compute", METHOD_VERSION, details=asdict(summary)
        )
        return summary

    def _save(self, set_info: SetInfo, ranked: list[Candidate]) -> int:
        now = iso_utc(self._clock.now())
        existing = {
            int(robot): (int(aid), decision)
            for aid, robot, decision in self._conn.execute(
                "SELECT id, robot_file_id, user_decision FROM association WHERE set_file_id = ?",
                (set_info.file_id,),
            )
        }
        kept_decisions = 0
        wanted = {c.robot.file_id for c in ranked}
        for robot_id, (aid, decision) in existing.items():
            if robot_id not in wanted and decision == "none":
                self._conn.execute("DELETE FROM association WHERE id = ?", (aid,))
        for candidate in ranked:
            previous = existing.get(candidate.robot.file_id)
            if previous is None:
                cursor = self._conn.execute(
                    "INSERT INTO association(robot_file_id, set_file_id, score, level,"
                    " engine_version, computed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        candidate.robot.file_id,
                        set_info.file_id,
                        candidate.score,
                        candidate.level,
                        METHOD_VERSION,
                        now,
                    ),
                )
                association_id = int(cursor.lastrowid or 0)
            else:
                association_id = previous[0]
                kept_decisions += previous[1] != "none"
                self._conn.execute(
                    "UPDATE association SET score = ?, level = ?, engine_version = ?,"
                    " computed_at = ? WHERE id = ?",
                    (candidate.score, candidate.level, METHOD_VERSION, now, association_id),
                )
                self._conn.execute(
                    "DELETE FROM association_evidence WHERE association_id = ?", (association_id,)
                )
            self._conn.executemany(
                "INSERT INTO association_evidence(association_id, kind, weight, value, polarity,"
                " detail_json) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        association_id,
                        e.kind,
                        e.weight,
                        e.value,
                        e.polarity,
                        json.dumps(e.detail, ensure_ascii=False, sort_keys=True),
                    )
                    for e in candidate.evidence
                ],
            )
        return kept_decisions

    # ---- consultation et décisions -------------------------------------------------------
    def find(
        self,
        *,
        set_file_id: int | None = None,
        robot_file_id: int | None = None,
        level: str | None = None,
        limit: int = 200,
    ) -> list[AssociationRow]:
        clauses: list[str] = ["1 = 1"]
        params: list[object] = []
        if set_file_id is not None:
            clauses.append("a.set_file_id = ?")
            params.append(set_file_id)
        if robot_file_id is not None:
            clauses.append("a.robot_file_id = ?")
            params.append(robot_file_id)
        if level is not None:
            clauses.append("a.level = ?")
            params.append(level)
        rows = self._conn.execute(
            "SELECT a.id, a.robot_file_id, r.rel_path, a.set_file_id, s.rel_path, a.score,"
            " a.level, a.user_decision, r.root_id, s.root_id FROM association a"
            " JOIN file_record r ON r.id = a.robot_file_id"
            " JOIN file_record s ON s.id = a.set_file_id"
            f" WHERE {' AND '.join(clauses)} ORDER BY a.score DESC, a.id LIMIT ?",
            (*params, limit),
        ).fetchall()
        dirs = self.robot_dirs() if rows else set()
        return [
            AssociationRow(
                int(r[0]),
                int(r[1]),
                r[2],
                int(r[3]),
                r[4],
                float(r[5]),
                r[6],
                r[7],
                placement_of(int(r[9]), _dir(r[4]), int(r[8]), _dir(r[2]), dirs),
            )
            for r in rows
        ]

    def robot_dirs(self) -> set[tuple[int, str]]:
        """Dossiers qui contiennent au moins un robot (source ou compilé) présent."""
        return {
            (int(root_id), _dir(rel_path))
            for root_id, rel_path in self._conn.execute(
                "SELECT f.root_id, f.rel_path FROM file_record f"
                " JOIN file_analysis a ON a.file_id = f.id WHERE f.presence = 'present' AND"
                " (a.detected_type IN ('ea', 'indicator', 'script') OR f.ext IN ('ex4', 'ex5'))"
            )
        }

    def placements(self) -> dict[int, str]:
        """Placement de chaque SET par rapport à son meilleur robot : association acceptée,
        sinon la mieux notée non rejetée. Les SET sans robot proposé n'y figurent pas."""
        dirs = self.robot_dirs()
        result: dict[int, str] = {}
        for set_id, set_root, set_path, robot_root, robot_path in self._conn.execute(
            "SELECT a.set_file_id, s.root_id, s.rel_path, r.root_id, r.rel_path"
            " FROM association a JOIN file_record s ON s.id = a.set_file_id"
            " JOIN file_record r ON r.id = a.robot_file_id"
            " WHERE a.user_decision <> 'rejected' AND s.presence = 'present'"
            " AND r.presence = 'present'"
            " ORDER BY a.set_file_id, a.user_decision = 'accepted' DESC, a.score DESC, a.id"
        ):
            if int(set_id) in result:
                continue
            result[int(set_id)] = placement_of(
                int(set_root), _dir(set_path), int(robot_root), _dir(robot_path), dirs
            )
        return result

    def placement_counts(self) -> dict[str, int]:
        """Nombre de SET par placement, plus « orphelins » (aucun robot proposé)."""
        placed = self.placements()
        counts = {key: 0 for key in PLACEMENT_LABELS}
        for value in placed.values():
            counts[value] += 1
        total = int(
            self._conn.execute(
                "SELECT count(*) FROM set_file sf JOIN file_record f ON f.id = sf.file_id"
                " WHERE f.presence = 'present'"
            ).fetchone()[0]
        )
        counts["orphelins"] = total - len(placed)
        return counts

    def evidence(
        self, association_id: int
    ) -> list[tuple[str, float, float, str, dict[str, object]]]:
        return [
            (r[0], float(r[1]), float(r[2]), r[3], json.loads(r[4]))
            for r in self._conn.execute(
                "SELECT kind, weight, value, polarity, detail_json FROM association_evidence"
                " WHERE association_id = ? ORDER BY rowid",
                (association_id,),
            )
        ]

    def orphans(self, limit: int = 500) -> list[tuple[int, str]]:
        return [
            (int(r[0]), r[1])
            for r in self._conn.execute(
                "SELECT f.id, f.rel_path FROM set_file sf JOIN file_record f ON f.id = sf.file_id"
                " WHERE f.presence = 'present' AND NOT EXISTS"
                " (SELECT 1 FROM association a WHERE a.set_file_id = sf.file_id)"
                " ORDER BY f.id LIMIT ?",
                (limit,),
            )
        ]

    def decide(self, association_id: int, decision: str) -> AssociationRow:
        if decision not in ("accepted", "rejected", "none"):
            raise AssociationError(f"Décision invalide : {decision}")
        row = self._conn.execute(
            "SELECT robot_file_id, set_file_id FROM association WHERE id = ?", (association_id,)
        ).fetchone()
        if row is None:
            raise AssociationError(f"Association {association_id} inconnue")
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE association SET user_decision = ?, decided_at = ? WHERE id = ?",
                (
                    decision,
                    iso_utc(self._clock.now()) if decision != "none" else None,
                    association_id,
                ),
            )
        self._journal.append(
            ACTOR_USER,
            f"association.{decision}",
            f"association={association_id}",
            details={"robot": row[0], "set": row[1]},
        )
        return next(
            a for a in self.find(set_file_id=int(row[1]), limit=1000) if a.id == association_id
        )
