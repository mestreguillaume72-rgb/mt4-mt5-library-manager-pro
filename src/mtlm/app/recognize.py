"""Service de reconnaissance MetaTrader (F4, phase 5).

Ordre de travail : inventaire → empreintes → formats → **reconnaissance**.

1. Sources MQL (``.mq4/.mq5/.mqh``) : lecture seule (au plus 8 Mio), vérification que les
   octets lus correspondent à l'empreinte validée (sinon le fichier a changé : ignoré),
   analyse lexicale, enregistrement des métadonnées par **contenu** (deux copies identiques
   ne sont analysées qu'une fois).
2. Tous les fichiers : classement (type, plateforme, certitude, base, limites). Les EX4/EX5
   sont classés après les sources pour profiter de l'appariement par nom.

Un fichier malformé ne bloque jamais le traitement : l'erreur est enregistrée comme
avertissement et le fichier reste « unknown ».
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

from mtlm import ENGINE_VERSION
from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock, iso_utc
from mtlm.core.control import TaskControl
from mtlm.formats.signatures import EXPECTED
from mtlm.fs.reader import ReadOnlyFile
from mtlm.metatrader.classify import Classification, classify
from mtlm.metatrader.encoding import decode_text
from mtlm.metatrader.mql import (
    MqlSource,
    parse_mql,
    shingle_hashes,
    sketch,
    source_text_parts,
    tokens,
)
from mtlm.store.database import transaction

log = logging.getLogger("mtlm.recognize")

MAX_SOURCE_BYTES = 8 * 1024 * 1024
SOURCE_EXTS = ("mq4", "mq5", "mqh")


@dataclass
class RecognitionSummary:
    job_id: int
    state: str
    classified: int = 0
    sources_parsed: int = 0
    waiting_for_hash: int = 0
    warnings: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_certainty: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _File:
    id: int
    root: str
    rel_path: str
    rel_path_bytes: bytes
    ext: str
    magic: str | None
    content_id: int | None
    sha256: bytes | None
    hash_state: str
    root_id: int


BATCH = 500


class RecognitionService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)
        self._in_batch = False
        self._pairs: dict[tuple[int, str], str] | None = None

    @contextmanager
    def _tx(self) -> Iterator[None]:
        """Transaction propre, sauf si l'appel a lieu dans un lot déjà ouvert."""
        if self._in_batch:
            yield
        else:
            with transaction(self._conn):
                yield

    def _begin_batch(self) -> None:
        if not self._in_batch:
            self._conn.execute("BEGIN IMMEDIATE")
            self._in_batch = True

    def _commit_batch(self) -> None:
        if self._in_batch:
            self._conn.execute("COMMIT")
            self._in_batch = False

    def _pending(self, source_id: int | None) -> list[_File]:
        sql = (
            "SELECT f.id, s.path, f.rel_path, f.rel_path_bytes, f.ext, f.magic, f.content_id,"
            " c.sha256, f.hash_state, f.root_id FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id"
            " LEFT JOIN content c ON c.id = f.content_id"
            " LEFT JOIN file_analysis a ON a.file_id = f.id"
            " WHERE s.status = 'ok' AND f.presence = 'present'"
            " AND (a.file_id IS NULL OR a.engine_version <> ?"
            "      OR a.content_id IS NOT f.content_id)"
        )
        params: list[object] = [ENGINE_VERSION]
        if source_id is not None:
            sql += " AND f.root_id = ?"
            params.append(source_id)
        rows = self._conn.execute(sql + " ORDER BY f.id", params).fetchall()
        return [
            _File(
                int(r[0]),
                r[1],
                r[2],
                bytes(r[3]),
                r[4],
                r[5],
                r[6],
                bytes(r[7]) if r[7] is not None else None,
                r[8],
                int(r[9]),
            )
            for r in rows
        ]

    def run(
        self,
        source_id: int | None = None,
        *,
        control: TaskControl | None = None,
        progress: Callable[[RecognitionSummary], None] | None = None,
    ) -> RecognitionSummary:
        ctl = control or TaskControl()
        job_id = self._jobs.create("recognize", {"source_id": source_id})
        summary = RecognitionSummary(job_id=job_id, state="running")
        files = self._pending(source_id)
        # Sources d'abord, binaires compilés ensuite (appariement), le reste entre les deux.
        files.sort(
            key=lambda f: (2 if f.ext in ("ex4", "ex5") else 0 if f.ext in SOURCE_EXTS else 1, f.id)
        )
        types: Counter[str] = Counter()
        certainties: Counter[str] = Counter()
        self._pairs = None
        try:
            self._process(files, ctl, summary, types, certainties, progress)
        except BaseException:
            if self._in_batch:
                self._conn.execute("ROLLBACK")
                self._in_batch = False
            raise
        self._commit_batch()
        summary.by_type = dict(types)
        summary.by_certainty = dict(certainties)
        summary.state = "completed"
        self._jobs.finish(job_id, "completed", asdict(summary))
        self._journal.append(
            ACTOR_USER, "recognize.run", f"source={source_id or 'toutes'}", details=asdict(summary)
        )
        return summary

    def _process(
        self,
        files: list[_File],
        ctl: TaskControl,
        summary: RecognitionSummary,
        types: Counter[str],
        certainties: Counter[str],
        progress: Callable[[RecognitionSummary], None] | None,
    ) -> None:
        for index, item in enumerate(files, start=1):
            if ctl.paused or ctl.cancelled:
                self._commit_batch()  # ne jamais garder la base verrouillée pendant une pause
            ctl.checkpoint()
            if index % BATCH == 0:
                self._commit_batch()
            self._begin_batch()
            if item.hash_state != "validated" or item.content_id is None:
                summary.waiting_for_hash += 1
                continue
            warnings: list[str] = []
            source: MqlSource | None = None
            misleading = (
                bool(item.magic)
                and item.magic != "empty"
                and item.ext in EXPECTED
                and item.magic not in EXPECTED[item.ext]
            )
            if item.ext in SOURCE_EXTS and not misleading:
                try:
                    source = self._source_meta(item, warnings)
                    summary.sources_parsed += source is not None
                except Exception as exc:  # un fichier malformé ne bloque jamais le traitement
                    warnings.append(f"analyse impossible : {exc}")
                    log.warning("Analyse impossible du fichier %s : %s", item.id, exc)
            paired = self._paired_type(item) if item.ext in ("ex4", "ex5") else None
            result = classify(
                ext=item.ext,
                rel_path=item.rel_path,
                signature=item.magic,
                misleading=misleading,
                source=source,
                paired_source_type=paired,
            )
            self._save(item, result, warnings)
            summary.classified += 1
            summary.warnings += len(warnings)
            types[result.detected_type] += 1
            certainties[result.certainty] += 1
            if progress is not None and index % BATCH == 0:
                progress(summary)

    # ------------------------------------------------------------------------------------
    def _read(self, item: _File) -> bytes:
        path = os.path.join(os.fsencode(item.root), item.rel_path_bytes)  # noqa: PTH118
        chunks: list[bytes] = []
        total = 0
        with ReadOnlyFile(path) as handle:
            for chunk in handle.chunks():
                total += len(chunk)
                if total > MAX_SOURCE_BYTES:
                    raise ValueError("source trop volumineuse (> 8 Mio) : non analysée")
                chunks.append(chunk)
        return b"".join(chunks)

    def _source_meta(self, item: _File, warnings: list[str]) -> MqlSource | None:
        data = self._read(item)
        if item.sha256 is not None and hashlib.sha256(data).digest() != item.sha256:
            warnings.append("contenu différent de l'empreinte : relancez inventaire et empreintes")
            return None
        decoded = decode_text(data)
        if decoded.confidence < 0.5:
            warnings.append(f"encodage incertain ({decoded.encoding})")
        parsed = parse_mql(decoded.text)
        warnings.extend(parsed.warnings)
        existing = self._conn.execute(
            "SELECT engine_version FROM mql_source_meta WHERE content_id = ?", (item.content_id,)
        ).fetchone()
        if existing is None or existing[0] != ENGINE_VERSION:
            no_comments, _ = source_text_parts(decoded.text)
            self._store_meta(
                item.content_id,
                decoded.encoding,
                decoded.confidence,
                parsed,
                sketch(shingle_hashes(tokens(no_comments))),
            )
        return parsed

    def _store_meta(
        self,
        content_id: int | None,
        encoding: str,
        confidence: float,
        parsed: MqlSource,
        minhash: bytes,
    ) -> None:
        props = parsed.properties
        with self._tx():
            for table in (
                "mql_input",
                "mql_include",
                "mql_import",
                "mql_reference",
                "mql_icustom",
            ):
                self._conn.execute(f"DELETE FROM {table} WHERE content_id = ?", (content_id,))
            self._conn.execute(
                "INSERT INTO mql_source_meta(content_id, encoding, encoding_confidence,"
                " line_count, prop_version, prop_copyright, prop_link, prop_description,"
                " prop_strict, normalized_sha256, minhash, warnings_json, engine_version,"
                " program_type, entry_points_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, NULL, ?) ON CONFLICT(content_id) DO UPDATE SET"
                " encoding = excluded.encoding, encoding_confidence = excluded.encoding_confidence,"
                " line_count = excluded.line_count, prop_version = excluded.prop_version,"
                " prop_copyright = excluded.prop_copyright, prop_link = excluded.prop_link,"
                " prop_description = excluded.prop_description,"
                " prop_strict = excluded.prop_strict,"
                " normalized_sha256 = excluded.normalized_sha256, minhash = excluded.minhash,"
                " warnings_json = excluded.warnings_json,"
                " engine_version = excluded.engine_version,"
                " entry_points_json = excluded.entry_points_json",
                (
                    content_id,
                    encoding,
                    confidence,
                    parsed.line_count,
                    props.get("version"),
                    props.get("copyright"),
                    props.get("link"),
                    props.get("description"),
                    int("strict" in parsed.property_flags),
                    parsed.normalized_sha256,
                    minhash,
                    json.dumps(parsed.warnings, ensure_ascii=False),
                    ENGINE_VERSION,
                    json.dumps(parsed.entry_points),
                ),
            )
            self._conn.executemany(
                "INSERT INTO mql_input(content_id, ordinal, name, mql_type, default_raw,"
                " modifier, line) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (content_id, i.ordinal, i.name, i.mql_type, i.default_raw, i.modifier, i.line)
                    for i in parsed.inputs
                ],
            )
            self._conn.executemany(
                "INSERT INTO mql_include(content_id, target, is_system, line) VALUES (?, ?, ?, ?)",
                [(content_id, t, int(system), line) for t, system, line in parsed.includes],
            )
            self._conn.executemany(
                "INSERT INTO mql_import(content_id, module, line) VALUES (?, ?, ?)",
                [(content_id, module, line) for module, line in parsed.imports],
            )
            self._conn.executemany(
                "INSERT INTO mql_reference(content_id, target, target_key, kind, line)"
                " VALUES (?, ?, ?, ?, ?)",
                [
                    (content_id, target, target.casefold(), kind, line)
                    for target, kind, line in parsed.references
                ],
            )
            self._conn.executemany(
                "INSERT INTO mql_icustom(content_id, target, target_key, line) VALUES (?, ?, ?, ?)",
                [(content_id, name, name.casefold(), line) for name, line in parsed.custom_calls],
            )

    def _paired_type(self, item: _File) -> str | None:
        """Type de la source de même nom dans le même dossier (appariement par nom).

        L'index des sources est construit une seule fois (les sources sont classées avant les
        binaires compilés) : coût linéaire, quel que soit le nombre de fichiers.
        """
        if self._pairs is None:
            self._pairs = {}
            for root_id, rel_path, detected in self._conn.execute(
                "SELECT f.root_id, f.rel_path, a.detected_type FROM file_record f"
                " JOIN file_analysis a ON a.file_id = f.id WHERE f.presence = 'present'"
                " AND f.ext IN ('mq4', 'mq5') AND a.detected_type NOT IN ('unknown', 'include')"
            ):
                self._pairs[(int(root_id), str(rel_path).casefold())] = str(detected)
        directory, _, filename = item.rel_path.rpartition("/")
        stem = filename.rsplit(".", 1)[0]
        source_ext = "mq4" if item.ext == "ex4" else "mq5"
        candidate = f"{directory}/{stem}.{source_ext}" if directory else f"{stem}.{source_ext}"
        return self._pairs.get((item.root_id, candidate.casefold()))

    def _save(self, item: _File, result: Classification, warnings: list[str]) -> None:
        now = iso_utc(self._clock.now())
        with self._tx():
            self._conn.execute(
                "INSERT INTO file_analysis(file_id, detected_type, platform, certainty,"
                " basis_json, limits, engine_version, content_id, analyzed_at, warnings_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(file_id) DO UPDATE SET"
                " detected_type = excluded.detected_type, platform = excluded.platform,"
                " certainty = excluded.certainty, basis_json = excluded.basis_json,"
                " limits = excluded.limits, engine_version = excluded.engine_version,"
                " content_id = excluded.content_id, analyzed_at = excluded.analyzed_at,"
                " warnings_json = excluded.warnings_json",
                (
                    item.id,
                    result.detected_type,
                    result.platform,
                    result.certainty,
                    json.dumps(result.basis, ensure_ascii=False),
                    result.limits,
                    ENGINE_VERSION,
                    item.content_id,
                    now,
                    json.dumps(warnings, ensure_ascii=False),
                ),
            )
            if item.ext in SOURCE_EXTS and item.content_id is not None:
                meta = self._conn.execute(
                    "SELECT prop_description, prop_copyright FROM mql_source_meta"
                    " WHERE content_id = ?",
                    (item.content_id,),
                ).fetchone()
                if meta is not None:
                    self._conn.execute(
                        "UPDATE search_fts SET prop_description = ?, prop_copyright = ?"
                        " WHERE rowid = ?",
                        (meta[0], meta[1], item.id),
                    )
                    self._conn.execute(
                        "UPDATE mql_source_meta SET program_type = ? WHERE content_id = ?",
                        (result.detected_type, item.content_id),
                    )
