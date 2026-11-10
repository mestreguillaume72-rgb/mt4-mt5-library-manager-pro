"""Service familles/versions (F6, phase 7).

Les familles sont **dérivées** (recalculées entièrement à chaque fois) : aucune donnée de
l'utilisateur n'y est stockée. Les SET y sont rattachés lorsqu'une association est acceptée
par l'utilisateur, ou de niveau « forte » et non rejetée.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass

from mtlm import ENGINE_VERSION
from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock
from mtlm.matching.families import METHOD_VERSION, FamilyInput, Member, build_families
from mtlm.store.database import transaction

CODE_TYPES = ("ea", "indicator", "script", "library", "service", "include")


@dataclass
class FamilySummary:
    job_id: int
    state: str
    families: int = 0
    members: int = 0
    multi_version: int = 0
    homonym_groups: int = 0
    with_sets: int = 0


@dataclass(frozen=True)
class FamilyRow:
    id: int
    display_name: str
    platform: str
    confidence: str
    members: int
    versions: int


@dataclass(frozen=True)
class MemberRow:
    file_id: int
    rel_path: str
    relation: str
    estimated_version: str | None
    version_basis: str | None
    confidence: str


class FamilyService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)

    def _inputs(self) -> list[FamilyInput]:
        names: dict[int, set[str]] = defaultdict(set)
        for content_id, name in self._conn.execute("SELECT content_id, name FROM mql_input"):
            names[int(content_id)].add(str(name))
        rows = self._conn.execute(
            "SELECT f.id, f.rel_path, f.root_id, f.ext, a.detected_type, a.platform,"
            " f.content_id, m.prop_version, m.prop_description, f.mtime_ns"
            " FROM file_record f JOIN file_analysis a ON a.file_id = f.id"
            " JOIN source_root s ON s.id = f.root_id"
            " LEFT JOIN mql_source_meta m ON m.content_id = f.content_id"
            " WHERE s.status = 'ok' AND f.presence = 'present'"
            f" AND (a.detected_type IN ({','.join('?' * len(CODE_TYPES))})"
            "      OR f.ext IN ('ex4', 'ex5'))",
            CODE_TYPES,
        ).fetchall()
        return [
            FamilyInput(
                int(r[0]),
                r[1],
                int(r[2]),
                r[3],
                r[4],
                r[5],
                r[6],
                r[7],
                r[8],
                frozenset(names.get(int(r[6]), ())) if r[6] is not None else frozenset(),
                int(r[9] or 0),
            )
            for r in rows
        ]

    def rebuild(self) -> FamilySummary:
        job_id = self._jobs.create("families", {"method": METHOD_VERSION})
        summary = FamilySummary(job_id=job_id, state="running")
        families = build_families(self._inputs())
        sets_by_robot: dict[int, list[int]] = defaultdict(list)
        for robot_id, set_id in self._conn.execute(
            "SELECT robot_file_id, set_file_id FROM association"
            " WHERE user_decision = 'accepted' OR (level = 'forte' AND user_decision = 'none')"
        ):
            sets_by_robot[int(robot_id)].append(int(set_id))
        with transaction(self._conn):
            self._conn.execute("DELETE FROM family_member")
            self._conn.execute("DELETE FROM file_family")
            for family in families:
                member_ids = {m.file_id for m in family.members}
                for member in list(family.members):
                    for set_id in sets_by_robot.get(member.file_id, ()):
                        if set_id not in member_ids:
                            member_ids.add(set_id)
                            family.members.append(Member(set_id, "set_for", None, None, "probable"))
                cursor = self._conn.execute(
                    "INSERT INTO file_family(logical_key, display_name, basis_json, confidence,"
                    " platform, engine_version) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        family.logical_key,
                        family.display_name,
                        json.dumps(family.basis, ensure_ascii=False),
                        family.confidence,
                        family.platform,
                        ENGINE_VERSION,
                    ),
                )
                family_id = int(cursor.lastrowid or 0)
                self._conn.executemany(
                    "INSERT INTO family_member(family_id, file_id, relation, estimated_version,"
                    " version_basis, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            family_id,
                            m.file_id,
                            m.relation,
                            m.estimated_version,
                            m.version_basis,
                            m.confidence,
                        )
                        for m in family.members
                    ],
                )
                summary.families += 1
                summary.members += len(family.members)
                relations = {m.relation for m in family.members}
                summary.multi_version += (
                    "version_variant" in relations
                    and sum(m.relation == "version_variant" for m in family.members) > 1
                )
                summary.homonym_groups += "homonym_different" in relations
                summary.with_sets += "set_for" in relations
        summary.state = "completed"
        self._jobs.finish(job_id, "completed", asdict(summary))
        self._journal.append(
            ACTOR_USER, "families.rebuild", METHOD_VERSION, details=asdict(summary)
        )
        return summary

    def find(
        self, *, text: str | None = None, min_members: int = 1, limit: int = 200
    ) -> list[FamilyRow]:
        clauses: list[str] = ["1 = 1"]
        params: list[object] = []
        if text:
            clauses.append("(ff.display_name LIKE ? OR ff.logical_key LIKE ?)")
            params += [f"%{text}%", f"%{text.casefold()}%"]
        rows = self._conn.execute(
            "SELECT ff.id, ff.display_name, ff.platform, ff.confidence, count(fm.file_id),"
            " count(CASE WHEN fm.relation IN ('version_variant', 'homonym_different',"
            " 'source_of') THEN 1 END)"
            " FROM file_family ff JOIN family_member fm ON fm.family_id = ff.id"
            f" WHERE {' AND '.join(clauses)} GROUP BY ff.id HAVING count(fm.file_id) >= ?"
            " ORDER BY count(fm.file_id) DESC, ff.display_name LIMIT ?",
            (*params, min_members, limit),
        ).fetchall()
        return [FamilyRow(int(r[0]), r[1], r[2], r[3], int(r[4]), int(r[5])) for r in rows]

    def detail(self, family_id: int) -> tuple[FamilyRow, list[str], list[MemberRow]] | None:
        head = self._conn.execute(
            "SELECT id, display_name, platform, confidence, basis_json FROM file_family"
            " WHERE id = ?",
            (family_id,),
        ).fetchone()
        if head is None:
            return None
        members = [
            MemberRow(int(r[0]), r[1], r[2], r[3], r[4], r[5])
            for r in self._conn.execute(
                "SELECT fm.file_id, f.rel_path, fm.relation, fm.estimated_version,"
                " fm.version_basis, fm.confidence FROM family_member fm"
                " JOIN file_record f ON f.id = fm.file_id WHERE fm.family_id = ?"
                " ORDER BY fm.relation, f.rel_path",
                (family_id,),
            )
        ]
        versions = sum(
            m.relation in ("version_variant", "homonym_different", "source_of") for m in members
        )
        row = FamilyRow(int(head[0]), head[1], head[2], head[3], len(members), versions)
        return row, json.loads(head[4]), members

    def family_of(self, file_id: int) -> int | None:
        row = self._conn.execute(
            "SELECT family_id FROM family_member WHERE file_id = ? ORDER BY family_id LIMIT 1",
            (file_id,),
        ).fetchone()
        return int(row[0]) if row else None
