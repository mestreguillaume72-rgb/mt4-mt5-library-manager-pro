"""Présentation lisible (français) des données du moteur, partagée par la ligne de commande
et l'interface graphique : les deux affichent exactement les mêmes informations."""

from __future__ import annotations

import sqlite3

from mtlm.app.inventory import InventoryService, analysis_of


def human_size(size: int | None) -> str:
    if size is None:
        return "?"
    value = float(size)
    for unit in ("o", "Kio", "Mio", "Gio"):
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
    size = f"{human_size(row.size)} ({row.size} octets)" if row.size is not None else "inconnue"
    signature = (detail.magic_label or "non identifié") + (
        " — EXTENSION TROMPEUSE" if detail.misleading_extension else ""
    )
    lines = [
        f"Chemin : {row.rel_path}",
        f"Source : {detail.source_path}",
        f"Nom : {row.name}",
        f"Extension : {row.ext or '(aucune)'}",
        f"Type d'entrée : {row.file_type}",
        f"Taille : {size}",
        f"Présence : {row.presence}",
        f"iCloud non téléchargé : {'oui (jamais lu)' if detail.is_dataless else 'non'}",
        f"État de l'empreinte : {row.hash_state}",
        f"SHA-256 : {detail.sha256_hex or 'non calculée'}",
        f"Erreur d'empreinte : {detail.hash_error or 'aucune'}",
        f"Format réel (signature) : {signature}",
        f"Moteur : {detail.hashed_with_engine or '—'}",
        f"Autres emplacements au contenu identique : {detail.other_paths_same_content}",
        f"En quarantaine : {'oui' if row.in_quarantine else 'non'}",
    ]
    info = analysis_of(conn, file_id)
    if info is None:
        lines.append("Reconnaissance : non effectuée (lancez l'analyse).")
        return lines
    lines.append(
        f"Type reconnu : {TYPE_LABELS.get(info.detected_type, info.detected_type)} — "
        f"plateforme {info.platform} — certitude {CERTAINTY_LABELS[info.certainty]}"
    )
    lines += [f"  preuve : {reason}" for reason in info.basis]
    if info.limits:
        lines.append(f"  limite : {info.limits}")
    lines += [f"  avertissement : {w}" for w in info.warnings]
    if info.encoding is not None:
        lines += [
            f"Encodage : {info.encoding}",
            f"Version déclarée : {info.prop_version or 'aucune'}",
            f"Copyright déclaré : {info.prop_copyright or 'aucun'}",
        ]
        if info.prop_description:
            lines.append(f"Description : {info.prop_description}")
        lines.append(f"Fonctions d'entrée : {', '.join(info.entry_points) or 'aucune'}")
        lines.append(f"Paramètres ({len(info.inputs)}) :")
        lines += [
            f"  {modifier} {mql_type} {name}" + (f" = {default}" if default else "")
            for name, mql_type, default, modifier in info.inputs
        ]
        if info.includes:
            lines.append(f"Inclusions : {', '.join(info.includes)}")
        if info.imports:
            lines.append(f"Imports (jamais chargés) : {', '.join(info.imports)}")
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
