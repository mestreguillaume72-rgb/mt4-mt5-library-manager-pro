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
from mtlm.core.i18n import tr
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
            "archives.decompresser",
            "Décompresser les archives et mettre l'archive à la Corbeille (0 = non, 1 = oui)",
            0,
            0,
            1,
            True,
            "1 : à l'analyse, chaque archive lue sans problème est décompressée dans un dossier "
            "à son nom, à côté d'elle, puis mise à la Corbeille si tout est vérifié. 0 : les "
            "archives sont seulement lues, sans rien extraire.",
        ),
        SettingSpec(
            "empreintes.tout_lire",
            "Lire en entier tous les fichiers du disque (0 = robots et indicateurs seulement)",
            0,
            0,
            1,
            True,
            "0 (conseillé) : seuls les fichiers MetaTrader (.mq4, .mq5, .ex4, .ex5, .mqh, .set, "
            ".tpl, .dll…), les archives, et les images, sons et documents rangés à côté d'eux "
            "sont lus en entier. Les autres fichiers (vidéos, photos, images disque…) sont "
            "seulement listés : l'analyse d'un disque entier est beaucoup plus rapide. 1 : tout "
            "est lu, ce qui peut prendre des heures sur un grand disque.",
        ),
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
            raise SettingsError(tr("Paramètre inconnu : {key}", key=key))
        row = self._conn.execute("SELECT value_json FROM setting WHERE key = ?", (key,)).fetchone()
        value = float(json.loads(row[0])) if row else spec.default
        return int(value) if spec.integer else value

    def all(self) -> dict[str, float]:
        return {key: self.get(key) for key in SPECS}

    #: Langue de l'interface (texte, hors des réglages numériques).
    LANGUAGE_KEY = "interface.langue"

    def language(self) -> str | None:
        row = self._conn.execute(
            "SELECT value_json FROM setting WHERE key = ?", (self.LANGUAGE_KEY,)
        ).fetchone()
        return str(json.loads(row[0])) if row else None

    def set_language(self, code: str) -> None:
        previous = self.language()
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO setting(key, value_json) VALUES (?, ?) ON CONFLICT(key)"
                " DO UPDATE SET value_json = excluded.value_json",
                (self.LANGUAGE_KEY, json.dumps(code)),
            )
        self._journal.append(
            ACTOR_USER,
            "settings.set",
            self.LANGUAGE_KEY,
            details={"avant": previous, "apres": code},
        )

    def set(self, key: str, value: float) -> float:
        spec = SPECS.get(key)
        if spec is None:
            raise SettingsError(tr("Paramètre inconnu : {key}", key=key))
        if spec.integer and float(value) != int(value):
            raise SettingsError(tr("{label} : un nombre entier est attendu", label=spec.label))
        if not spec.minimum <= value <= spec.maximum:
            raise SettingsError(
                tr(
                    "{label} : valeur entre {minimum:g} et {maximum:g} attendue",
                    label=spec.label,
                    minimum=spec.minimum,
                    maximum=spec.maximum,
                )
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
