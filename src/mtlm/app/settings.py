"""Paramètres persistants de l'application (écran « Paramètres », F11).

Chaque paramètre a une valeur par défaut documentée, des bornes, et il est **réellement
utilisé** par les traitements (voir :meth:`SettingsService.archive_limits`, etc.).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.errors import MtlmError
from mtlm.formats.archives import ArchiveLimits
from mtlm.store.database import transaction


class SettingsError(MtlmError):
    """Valeur de paramètre invalide."""


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    integer: bool
    help: str


SPECS: dict[str, SettingSpec] = {
    s.key: s
    for s in (
        SettingSpec(
            "similarite.seuil",
            "Seuil de similarité des sources",
            0.80,
            0.5,
            1.0,
            False,
            "Au-dessus de ce score, deux sources sont signalées « similaires » (jamais doublons).",
        ),
        SettingSpec(
            "empreintes.travailleurs",
            "Calculs d'empreintes en parallèle",
            4,
            1,
            16,
            True,
            "Réduire à 1 ou 2 pour un disque réseau ou un disque dur lent.",
        ),
        SettingSpec(
            "archives.profondeur",
            "Profondeur maximale des archives imbriquées",
            2,
            1,
            5,
            True,
            "Au-delà, une archive contenue dans une archive n'est pas ouverte.",
        ),
        SettingSpec(
            "archives.ratio",
            "Ratio de compression maximal",
            100,
            10,
            1000,
            True,
            "Protège contre les archives piégées (« zip bombs »).",
        ),
        SettingSpec(
            "archives.entrees",
            "Nombre maximal d'entrées par archive",
            10_000,
            100,
            1_000_000,
            True,
            "Au-delà, les entrées suivantes ne sont pas lues.",
        ),
        SettingSpec(
            "archives.taille_mio",
            "Taille décompressée maximale par archive (Mio)",
            2048,
            16,
            65536,
            True,
            "Total des octets décompressés en mémoire.",
        ),
    )
}


class SettingsService:
    def __init__(self, conn: sqlite3.Connection, journal: AuditJournal) -> None:
        self._conn = conn
        self._journal = journal

    def get(self, key: str) -> float:
        spec = SPECS.get(key)
        if spec is None:
            raise SettingsError(f"Paramètre inconnu : {key}")
        row = self._conn.execute("SELECT value_json FROM setting WHERE key = ?", (key,)).fetchone()
        value = float(json.loads(row[0])) if row else spec.default
        return int(value) if spec.integer else value

    def all(self) -> dict[str, float]:
        return {key: self.get(key) for key in SPECS}

    def set(self, key: str, value: float) -> float:
        spec = SPECS.get(key)
        if spec is None:
            raise SettingsError(f"Paramètre inconnu : {key}")
        if spec.integer and float(value) != int(value):
            raise SettingsError(f"{spec.label} : un nombre entier est attendu")
        if not spec.minimum <= value <= spec.maximum:
            raise SettingsError(
                f"{spec.label} : valeur entre {spec.minimum:g} et {spec.maximum:g} attendue"
            )
        stored = int(value) if spec.integer else float(value)
        previous = self.get(key)
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO setting(key, value_json) VALUES (?, ?) ON CONFLICT(key)"
                " DO UPDATE SET value_json = excluded.value_json",
                (key, json.dumps(stored)),
            )
        self._journal.append(
            ACTOR_USER, "settings.set", key, details={"avant": previous, "apres": stored}
        )
        return stored

    def reset(self, key: str) -> float:
        return self.set(key, SPECS[key].default)

    def archive_limits(self) -> ArchiveLimits:
        return ArchiveLimits(
            max_depth=int(self.get("archives.profondeur")),
            max_entries=int(self.get("archives.entrees")),
            max_total_bytes=int(self.get("archives.taille_mio")) * 1024 * 1024,
            max_ratio=float(self.get("archives.ratio")),
        )
