"""Service « fichiers liés » (1.3.0) : images, sons, documents, modèles et includes reliés
à l'outil avec lequel ils ont été faits. Dérivé (recalculé entièrement), lecture seule."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.matching.companions import KINDS, METHOD_VERSION, Companion, Tool, link_companions
from mtlm.matching.together import creation_batches
from mtlm.store.database import transaction

TOOL_TYPES = ("ea", "indicator", "script", "library", "service")
#: Placement d'un fichier lié par rapport à son outil (robot, indicateur, script…).
PLACEMENT_LABELS = {
    "avec_son_robot": "Rangé avec son outil",
    "en_vrac": "En vrac — outil retrouvé",
    "avec_autre_robot": "Rangé avec un autre outil",
}
KIND_LABELS = {
    "image": "image",
    "son": "son",
    "document": "document",
    "modele": "modèle de graphique",
    "include": "include (.mqh)",
    "autre": "autre",
}


@dataclass
class CompanionSummary:
    companions: int = 0
    linked: int = 0
    links: int = 0
    by_confidence: dict[str, int] | None = None


@dataclass(frozen=True)
class CompanionRow:
    companion_id: int
    companion_path: str
    kind: str
    tool_id: int
    tool_path: str
    confidence: str
    placement: str
    evidence: list[str]


def _split(rel_path: str) -> tuple[str, str]:
    directory, _, name = rel_path.rpartition("/")
    return directory, name


class CompanionService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal

    def rebuild(self) -> CompanionSummary:
        batches = creation_batches(
            [
                (int(f), int(m or 0))
                for f, m in self._conn.execute(
                    "SELECT id, mtime_ns FROM file_record WHERE presence = 'present'"
                    " AND file_type = 'file'"
                )
            ]
        )
        tools: list[Tool] = []
        tool_ids: set[int] = set()
        for file_id, root_id, rel_path in self._conn.execute(
            "SELECT f.id, f.root_id, f.rel_path FROM file_record f"
            " LEFT JOIN file_analysis a ON a.file_id = f.id JOIN source_root s ON s.id = f.root_id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.in_quarantine = 0 AND"
            f" (a.detected_type IN ({','.join('?' * len(TOOL_TYPES))})"
            "  OR f.ext IN ('ex4', 'ex5', 'mq4', 'mq5'))",
            TOOL_TYPES,
        ):
            directory, name = _split(str(rel_path))
            batch = batches.get(int(file_id))
            tools.append(
                Tool(int(file_id), int(root_id), directory, name, batch[0] if batch else None)
            )
            tool_ids.add(int(file_id))
        companions: list[Companion] = []
        for file_id, root_id, rel_path, ext in self._conn.execute(
            "SELECT f.id, f.root_id, f.rel_path, f.ext FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id WHERE s.status = 'ok'"
            " AND f.presence = 'present' AND f.in_quarantine = 0 AND f.file_type = 'file'"
            f" AND f.ext IN ({','.join('?' * len(KINDS))})",
            tuple(KINDS),
        ):
            if int(file_id) in tool_ids:
                continue
            directory, name = _split(str(rel_path))
            batch = batches.get(int(file_id))
            companions.append(
                Companion(
                    int(file_id),
                    int(root_id),
                    directory,
                    name,
                    KINDS[str(ext)],
                    batch[0] if batch else None,
                )
            )
        cited_by: dict[str, set[int]] = defaultdict(set)
        for file_id, target_key in self._conn.execute(
            "SELECT f.id, r.target_key FROM mql_reference r"
            " JOIN file_record f ON f.content_id = r.content_id WHERE f.presence = 'present'"
        ):
            cited_by[str(target_key)].add(int(file_id))
        for file_id, target in self._conn.execute(
            "SELECT f.id, i.target FROM mql_include i"
            " JOIN file_record f ON f.content_id = i.content_id WHERE f.presence = 'present'"
        ):
            name = str(target).replace("\\", "/").rpartition("/")[2].casefold()
            if name:
                cited_by[name].add(int(file_id))
        links = link_companions(companions, tools, cited_by)
        kind_of = {c.file_id: c.kind for c in companions}
        now = iso_utc(self._clock.now())
        with transaction(self._conn):
            self._conn.execute("DELETE FROM companion_link")
            self._conn.executemany(
                "INSERT INTO companion_link(companion_file_id, tool_file_id, kind, confidence,"
                " placement, evidence_json, computed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        link.companion_id,
                        link.tool_id,
                        kind_of[link.companion_id],
                        link.confidence,
                        link.placement,
                        json.dumps(link.evidence, ensure_ascii=False),
                        now,
                    )
                    for link in links
                ],
            )
        by_confidence: dict[str, int] = defaultdict(int)
        for link in links:
            by_confidence[link.confidence] += 1
        summary = CompanionSummary(
            companions=len(companions),
            linked=len({link.companion_id for link in links}),
            links=len(links),
            by_confidence=dict(by_confidence),
        )
        self._journal.append(
            ACTOR_USER,
            "companions.rebuild",
            METHOD_VERSION,
            details={
                "fichiers_annexes": summary.companions,
                "relies": summary.linked,
                "liens": summary.links,
            },
        )
        return summary

    def _rows(self, where: str, params: tuple[object, ...]) -> list[CompanionRow]:
        return [
            CompanionRow(int(r[0]), r[1], r[2], int(r[3]), r[4], r[5], r[6], json.loads(r[7]))
            for r in self._conn.execute(
                "SELECT l.companion_file_id, c.rel_path, l.kind, l.tool_file_id, t.rel_path,"
                " l.confidence, l.placement, l.evidence_json FROM companion_link l"
                " JOIN file_record c ON c.id = l.companion_file_id"
                " JOIN file_record t ON t.id = l.tool_file_id"
                f" WHERE c.presence = 'present' AND {where}"
                " ORDER BY l.confidence = 'certain' DESC, l.confidence = 'probable' DESC,"
                " c.rel_path",
                params,
            )
        ]

    def for_tools(self, tool_ids: list[int]) -> list[CompanionRow]:
        """Fichiers liés aux outils donnés (par exemple tous les membres d'une famille)."""
        if not tool_ids:
            return []
        return self._rows(f"l.tool_file_id IN ({','.join('?' * len(tool_ids))})", tuple(tool_ids))

    def all(self, placement: str | None = None, limit: int = 5000) -> list[CompanionRow]:
        rows = (
            self._rows("1 = 1", ())
            if placement is None
            else self._rows("l.placement = ?", (placement,))
        )
        return rows[:limit]

    def placement_counts(self) -> dict[str, int]:
        """Fichiers annexes par placement (meilleur lien), plus « sans outil trouvé »."""
        best: dict[int, str] = {}
        for companion_id, placement in self._conn.execute(
            "SELECT l.companion_file_id, l.placement FROM companion_link l"
            " JOIN file_record c ON c.id = l.companion_file_id WHERE c.presence = 'present'"
            " ORDER BY l.companion_file_id, l.placement = 'avec_son_robot' DESC"
        ):
            best.setdefault(int(companion_id), str(placement))
        counts = {"avec_son_robot": 0, "en_vrac": 0, "avec_autre_robot": 0}
        for value in best.values():
            counts[value] += 1
        total = int(
            self._conn.execute(
                "SELECT count(*) FROM file_record WHERE presence = 'present'"
                f" AND file_type = 'file' AND ext IN ({','.join('?' * len(KINDS))})",
                tuple(KINDS),
            ).fetchone()[0]
        )
        counts["sans_outil"] = max(0, total - len(best))
        return counts
