"""Noms de fichiers et de dossiers **valables partout** (Mac, Windows) pour ce que
l'application crée : dossiers proposés, quarantaine, décompression.

Windows refuse les caractères ``< > : " / \\ | ? *`` et de contrôle, les noms réservés
(``CON``, ``PRN``, ``AUX``, ``NUL``, ``COM1``…, ``LPT1``…) et un point ou une espace à la fin.
"""

from __future__ import annotations

FORBIDDEN = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}
MAX_COMPONENT = 120


def portable_name(text: str, fallback: str = "_") -> str:
    """Un composant de chemin sûr : caractères interdits remplacés par « _ », pas de point ni
    d'espace final, pas de nom réservé de Windows, 120 caractères au plus."""
    cleaned = "".join("_" if c in FORBIDDEN else c for c in text).strip().strip(".").strip()
    cleaned = cleaned[:MAX_COMPONENT].rstrip(" .")
    if not cleaned:
        return fallback
    if cleaned.split(".", 1)[0].upper() in RESERVED:
        cleaned = "_" + cleaned
    return cleaned
