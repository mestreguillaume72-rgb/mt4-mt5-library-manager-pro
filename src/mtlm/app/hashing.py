"""Service de calcul des empreintes (F2, phase 3).

États d'une empreinte : ``not_computed`` → ``in_progress`` → ``validated`` | ``error`` ;
``stale`` si le fichier a changé depuis (relevé par l'inventaire).

* Traitement par lots : chaque lot est marqué ``in_progress`` puis enregistré dans une
  transaction ; après une fermeture brutale, les ``in_progress`` restants sont remis à
  calculer (reprise).
* Calcul parallèle borné (threads ; ``hashlib`` libère le verrou global de Python).
* Ne lit que les fichiers ordinaires présents ; les fichiers iCloud non téléchargés ne
  sont jamais lus (la lecture déclencherait un téléchargement).
* Pause / annulation : vérifiées entre chaque bloc lu ; un fichier interrompu reprend son
  état précédent, aucune empreinte partielle n'est enregistrée.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from mtlm import ENGINE_VERSION
from mtlm.app.jobs import JobStore
from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.clock import Clock
from mtlm.core.control import Cancelled, TaskControl
from mtlm.fs.reader import FileIdentity, NotRegularFileError
from mtlm.hashing.sha256 import HashResult, UnstableFileError, hash_file
from mtlm.store.database import transaction

log = logging.getLogger("mtlm.hashing")

DEFAULT_BATCH = 256


def default_workers() -> int:
    return max(1, min(4, os.cpu_count() or 1))


@dataclass
class HashSummary:
    job_id: int
    state: str
    candidates: int = 0
    hashed: int = 0
    errors: int = 0
    bytes_read: int = 0
    seconds: float = 0.0

    @property
    def mib_per_second(self) -> float:
        return (self.bytes_read / 1048576) / self.seconds if self.seconds > 0 else 0.0


HashProgress = Callable[[HashSummary], None]


@dataclass(frozen=True)
class _Task:
    file_id: int
    path: bytes
    expected: FileIdentity
    previous_state: str


@dataclass(frozen=True)
class _Outcome:
    task: _Task
    result: HashResult | None
    error: str | None
    cancelled: bool = False


class HashService:
    def __init__(self, conn: sqlite3.Connection, clock: Clock, journal: AuditJournal) -> None:
        self._conn = conn
        self._clock = clock
        self._journal = journal
        self._jobs = JobStore(conn, clock)

    def reset_interrupted(self) -> int:
        """Remet à calculer les empreintes laissées « en cours » par une fermeture brutale."""
        with transaction(self._conn):
            cursor = self._conn.execute(
                "UPDATE file_record SET hash_state = 'not_computed'"
                " WHERE hash_state = 'in_progress'"
            )
        return cursor.rowcount

    def _candidates(self, source_id: int | None, retry_errors: bool) -> list[_Task]:
        states = ["not_computed", "stale"] + (["error"] if retry_errors else [])
        sql = (
            "SELECT f.id, s.path, f.rel_path_bytes, f.size, f.mtime_ns, f.inode, f.device,"  # noqa: S608
            " f.hash_state FROM file_record f JOIN source_root s ON s.id = f.root_id"
            " WHERE s.status = 'ok' AND f.presence = 'present' AND f.file_type = 'file'"
            " AND f.is_dataless = 0"
            f" AND f.hash_state IN ({','.join('?' * len(states))})"
        )
        params: list[object] = list(states)
        if source_id is not None:
            sql += " AND f.root_id = ?"
            params.append(source_id)
        rows = self._conn.execute(sql + " ORDER BY f.id", params).fetchall()
        return [
            _Task(
                int(r[0]),
                os.path.join(os.fsencode(r[1]), bytes(r[2])),  # noqa: PTH118 — chemins en octets
                FileIdentity(int(r[3]), int(r[4]), int(r[5]), int(r[6])),
                r[7],
            )
            for r in rows
        ]

    def run(
        self,
        source_id: int | None = None,
        *,
        retry_errors: bool = False,
        workers: int | None = None,
        control: TaskControl | None = None,
        progress: HashProgress | None = None,
        batch_size: int = DEFAULT_BATCH,
    ) -> HashSummary:
        ctl = control or TaskControl()
        self.reset_interrupted()
        tasks = self._candidates(source_id, retry_errors)
        job_id = self._jobs.create("hash", {"source_id": source_id, "retry_errors": retry_errors})
        summary = HashSummary(job_id=job_id, state="running", candidates=len(tasks))
        self._jobs.progress(job_id, 0, total=len(tasks))
        self._journal.append(
            ACTOR_USER,
            "hash.start",
            f"source={source_id or 'toutes'}",
            details={"job": job_id, "fichiers": len(tasks)},
        )
        started = time.perf_counter()
        cancelled = False
        with ThreadPoolExecutor(
            max_workers=workers or default_workers(), thread_name_prefix="hash"
        ) as pool:
            for offset in range(0, len(tasks), batch_size):
                if ctl.cancelled:
                    cancelled = True
                    break
                batch = tasks[offset : offset + batch_size]
                self._mark_in_progress(batch)
                outcomes = list(pool.map(lambda t: self._compute(t, ctl), batch))
                self._store(outcomes, summary)
                summary.seconds = time.perf_counter() - started
                self._jobs.progress(job_id, summary.hashed + summary.errors, errors=summary.errors)
                if progress is not None:
                    progress(summary)
                if any(o.cancelled for o in outcomes):
                    cancelled = True
                    break
        summary.seconds = time.perf_counter() - started
        summary.state = "cancelled" if cancelled else "completed"
        self._jobs.finish(job_id, summary.state, asdict(summary))
        self._journal.append(
            ACTOR_USER,
            "hash.end",
            f"source={source_id or 'toutes'}",
            result="cancelled" if cancelled else "ok",
            details=asdict(summary),
        )
        log.info("Empreintes %d : %s (%.1f Mio/s)", job_id, asdict(summary), summary.mib_per_second)
        return summary

    # ------------------------------------------------------------------------------------
    def _compute(self, task: _Task, ctl: TaskControl) -> _Outcome:
        def on_chunk(_n: int) -> None:
            ctl.checkpoint()

        try:
            ctl.checkpoint()
            result = hash_file(task.path, expected=task.expected, on_chunk=on_chunk)
        except Cancelled:
            return _Outcome(task, None, None, cancelled=True)
        except UnstableFileError as exc:
            return _Outcome(task, None, str(exc))
        except NotRegularFileError:
            return _Outcome(task, None, "pas un fichier ordinaire : non lu")
        except OSError as exc:
            return _Outcome(task, None, f"lecture impossible : {exc.strerror or exc}")
        return _Outcome(task, result, None)

    def _mark_in_progress(self, batch: list[_Task]) -> None:
        with transaction(self._conn):
            self._conn.executemany(
                "UPDATE file_record SET hash_state = 'in_progress' WHERE id = ?",
                [(t.file_id,) for t in batch],
            )

    def _store(self, outcomes: list[_Outcome], summary: HashSummary) -> None:
        with transaction(self._conn):
            for outcome in outcomes:
                task = outcome.task
                if outcome.cancelled:
                    self._conn.execute(
                        "UPDATE file_record SET hash_state = ? WHERE id = ?",
                        (task.previous_state, task.file_id),
                    )
                elif outcome.result is not None:
                    content_id = self._content_id(outcome.result)
                    self._conn.execute(
                        "UPDATE file_record SET hash_state = 'validated', content_id = ?,"
                        " hash_error = NULL, hashed_with_engine = ? WHERE id = ?",
                        (content_id, ENGINE_VERSION, task.file_id),
                    )
                    summary.hashed += 1
                    summary.bytes_read += outcome.result.size
                else:
                    self._conn.execute(
                        "UPDATE file_record SET hash_state = 'error', content_id = NULL,"
                        " hash_error = ?, hashed_with_engine = ? WHERE id = ?",
                        (outcome.error, ENGINE_VERSION, task.file_id),
                    )
                    summary.errors += 1

    def _content_id(self, result: HashResult) -> int:
        self._conn.execute(
            "INSERT OR IGNORE INTO content(sha256, size) VALUES (?, ?)",
            (result.sha256, result.size),
        )
        row = self._conn.execute(
            "SELECT id, size FROM content WHERE sha256 = ?", (result.sha256,)
        ).fetchone()
        if int(row[1]) != result.size:  # impossible sauf collision SHA-256 : on s'arrête
            raise RuntimeError("Incohérence : même SHA-256 pour deux tailles différentes")
        return int(row[0])
