"""Type des fichiers **contenus dans une archive** (1.6.0) : robot, indicateur, script…

Lecture en mémoire seulement (rien n'est extrait). Une source MQ4/MQ5 est analysée comme sur
le disque ; un compilé EX4/EX5 prend le type de la source de même nom dans le même dossier
de l'archive, sinon celui de son dossier (« Experts », « Indicators »…).
"""

from __future__ import annotations

from mtlm.metatrader.classify import classify, folder_hints
from mtlm.metatrader.encoding import decode_text
from mtlm.metatrader.mql import parse_mql

SOURCE_EXTS = ("mq4", "mq5")
TOOL_TYPES = ("ea", "indicator", "script", "library", "service")


def _ext(name: str) -> str:
    base = name.rpartition("/")[2]
    return base.rpartition(".")[2].casefold() if "." in base else ""


def classify_source(name: str, data: bytes) -> tuple[str | None, str | None]:
    """(type, raison) d'une source MQ4/MQ5 lue dans une archive."""
    ext = _ext(name)
    result = classify(
        ext=ext,
        rel_path=name.replace("\\", "/"),
        signature=None,
        misleading=False,
        source=parse_mql(decode_text(data).text),
    )
    if result.detected_type not in TOOL_TYPES:
        return None, "; ".join(result.basis) or None
    return result.detected_type, "; ".join(result.basis)


def classify_compiled(names_types: dict[str, str | None]) -> dict[str, tuple[str, str]]:
    """Compilés EX4/EX5 : type de la source appariée (même nom, même dossier), sinon dossier.

    ``names_types`` : chemin dans l'archive → type déjà reconnu (sources) ou ``None``."""
    by_stem: dict[str, str] = {}
    for name, kind in names_types.items():
        if kind and _ext(name) in SOURCE_EXTS:
            by_stem[name.rpartition(".")[0].casefold()] = kind
    found: dict[str, tuple[str, str]] = {}
    for name in names_types:
        if _ext(name) not in ("ex4", "ex5"):
            continue
        paired = by_stem.get(name.rpartition(".")[0].casefold())
        if paired:
            found[name] = (paired, "source de même nom dans l'archive")
            continue
        folder_type, _platform = folder_hints(name.replace("\\", "/"))
        if folder_type in TOOL_TYPES:
            found[name] = (folder_type, f"dossier « {folder_type} » dans l'archive")
    return found
