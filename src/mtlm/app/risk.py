"""Service « fichiers à risque » (1.5.0) — analyse **locale**, ce n'est pas un antivirus.

Les fichiers sont seulement lus (jamais exécutés) et rien n'est envoyé sur Internet. Voir
:mod:`mtlm.metatrader.risk` pour les règles et leurs limites.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field

from mtlm.core.control import TaskControl
from mtlm.formats.signatures import EXPECTED
from mtlm.fs.reader import ReadOnlyFile
from mtlm.metatrader.encoding import decode_text
from mtlm.metatrader.risk import (
    EXECUTABLE_EXTS,
    Finding,
    level_rank,
    scan_binary,
    scan_source,
)

MAX_READ = 32 * 1024 * 1024
LEVEL_LABELS = {"élevé": "Risque élevé", "à surveiller": "À surveiller", "info": "Information"}


@dataclass
class RiskRow:
    file_id: int
    rel_path: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def level(self) -> str:
        return min((f.level for f in self.findings), key=level_rank, default="info")

    @property
    def reasons(self) -> str:
        ordered = sorted(self.findings, key=lambda f: level_rank(f.level))
        return " ; ".join(dict.fromkeys(f.reason for f in ordered))


def _read(path: bytes) -> bytes | None:
    chunks, total = [], 0
    try:
        with ReadOnlyFile(path) as handle:
            for chunk in handle.chunks():
                total += len(chunk)
                if total > MAX_READ:
                    break
                chunks.append(chunk)
    except OSError:
        return None
    return b"".join(chunks)


class RiskService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def scan(self, *, control: TaskControl | None = None) -> list[RiskRow]:
        ctl = control or TaskControl()
        rows: dict[int, RiskRow] = {}

        def add(file_id: int, rel_path: str, finding: Finding) -> None:
            rows.setdefault(file_id, RiskRow(file_id, rel_path)).findings.append(finding)

        executables = tuple(EXECUTABLE_EXTS)
        candidates = self._conn.execute(
            "SELECT f.id, f.rel_path, f.ext, f.magic, s.path, f.rel_path_bytes FROM file_record f"
            " JOIN source_root s ON s.id = f.root_id WHERE f.presence = 'present'"
            " AND f.file_type = 'file' AND s.status = 'ok' AND (f.ext IN"
            f" ('mq4', 'mq5', 'mqh', 'ex4', 'ex5', 'dll', {','.join('?' * len(executables))})"
            " OR f.magic IN ('pe', 'elf', 'macho'))",
            executables,
        ).fetchall()
        for index, (file_id, rel_path, ext, magic, root, rel_bytes) in enumerate(candidates):
            if index % 200 == 0:
                ctl.checkpoint()
            file_id, ext = int(file_id), str(ext or "")
            path = os.path.join(os.fsencode(root), bytes(rel_bytes))  # noqa: PTH118
            if ext in EXECUTABLE_EXTS:
                add(
                    file_id, rel_path, Finding("élevé", f"{EXECUTABLE_EXTS[ext]} : peut s'exécuter")
                )
            if (
                magic in ("pe", "elf", "macho")
                and ext not in ("dll", "exe", "com", "scr")
                and ext in EXPECTED
                and magic not in EXPECTED[ext]
            ):
                add(
                    file_id,
                    rel_path,
                    Finding("élevé", f"programme déguisé : extension .{ext}, contenu {magic}"),
                )
            if ext == "dll":
                add(
                    file_id,
                    rel_path,
                    Finding("à surveiller", "DLL : bibliothèque Windows qui peut tout faire"),
                )
            if ext in ("mq4", "mq5", "mqh"):
                data = _read(path)
                if data is not None:
                    for finding in scan_source(decode_text(data).text):
                        add(file_id, rel_path, finding)
            elif ext in ("ex4", "ex5", "dll") or magic == "pe":
                data = _read(path)
                if data is not None:
                    for finding in scan_binary(data):
                        add(file_id, rel_path, finding)
        # Extensions trompeuses (autres que les programmes déjà signalés).
        for file_id, rel_path, ext, magic in self._conn.execute(
            "SELECT id, rel_path, ext, magic FROM file_record WHERE presence = 'present'"
            " AND magic IS NOT NULL AND magic NOT IN ('empty', 'pe', 'elf', 'macho')"
        ):
            if ext in EXPECTED and magic not in EXPECTED[ext]:
                add(
                    int(file_id),
                    rel_path,
                    Finding("à surveiller", f"extension trompeuse : .{ext}, contenu {magic}"),
                )
        # Archives : protégées par mot de passe, ou contenant des programmes.
        for file_id, rel_path, status in self._conn.execute(
            "SELECT f.id, f.rel_path, a.status FROM archive_scan a JOIN file_record f"
            " ON f.id = a.file_id WHERE f.presence = 'present'"
        ):
            if status == "encrypted":
                add(
                    int(file_id),
                    rel_path,
                    Finding(
                        "à surveiller",
                        "archive protégée par mot de passe : contenu invisible (technique "
                        "courante pour cacher un virus)",
                    ),
                )
        for file_id, rel_path, inner in self._conn.execute(
            "SELECT f.id, f.rel_path, e.inner_path FROM archive_entry e"
            " JOIN file_record f ON f.id = e.archive_file_id WHERE f.presence = 'present'"
            " AND e.is_dir = 0"
        ):
            ext = str(inner).rpartition(".")[2].casefold() if "." in str(inner) else ""
            if ext in EXECUTABLE_EXTS:
                add(
                    int(file_id),
                    rel_path,
                    Finding("élevé", f"contient {EXECUTABLE_EXTS[ext]} : {inner}"),
                )
            elif ext == "dll":
                add(int(file_id), rel_path, Finding("à surveiller", f"contient une DLL : {inner}"))
        result = [r for r in rows.values() if r.findings]
        return sorted(result, key=lambda r: (level_rank(r.level), r.rel_path))
