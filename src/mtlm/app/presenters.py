"""Présentation lisible (français) des données du moteur, partagée par la ligne de commande
et l'interface graphique : les deux affichent exactement les mêmes informations."""

from __future__ import annotations

import sqlite3

from mtlm.app.inventory import InventoryService, analysis_of
from mtlm.core.i18n import tr


def human_size(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("o", tr("Kio"), tr("Mio"), tr("Gio")):
        if value < 1024 or unit == "Gio":
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} o"  # pragma: no cover


TYPE_LABELS = {
    "ea": "robot (EA)",
    "indicator": "indicateur",
    "script": "script",
    "library": "bibliothèque",
    "include": "fichier d'inclusion",
    "service": "service",
    "set": "jeu de paramètres (SET)",
    "dll": "DLL",
    "template": "modèle",
    "resource": "fichier annexe",
    "unknown": "inconnu",
}


CERTAINTY_LABELS = {
    "certain": "certain",
    "probable": "probable",
    "possible": "possible",
    "unknown": "inconnue",
}


RELATION_LABELS = {
    "exact_copy": "copie exacte",
    "renamed_copy": "copie renommée",
    "version_variant": "version",
    "source_of": "source",
    "compiled_variant": "compilé",
    "homonym_different": "homonyme distinct",
    "set_for": "SET associé",
}


def file_detail_lines(conn: sqlite3.Connection, file_id: int) -> list[str] | None:
    """Détail complet d'un fichier (métadonnées, empreinte, reconnaissance, preuves, limites)."""
    detail = InventoryService(conn).detail(file_id)
    if detail is None:
        return None
    row = detail.row
    size = (
        tr("{v} ({size} octets)", v=human_size(row.size), size=row.size)
        if row.size is not None
        else "inconnue"
    )
    signature = (detail.magic_label or tr("non identifié")) + (
        tr(" — EXTENSION TROMPEUSE") if detail.misleading_extension else ""
    )
    lines = [
        tr("Chemin : {rel_path}", rel_path=row.rel_path),
        tr("Source : {source_path}", source_path=detail.source_path),
        tr("Nom : {name}", name=row.name),
        tr("Extension : {v}", v=row.ext or "(aucune)"),
        tr("Type d'entrée : {file_type}", file_type=row.file_type),
        tr("Taille : {size}", size=size),
        tr("Présence : {presence}", presence=row.presence),
        tr("iCloud non téléchargé : {v}", v="oui (jamais lu)" if detail.is_dataless else "non"),
        tr("État de l'empreinte : {hash_state}", hash_state=row.hash_state),
        tr("SHA-256 : {v}", v=detail.sha256_hex or "non calculée"),
        tr("Erreur d'empreinte : {v}", v=detail.hash_error or "aucune"),
        tr("Format réel (signature) : {signature}", signature=signature),
        tr("Moteur : {v}", v=detail.hashed_with_engine or "—"),
        tr(
            "Autres emplacements au contenu identique : {other_paths_same_content}",
            other_paths_same_content=detail.other_paths_same_content,
        ),
        tr("En quarantaine : {v}", v="oui" if row.in_quarantine else "non"),
    ]
    info = analysis_of(conn, file_id)
    if info is None:
        lines.append(tr("Reconnaissance : non effectuée (lancez l'analyse)."))
        return lines
    lines.append(
        tr(
            "Type reconnu : {v} — plateforme {platform} — certitude {v2}",
            v=TYPE_LABELS.get(info.detected_type, info.detected_type),
            platform=info.platform,
            v2=CERTAINTY_LABELS[info.certainty],
        )
    )
    lines += [tr("  preuve : {reason}", reason=reason) for reason in info.basis]
    if info.limits:
        lines.append(tr("  limite : {limits}", limits=info.limits))
    lines += [tr("  avertissement : {w}", w=w) for w in info.warnings]
    if info.encoding is not None:
        lines += [
            tr("Encodage : {encoding}", encoding=info.encoding),
            tr("Version déclarée : {v}", v=info.prop_version or "aucune"),
            tr("Copyright déclaré : {v}", v=info.prop_copyright or "aucun"),
        ]
        if info.prop_description:
            lines.append(
                tr("Description : {prop_description}", prop_description=info.prop_description)
            )
        lines.append(tr("Fonctions d'entrée : {v}", v=", ".join(info.entry_points) or "aucune"))
        lines.append(tr("Paramètres ({v}) :", v=len(info.inputs)))
        lines += [
            f"  {modifier} {mql_type} {name}" + (f" = {default}" if default else "")
            for name, mql_type, default, modifier in info.inputs
        ]
        if info.includes:
            lines.append(tr("Inclusions : {v}", v=", ".join(info.includes)))
        if info.imports:
            lines.append(tr("Imports (jamais chargés) : {v}", v=", ".join(info.imports)))
    return lines


JOB_KIND_LABELS = {
    "scan": "inventaire",
    "hash": "empreintes",
    "archives": "formats et archives",
    "recognize": "reconnaissance",
    "sets": "analyse des SET",
    "match": "associations",
    "families": "familles",
    "duplicates": "doublons",
    "quarantine": "quarantaine",
    "restore": "restauration",
    "organize": "organisation",
    "report": "rapport",
}
JOB_STATE_LABELS = {
    "queued": "en attente",
    "running": "en cours",
    "paused": "en pause",
    "cancelling": "annulation…",
    "cancelled": "annulée",
    "completed": "terminée",
    "failed": "en échec",
    "interrupted": "interrompue",
}
