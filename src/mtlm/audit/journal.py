"""Journal d'audit append-only, chaîné par empreinte SHA-256.

Chaque événement contient l'empreinte de l'événement précédent (``prev_hash``) et sa
propre empreinte (``hash``), calculée sur ``prev_hash`` + le contenu de l'événement.
Toute modification ou suppression d'un événement intermédiaire casse la chaîne et
est détectée par :meth:`AuditJournal.verify`. En plus, des triggers SQL refusent
``UPDATE`` et ``DELETE`` sur la table.

Limite connue (documentée) : la suppression du **dernier** événement par un accès
direct à la base, triggers retirés, n'est pas détectable par la chaîne seule.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from mtlm.core.clock import Clock, iso_utc
from mtlm.core.errors import AuditError, ExportError
from mtlm.store.database import transaction

log = logging.getLogger("mtlm.audit")

GENESIS_HASH = bytes(32)

Result = Literal["ok", "refused", "failed", "cancelled"]
ACTOR_USER = "utilisateur"
ACTOR_SYSTEM = "systeme"


def canonical_details(details: Mapping[str, Any] | None) -> str:
    return json.dumps(
        dict(details or {}), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def compute_hash(
    prev_hash: bytes, ts: str, actor: str, action: str, obj: str, result: str, details_json: str
) -> bytes:
    payload = json.dumps(
        [ts, actor, action, obj, result, details_json], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(prev_hash + payload).digest()


@dataclass(frozen=True)
class AuditRecord:
    id: int
    ts: str
    actor: str
    action: str
    object: str
    result: str
    details_json: str
    prev_hash: bytes
    hash: bytes

    def to_json(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "ts": self.ts,
                "actor": self.actor,
                "action": self.action,
                "object": self.object,
                "result": self.result,
                "details": json.loads(self.details_json),
                "prev_hash": self.prev_hash.hex(),
                "hash": self.hash.hex(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass(frozen=True)
class AuditVerification:
    ok: bool
    checked: int
    first_invalid_id: int | None = None
    reason: str | None = None


class AuditJournal:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def append(
        self,
        actor: str,
        action: str,
        obj: str,
        result: Result = "ok",
        details: Mapping[str, Any] | None = None,
    ) -> AuditRecord:
        if not actor or not action:
            raise AuditError("Un événement d'audit exige un acteur et une action")
        details_json = canonical_details(details)
        ts = iso_utc(self._clock.now())
        with transaction(self._conn):
            row = self._conn.execute(
                "SELECT hash FROM audit_event ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev = bytes(row[0]) if row else GENESIS_HASH
            digest = compute_hash(prev, ts, actor, action, obj, result, details_json)
            cursor = self._conn.execute(
                "INSERT INTO audit_event(ts, actor, action, object, result, details_json,"
                " prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ts, actor, action, obj, result, details_json, prev, digest),
            )
            event_id = int(cursor.lastrowid or 0)
        log.info("audit %s %s %s -> %s", actor, action, obj, result)
        return AuditRecord(event_id, ts, actor, action, obj, result, details_json, prev, digest)

    def __iter__(self) -> Iterator[AuditRecord]:
        cursor = self._conn.execute(
            "SELECT id, ts, actor, action, object, result, details_json, prev_hash, hash"
            " FROM audit_event ORDER BY id"
        )
        for row in cursor:
            yield AuditRecord(
                int(row[0]),
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                bytes(row[7]),
                bytes(row[8]),
            )

    def count(self) -> int:
        row = self._conn.execute("SELECT count(*) FROM audit_event").fetchone()
        return int(row[0]) if row else 0

    def verify(self) -> AuditVerification:
        expected_prev = GENESIS_HASH
        checked = 0
        for record in self:
            if record.prev_hash != expected_prev:
                return AuditVerification(
                    False,
                    checked,
                    record.id,
                    "Chaînage rompu : un événement précédent a été supprimé ou modifié",
                )
            recomputed = compute_hash(
                record.prev_hash,
                record.ts,
                record.actor,
                record.action,
                record.object,
                record.result,
                record.details_json,
            )
            if recomputed != record.hash:
                return AuditVerification(
                    False, checked, record.id, "Contenu modifié : empreinte incohérente"
                )
            expected_prev = record.hash
            checked += 1
        return AuditVerification(True, checked)

    def export_jsonl(self, destination: Path) -> int:
        """Exporte tout le journal en JSON Lines. N'écrase jamais un fichier existant."""
        try:
            with destination.open("x", encoding="utf-8", newline="\n") as handle:
                count = 0
                for record in self:
                    handle.write(record.to_json())
                    handle.write("\n")
                    count += 1
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError as exc:
            raise ExportError(
                f"Le fichier existe déjà, il ne sera pas écrasé : {destination}"
            ) from exc
        except OSError as exc:
            if destination.exists():
                destination.unlink()
            raise ExportError(f"Export impossible : {exc}") from exc
        return count
