"""Classement des fichiers MetaTrader avec **niveau de certitude** et **limites** (F4).

Chaque décision liste sa base (règles appliquées) : rien n'est présenté comme certain s'il
est seulement déduit d'un nom ou d'un dossier.

Certitudes : ``certain`` (contenu lisible et cohérent), ``probable`` (déduit d'indices
concordants, ex. dossier ou source appariée), ``possible`` (indice isolé ou contradictoire),
``unknown``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtlm.metatrader.mql import MqlSource

FOLDER_TYPES = {
    "experts": "ea",
    "indicators": "indicator",
    "scripts": "script",
    "libraries": "library",
    "include": "include",
    "services": "service",
}
RESOURCE_EXTS = {
    "csv",
    "ini",
    "txt",
    "htm",
    "html",
    "bmp",
    "ico",
    "wav",
    "png",
    "jpg",
    "jpeg",
    "gif",
    "chr",
    "hst",
    "hcc",
    "dat",
    "log",
    "pdf",
    "json",
    "xml",
    "md",
    "mqproj",
    "fxt",
    "sqlite",
}
COMPILED_LIMIT = (
    "binaire compilé opaque : contenu non analysé (ni décompilation ni extraction de "
    "paramètres) ; type déduit d'indices externes uniquement"
)


@dataclass
class Classification:
    detected_type: str = "unknown"
    platform: str = "unknown"
    certainty: str = "unknown"
    basis: list[str] = field(default_factory=list)
    limits: str | None = None


def folder_hints(rel_path: str) -> tuple[str | None, str | None]:
    """(type suggéré par le dossier, plateforme suggérée par le dossier)."""
    parts = [p.lower() for p in rel_path.replace("\\", "/").split("/")[:-1]]
    folder_type = next((FOLDER_TYPES[p] for p in reversed(parts) if p in FOLDER_TYPES), None)
    platform = "mt4" if "mql4" in parts else "mt5" if "mql5" in parts else None
    return folder_type, platform


def source_program_type(
    source: MqlSource, ext: str, folder_type: str | None
) -> tuple[str | None, list[str]]:
    """Type de programme d'après le contenu d'une source ; (None, raisons) si indéterminé."""
    entries = set(source.entry_points)
    if ext == "mqh":
        return "include", ["extension .mqh : fichier d'inclusion"]
    if "service" in source.property_flags:
        return "service", ["#property service"]
    if "library" in source.property_flags:
        return "library", ["#property library"]
    if "OnCalculate" in entries or source.is_indicator:
        reasons = []
        if "OnCalculate" in entries:
            reasons.append("fonction OnCalculate()")
        if source.is_indicator:
            reasons.append("#property indicator_*")
        return "indicator", reasons
    if "OnTick" in entries:
        return "ea", ["fonction OnTick()"]
    if "OnStart" in entries:
        return "script", ["fonction OnStart()"]
    if "start" in entries:
        # MQL4 historique : start() sert aux EA, scripts et indicateurs. Le dossier tranche.
        if folder_type in ("ea", "script", "indicator"):
            return folder_type, ["fonction start() (MQL4 ancien)", f"dossier « {folder_type} »"]
        return None, ["fonction start() (MQL4 ancien) sans dossier explicite"]
    return None, ["aucune fonction d'entrée reconnue"]


def classify(
    *,
    ext: str,
    rel_path: str,
    signature: str | None,
    misleading: bool,
    source: MqlSource | None = None,
    paired_source_type: str | None = None,
) -> Classification:
    folder_type, folder_platform = folder_hints(rel_path)
    result = Classification()
    if misleading:
        result.basis.append(f"EXTENSION TROMPEUSE : le contenu réel est « {signature} »")

    if ext in ("mq4", "mq5", "mqh"):
        result.platform = {"mq4": "mt4", "mq5": "mt5"}.get(ext, folder_platform or "unknown")
        result.basis.append(f"extension .{ext}")
        if misleading or source is None:
            result.detected_type = "unknown"
            result.certainty = "possible" if not misleading else "unknown"
            result.limits = "contenu non lisible comme source MQL"
            return result
        program_type, reasons = source_program_type(source, ext, folder_type)
        result.basis += reasons
        if program_type is None:
            result.detected_type = folder_type or "unknown"
            result.certainty = "possible" if folder_type else "unknown"
            if folder_type:
                result.basis.append(f"dossier « {folder_type} »")
            result.limits = "aucun indice de type dans le contenu"
        elif ext != "mqh" and folder_type and folder_type not in (program_type, "include"):
            result.detected_type = program_type
            result.certainty = "probable"
            result.basis.append(f"contradiction : rangé dans un dossier « {folder_type} »")
        else:
            result.detected_type = program_type
            result.certainty = "certain"
        return result

    if ext in ("ex4", "ex5"):
        result.platform = "mt4" if ext == "ex4" else "mt5"
        result.basis.append(f"extension .{ext} (binaire compilé MetaTrader)")
        result.limits = COMPILED_LIMIT
        if misleading:
            result.certainty = "possible"
            return result
        if paired_source_type:
            result.detected_type = paired_source_type
            result.certainty = "probable"
            result.basis.append(
                f"source de même nom dans le même dossier (type « {paired_source_type} ») — "
                "appariement par nom, non vérifié"
            )
        elif folder_type:
            result.detected_type = folder_type
            result.certainty = "probable"
            result.basis.append(f"dossier « {folder_type} »")
        else:
            result.certainty = "unknown"
            result.basis.append("aucun dossier ni source appariée : type inconnu")
        return result

    if ext == "set":
        result.detected_type = "set"
        result.platform = folder_platform or "unknown"
        result.certainty = "possible" if misleading else "certain"
        result.basis.append("extension .set (jeu de paramètres)")
        if folder_platform:
            result.basis.append(f"dossier {folder_platform.upper()}")
        return result

    if ext == "dll" or signature == "pe":
        result.detected_type = "dll"
        result.platform = folder_platform or "unknown"
        result.certainty = "certain" if signature == "pe" else "possible"
        result.basis.append(
            "bibliothèque Windows (signature PE)"
            if signature == "pe"
            else "extension .dll sans signature PE"
        )
        result.limits = "bibliothèque native : jamais chargée ni exécutée"
        return result

    if ext == "tpl":
        result.detected_type = "template"
        result.certainty = "certain" if not misleading else "possible"
        result.basis.append("extension .tpl (modèle de graphique)")
        return result

    if ext in RESOURCE_EXTS or signature in ("png", "jpeg", "gif", "bmp", "ico", "pdf", "riff"):
        result.detected_type = "resource"
        result.platform = folder_platform or "unknown"
        result.certainty = "probable"
        result.basis.append(f"fichier annexe (.{ext or '?'}, {signature or 'signature inconnue'})")
        return result

    result.basis.append(f"extension inconnue (.{ext})" if ext else "aucune extension")
    if signature:
        result.basis.append(f"signature : {signature}")
    result.limits = "format non reconnu : conservé et inventorié (périmètre ALL)"
    return result
