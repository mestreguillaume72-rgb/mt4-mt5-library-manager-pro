"""« Recommencer l'analyse à zéro » (1.6.0).

Efface **seulement les résultats d'analyse** enregistrés par l'application (empreintes,
formats, archives lues, reconnaissance, SET, associations, familles, doublons, fichiers
liés), puis la prochaine « Tout analyser » repart de rien au lieu de compléter l'analyse
précédente. **Rien n'est touché sur le disque.**

Conservés : les dossiers ajoutés, les paramètres, le journal d'audit, l'historique de
quarantaine, de Corbeille (« Remettre en place » reste possible), des décompressions et des
dossiers créés.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.store.database import transaction

#: Tables de résultats d'analyse, dans l'ordre (les dépendantes d'abord).
ANALYSIS_TABLES = (
    "association_evidence",
    "association",
    "set_parameter",
    "set_file",
    "similarity_pair",
    "duplicate_member",
    "duplicate_group",
    "family_member",
    "file_family",
    "companion_link",
    "tool_dependency",
    "mql_icustom",
    "mql_import",
    "mql_include",
    "mql_input",
    "mql_reference",
    "mql_source_meta",
    "file_analysis",
    "archive_entry",
    "archive_scan",
    "scan_error",
)
#: Tâches d'analyse effacées (celles d'inventaire restent : les fichiers y renvoient).
ANALYSIS_JOBS = ("hash", "archives", "recognize", "sets", "match", "families", "duplicates")
#: Historique qui garde un lien vers un fichier : ces fichiers ne sont jamais oubliés.
_HISTORY = (
    "SELECT file_id FROM quarantine_entry",
    "SELECT file_id FROM deletion_record",
    "SELECT keeper_file_id FROM deletion_record WHERE keeper_file_id IS NOT NULL",
    "SELECT file_id FROM organize_item",
    "SELECT collision_of FROM organize_item WHERE collision_of IS NOT NULL",
    "SELECT archive_file_id FROM archive_extraction",
)


@dataclass
class ResetSummary:
    results_cleared: int = 0
    files_forgotten: int = 0
    files_to_reread: int = 0


class ResetService:
    def __init__(self, conn: sqlite3.Connection, journal: AuditJournal) -> None:
        self._conn = conn
        self._journal = journal

    def reset(self) -> ResetSummary:
        summary = ResetSummary()
        with transaction(self._conn):
            for table in ANALYSIS_TABLES:
                summary.results_cleared += self._conn.execute(f"DELETE FROM {table}").rowcount
            self._conn.execute(
                f"DELETE FROM job WHERE kind IN ({','.join('?' * len(ANALYSIS_JOBS))})"
                " AND state <> 'running'",
                ANALYSIS_JOBS,
            )
            keep = " UNION ".join(_HISTORY)
            # Fichiers disparus et sans historique : oubliés (l'inventaire les retrouvera
            # s'ils reviennent) ; plus d'analyse « par-dessus » d'anciens résultats.
            summary.files_forgotten = self._conn.execute(
                f"DELETE FROM file_record WHERE presence <> 'present' AND id NOT IN ({keep})"
            ).rowcount
            summary.files_to_reread = self._conn.execute(
                "UPDATE file_record SET hash_state = 'not_computed', content_id = NULL,"
                " hash_error = NULL, magic = NULL WHERE presence = 'present'"
            ).rowcount
        self._journal.append(
            ACTOR_USER,
            "analysis.reset",
            "résultats d'analyse effacés",
            details={
                "resultats": summary.results_cleared,
                "fichiers_oublies": summary.files_forgotten,
                "fichiers_a_relire": summary.files_to_reread,
            },
        )
        return summary
