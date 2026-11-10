"""Exports et rapports (F10) : toutes les valeurs viennent de la base, jamais de valeurs
fictives. Formats CSV (Excel, « ; ») et JSON (schéma documenté dans
docs/utilisateur/exports.md)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mtlm.audit.journal import ACTOR_USER, AuditJournal
from mtlm.core.errors import ExportError
from mtlm.core.paths import AppPaths
from mtlm.transfer.exports import write_csv, write_json
from mtlm.transfer.guards import check_destination


@dataclass(frozen=True)
class ExportKind:
    key: str
    label: str
    header: tuple[str, ...]
    sql: str


KINDS: dict[str, ExportKind] = {
    k.key: k
    for k in (
        ExportKind(
            "inventaire",
            "Inventaire complet",
            (
                "id",
                "source",
                "chemin",
                "nom",
                "extension",
                "taille",
                "date_modification_ns",
                "presence",
                "etat_empreinte",
                "sha256",
                "format_reel",
                "type",
                "plateforme",
                "certitude",
                "en_quarantaine",
            ),
            "SELECT f.id, s.path, f.rel_path, f.name, f.ext, f.size, f.mtime_ns, f.presence,"
            " f.hash_state, lower(hex(c.sha256)), f.magic, a.detected_type, a.platform,"
            " a.certainty, f.in_quarantine FROM file_record f JOIN source_root s"
            " ON s.id = f.root_id LEFT JOIN content c ON c.id = f.content_id"
            " LEFT JOIN file_analysis a ON a.file_id = f.id ORDER BY f.id",
        ),
        ExportKind(
            "associations",
            "Associations robot ↔ SET",
            ("id", "robot", "set", "score", "niveau", "decision", "preuves"),
            "SELECT a.id, r.rel_path, s.rel_path, a.score, a.level, a.user_decision,"
            " (SELECT group_concat(e.polarity || ' ' || e.kind || '=' || round(e.value, 2),"
            " ' | ') FROM association_evidence e WHERE e.association_id = a.id)"
            " FROM association a JOIN file_record r ON r.id = a.robot_file_id"
            " JOIN file_record s ON s.id = a.set_file_id ORDER BY a.score DESC, a.id",
        ),
        ExportKind(
            "doublons",
            "Doublons exacts",
            (
                "groupe",
                "sha256",
                "taille",
                "fichier",
                "chemin",
                "reference",
                "admissible_quarantaine",
                "motif",
            ),
            "SELECT g.id, lower(hex(g.sha256)), g.size, m.file_id, f.rel_path, m.is_reference,"
            " m.admissible_for_quarantine, m.inadmissible_reason FROM duplicate_group g"
            " JOIN duplicate_member m ON m.group_id = g.id JOIN file_record f ON f.id = m.file_id"
            " ORDER BY g.id, m.is_reference DESC, f.rel_path",
        ),
        ExportKind(
            "similaires",
            "Fichiers similaires (non doublons)",
            ("fichier_a", "chemin_a", "fichier_b", "chemin_b", "type", "score", "methode"),
            "SELECT p.file_a, fa.rel_path, p.file_b, fb.rel_path, p.kind, p.score, p.method"
            " FROM similarity_pair p JOIN file_record fa ON fa.id = p.file_a"
            " JOIN file_record fb ON fb.id = p.file_b ORDER BY p.score DESC",
        ),
        ExportKind(
            "familles",
            "Familles et versions",
            (
                "famille",
                "nom",
                "plateforme",
                "confiance",
                "fichier",
                "chemin",
                "relation",
                "version_estimee",
                "base_version",
            ),
            "SELECT ff.id, ff.display_name, ff.platform, ff.confidence, fm.file_id, f.rel_path,"
            " fm.relation, fm.estimated_version, fm.version_basis FROM file_family ff"
            " JOIN family_member fm ON fm.family_id = ff.id JOIN file_record f"
            " ON f.id = fm.file_id ORDER BY ff.id, f.rel_path",
        ),
        ExportKind(
            "erreurs",
            "Erreurs d'inventaire et d'empreinte",
            ("type", "tache_ou_fichier", "chemin", "message"),
            "SELECT 'inventaire', job_id, cast(rel_path_bytes AS TEXT), message FROM scan_error"
            " UNION ALL SELECT 'empreinte', id, rel_path, hash_error FROM file_record"
            " WHERE hash_state = 'error' UNION ALL SELECT 'archive', file_id, '', reason"
            " FROM archive_scan WHERE status NOT IN ('ok')",
        ),
        ExportKind(
            "parametres-set",
            "Paramètres des SET",
            (
                "fichier",
                "chemin",
                "format",
                "parametre",
                "valeur_brute",
                "valeur_normalisee",
                "type_estime",
                "optimisation",
            ),
            "SELECT sp.file_id, f.rel_path, sf.format, sp.name, sp.raw_value,"
            " sp.normalized_value, sp.estimated_type, sp.opt_enabled FROM set_parameter sp"
            " JOIN set_file sf ON sf.file_id = sp.file_id JOIN file_record f"
            " ON f.id = sp.file_id ORDER BY sp.file_id, sp.ordinal",
        ),
    )
}


class ReportService:
    def __init__(self, conn: sqlite3.Connection, journal: AuditJournal, paths: AppPaths) -> None:
        self._conn = conn
        self._journal = journal
        self._paths = paths

    def rows(self, kind: str) -> Iterator[tuple[Any, ...]]:
        spec = KINDS.get(kind)
        if spec is None:
            raise ExportError(f"Export inconnu : {kind}")
        yield from self._conn.execute(spec.sql)

    def export(self, kind: str, destination: Path) -> int:
        spec = KINDS.get(kind)
        if spec is None:
            raise ExportError(f"Export inconnu : {kind} (choix : {', '.join(KINDS)})")
        sources = [
            Path(r[0])
            for r in self._conn.execute("SELECT path FROM source_root WHERE status <> 'removed'")
        ]
        check_destination(destination.parent, sources, [], require_existing=True)
        suffix = destination.suffix.lower()
        if suffix == ".json":
            items = [dict(zip(spec.header, row, strict=True)) for row in self.rows(kind)]
            write_json(
                destination,
                {"export": spec.key, "titre": spec.label, "nombre": len(items), "elements": items},
            )
            count = len(items)
        elif suffix == ".csv":
            count = write_csv(destination, spec.header, self.rows(kind))
        else:
            raise ExportError("Format d'export non pris en charge : utilisez .csv ou .json")
        self._journal.append(
            ACTOR_USER, "report.export", str(destination), details={"export": kind, "lignes": count}
        )
        return count
