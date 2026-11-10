"""Consultation de l'inventaire : statistiques, liste paginée filtrée, erreurs (F10).

Toutes les valeurs proviennent de la base (jamais de valeurs fictives).
Pagination « par clé » (``id > dernier_id``) : stable et rapide à 100 000 lignes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from mtlm.formats.signatures import EXPECTED, LABELS


@dataclass(frozen=True)
class FileRow:
    id: int
    root_id: int
    rel_path: str
    name: str
    ext: str
    size: int | None
    mtime_ns: int | None
    file_type: str
    presence: str
    hash_state: str
    in_quarantine: bool


@dataclass(frozen=True)
class FileDetail:
    row: FileRow
    source_path: str
    rel_path_bytes: bytes
    sha256_hex: str | None
    hash_error: str | None
    hashed_with_engine: str | None
    first_seen_job: int | None
    last_seen_job: int | None
    is_dataless: bool
    other_paths_same_content: int
    magic: str | None = None
    magic_label: str | None = None
    misleading_extension: bool = False


@dataclass(frozen=True)
class FileFilter:
    source_id: int | None = None
    extensions: tuple[str, ...] = ()
    presence: str | None = "present"
    text: str | None = None  # recherche plein texte (nom, chemin), insensible aux accents
    hash_state: str | None = None
    file_type: str | None = None
    detected_type: str | None = None
    platform: str | None = None


@dataclass
class InventoryStats:
    files: int = 0
    total_bytes: int = 0
    missing: int = 0
    symlinks: int = 0
    by_extension: dict[str, int] = field(default_factory=dict)
    by_hash_state: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ScanErrorRow:
    job_id: int
    root_id: int
    rel_path: str
    errno: int | None
    message: str
    at: str


_COLUMNS = (
    "f.id, f.root_id, f.rel_path, f.name, f.ext, f.size, f.mtime_ns, f.file_type, f.presence,"
    " f.hash_state, f.in_quarantine"
)


def _fts_query(text: str) -> str:
    # Chaque mot devient un préfixe entre guillemets : aucune syntaxe FTS injectable.
    words = [w.replace('"', '""') for w in text.split() if w]
    return " ".join(f'"{w}"*' for w in words)


class InventoryService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _where(self, flt: FileFilter) -> tuple[str, list[object]]:
        clauses: list[str] = ["s.status <> 'removed'"]
        params: list[object] = []
        if flt.source_id is not None:
            clauses.append("f.root_id = ?")
            params.append(flt.source_id)
        if flt.extensions:
            clauses.append(f"f.ext IN ({','.join('?' * len(flt.extensions))})")
            params.extend(e.lower().lstrip(".") for e in flt.extensions)
        if flt.presence is not None:
            clauses.append("f.presence = ?")
            params.append(flt.presence)
        if flt.hash_state is not None:
            clauses.append("f.hash_state = ?")
            params.append(flt.hash_state)
        if flt.file_type is not None:
            clauses.append("f.file_type = ?")
            params.append(flt.file_type)
        if flt.detected_type is not None:
            clauses.append("f.id IN (SELECT file_id FROM file_analysis WHERE detected_type = ?)")
            params.append(flt.detected_type)
        if flt.platform is not None:
            clauses.append("f.id IN (SELECT file_id FROM file_analysis WHERE platform = ?)")
            params.append(flt.platform)
        if flt.text:
            query = _fts_query(flt.text)
            if query:
                clauses.append("f.id IN (SELECT rowid FROM search_fts WHERE search_fts MATCH ?)")
                params.append(query)
        return " AND ".join(clauses), params

    def page(self, flt: FileFilter, *, after_id: int = 0, limit: int = 200) -> list[FileRow]:
        where, params = self._where(flt)
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM file_record f JOIN source_root s ON s.id = f.root_id"
            f" WHERE {where} AND f.id > ? ORDER BY f.id LIMIT ?",
            (*params, after_id, limit),
        ).fetchall()
        return [
            FileRow(
                int(r[0]), int(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], bool(r[10])
            )
            for r in rows
        ]

    def count(self, flt: FileFilter) -> int:
        where, params = self._where(flt)
        row = self._conn.execute(
            f"SELECT count(*) FROM file_record f JOIN source_root s ON s.id = f.root_id"
            f" WHERE {where}",
            params,
        ).fetchone()
        return int(row[0])

    def stats(self, source_id: int | None = None) -> InventoryStats:
        flt = FileFilter(source_id=source_id, presence=None)
        where, params = self._where(flt)
        base = f"FROM file_record f JOIN source_root s ON s.id = f.root_id WHERE {where}"
        result = InventoryStats()
        row = self._conn.execute(
            f"SELECT count(*), coalesce(sum(f.size), 0),"
            f" sum(f.presence = 'missing'), sum(f.file_type = 'symlink') {base}",
            params,
        ).fetchone()
        missing = int(row[2] or 0)
        result.files = int(row[0]) - missing
        result.total_bytes = int(row[1])  # inclut les fichiers manquants (dernière taille connue)
        result.missing = missing
        result.symlinks = int(row[3] or 0)
        for ext, n in self._conn.execute(
            f"SELECT f.ext, count(*) {base} AND f.presence = 'present'"
            " GROUP BY f.ext ORDER BY count(*) DESC, f.ext",
            params,
        ):
            result.by_extension[ext or "(sans extension)"] = int(n)
        for state, n in self._conn.execute(
            f"SELECT f.hash_state, count(*) {base} AND f.presence = 'present'"
            " GROUP BY f.hash_state ORDER BY f.hash_state",
            params,
        ):
            result.by_hash_state[state] = int(n)
        return result

    def detail(self, file_id: int) -> FileDetail | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS}, s.path, f.rel_path_bytes, c.sha256, f.hash_error,"
            " f.hashed_with_engine, f.first_seen_job, f.last_seen_job, f.is_dataless,"
            " f.content_id, f.magic FROM file_record f JOIN source_root s ON s.id = f.root_id"
            " LEFT JOIN content c ON c.id = f.content_id WHERE f.id = ?",
            (file_id,),
        ).fetchone()
        if row is None:
            return None
        base = FileRow(
            int(row[0]),
            int(row[1]),
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            row[8],
            row[9],
            bool(row[10]),
        )
        same = 0
        if row[19] is not None:
            same = int(
                self._conn.execute(
                    "SELECT count(*) FROM file_record WHERE content_id = ? AND id <> ?"
                    " AND presence = 'present'",
                    (row[19], file_id),
                ).fetchone()[0]
            )
        return FileDetail(
            row=base,
            source_path=row[11],
            rel_path_bytes=bytes(row[12]),
            sha256_hex=bytes(row[13]).hex() if row[13] is not None else None,
            hash_error=row[14],
            hashed_with_engine=row[15],
            first_seen_job=row[16],
            last_seen_job=row[17],
            is_dataless=bool(row[18]),
            other_paths_same_content=same,
            magic=row[20],
            magic_label=LABELS.get(row[20]) if row[20] else None,
            misleading_extension=bool(row[20])
            and row[20] != "empty"
            and base.ext in EXPECTED
            and row[20] not in EXPECTED[base.ext],
        )

    def errors(self, job_id: int, limit: int = 1000) -> list[ScanErrorRow]:
        rows = self._conn.execute(
            "SELECT job_id, root_id, rel_path_bytes, errno, message, at FROM scan_error"
            " WHERE job_id = ? ORDER BY id LIMIT ?",
            (job_id, limit),
        ).fetchall()
        return [
            ScanErrorRow(
                int(r[0]), int(r[1]), bytes(r[2]).decode("utf-8", "replace"), r[3], r[4], r[5]
            )
            for r in rows
        ]


@dataclass(frozen=True)
class AnalysisInfo:
    detected_type: str
    platform: str
    certainty: str
    basis: list[str]
    limits: str | None
    warnings: list[str]
    encoding: str | None = None
    prop_version: str | None = None
    prop_copyright: str | None = None
    prop_description: str | None = None
    inputs: list[tuple[str, str, str | None, str]] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)


def analysis_of(conn: sqlite3.Connection, file_id: int) -> AnalysisInfo | None:
    """Résultat de la reconnaissance d'un fichier (type, certitude, preuves, limites)."""
    import json

    row = conn.execute(
        "SELECT detected_type, platform, certainty, basis_json, limits, warnings_json,"
        " content_id FROM file_analysis WHERE file_id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    info = AnalysisInfo(row[0], row[1], row[2], json.loads(row[3]), row[4], json.loads(row[5]))
    content_id = row[6]
    meta = conn.execute(
        "SELECT encoding, prop_version, prop_copyright, prop_description, entry_points_json"
        " FROM mql_source_meta WHERE content_id = ?",
        (content_id,),
    ).fetchone()
    if meta is None:
        return info
    inputs = [
        (r[0], r[1] or "?", r[2], r[3])
        for r in conn.execute(
            "SELECT name, mql_type, default_raw, modifier FROM mql_input WHERE content_id = ?"
            " ORDER BY ordinal",
            (content_id,),
        )
    ]
    includes = [
        r[0]
        for r in conn.execute(
            "SELECT target FROM mql_include WHERE content_id = ? ORDER BY line", (content_id,)
        )
    ]
    imports = [
        r[0]
        for r in conn.execute(
            "SELECT module FROM mql_import WHERE content_id = ? ORDER BY line", (content_id,)
        )
    ]
    return AnalysisInfo(
        info.detected_type,
        info.platform,
        info.certainty,
        info.basis,
        info.limits,
        info.warnings,
        meta[0],
        meta[1],
        meta[2],
        meta[3],
        inputs,
        includes,
        imports,
        json.loads(meta[4]),
    )
