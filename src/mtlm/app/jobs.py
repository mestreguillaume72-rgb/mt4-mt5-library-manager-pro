"""Tâches persistées (table ``job``) : création, progression, fin, reprise après fermeture."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mtlm import ENGINE_VERSION
from mtlm.core.clock import Clock, iso_utc
from mtlm.store.database import transaction

FINAL_STATES = ("cancelled", "completed", "failed", "interrupted")


@dataclass(frozen=True)
class JobInfo:
    id: int
    kind: str
    state: str
    progress_done: int
    progress_total: int | None
    errors_count: int
    created_at: str
    finished_at: str | None
    params: dict[str, Any]


class JobStore:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def _now(self) -> str:
        return iso_utc(self._clock.now())

    def create(self, kind: str, params: Mapping[str, Any]) -> int:
        now = self._now()
        with transaction(self._conn):
            cursor = self._conn.execute(
                "INSERT INTO job(kind, params_json, state, created_at, started_at, updated_at,"
                " engine_version) VALUES (?, ?, 'running', ?, ?, ?, ?)",
                (kind, json.dumps(dict(params), sort_keys=True), now, now, now, ENGINE_VERSION),
            )
            return int(cursor.lastrowid or 0)

    def progress(
        self, job_id: int, done: int, total: int | None = None, errors: int | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE job SET progress_done = ?, progress_total = coalesce(?, progress_total),"
            " errors_count = coalesce(?, errors_count), updated_at = ? WHERE id = ?",
            (done, total, errors, self._now(), job_id),
        )

    def finish(self, job_id: int, state: str, summary: Mapping[str, Any] | None = None) -> None:
        if state not in FINAL_STATES:
            raise ValueError(f"état final invalide : {state}")
        now = self._now()
        with transaction(self._conn):
            self._conn.execute(
                "UPDATE job SET state = ?, finished_at = ?, updated_at = ? WHERE id = ?",
                (state, now, now, job_id),
            )
            if summary is not None:
                self.set_checkpoint(job_id, "summary", summary)

    def set_checkpoint(self, job_id: int, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO job_checkpoint(job_id, key, value_json, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(job_id, key) DO UPDATE SET value_json = excluded.value_json,"
            " updated_at = excluded.updated_at",
            (job_id, key, json.dumps(value, sort_keys=True, ensure_ascii=False), self._now()),
        )

    def checkpoint(self, job_id: int, key: str) -> Any:
        row = self._conn.execute(
            "SELECT value_json FROM job_checkpoint WHERE job_id = ? AND key = ?", (job_id, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, job_id: int) -> JobInfo:
        row = self._conn.execute(
            "SELECT id, kind, state, progress_done, progress_total, errors_count, created_at,"
            " finished_at, params_json FROM job WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return JobInfo(
            int(row[0]),
            row[1],
            row[2],
            int(row[3]),
            row[4],
            int(row[5]),
            row[6],
            row[7],
            json.loads(row[8]),
        )

    def recent(self, limit: int = 20) -> list[JobInfo]:
        ids = [
            r[0]
            for r in self._conn.execute("SELECT id FROM job ORDER BY id DESC LIMIT ?", (limit,))
        ]
        return [self.get(int(i)) for i in ids]

    def mark_interrupted(self) -> list[int]:
        """Au démarrage : les tâches restées « en cours » (fermeture brutale) sont marquées
        interrompues pour être proposées à la reprise. Retourne leurs identifiants."""
        rows = self._conn.execute(
            "SELECT id FROM job WHERE state IN ('queued', 'running', 'paused', 'cancelling')"
        ).fetchall()
        ids = [int(r[0]) for r in rows]
        if ids:
            now = self._now()
            with transaction(self._conn):
                self._conn.executemany(
                    "UPDATE job SET state = 'interrupted', updated_at = ? WHERE id = ?",
                    [(now, i) for i in ids],
                )
        return ids
