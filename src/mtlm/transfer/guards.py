"""Contrôles de destination (spécification § 6 : quarantaine et bibliothèque organisée sur des
destinations distinctes des sources)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

from mtlm.core.errors import MtlmError
from mtlm.fs.paths import is_within


class DestinationError(MtlmError):
    """Destination refusée."""


def check_destination(
    destination: Path,
    source_roots: Iterable[Path],
    app_dirs: Iterable[Path],
    *,
    require_existing: bool = False,
) -> Path:
    """Valide une destination ; retourne son chemin résolu. Refuse : destination dans une
    source, source dans la destination, dossiers de l'application, emplacement non accessible
    en écriture."""
    target = Path(os.path.realpath(destination.expanduser()))
    if require_existing and not target.is_dir():
        # Un disque externe débranché laisse son point de montage parent (/Volumes) : sans ce
        # contrôle, l'arborescence serait recréée sur le disque interne.
        raise DestinationError(
            f"Destination indisponible : {destination} n'existe pas (disque débranché ?)"
        )
    existing = target
    while not existing.exists():
        if existing.parent == existing:
            raise DestinationError(f"Destination inaccessible : {destination}")
        existing = existing.parent
    if not existing.is_dir():
        raise DestinationError(f"La destination n'est pas un dossier : {existing}")

    def conflicts(protected: Path) -> bool:
        # La destination (ou son premier dossier existant) est dans la zone protégée…
        if is_within(existing, protected):
            return True
        # … ou elle existe déjà et contient la zone protégée.
        return target.exists() and is_within(protected, target)

    for root in source_roots:
        if conflicts(root):
            raise DestinationError(
                f"Destination refusée : {target} chevauche la source {root}. La quarantaine et "
                "la bibliothèque organisée doivent être distinctes des sources."
            )
    for app_dir in app_dirs:
        if conflicts(app_dir):
            raise DestinationError(
                f"Destination refusée : {target} chevauche les dossiers de l'application."
            )
    if not os.access(existing, os.W_OK | os.X_OK):
        raise DestinationError(f"Pas de droit d'écriture sur {existing}")
    return target


def free_space(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free


def check_space(path: Path, needed: int, margin: int = 64 * 1024 * 1024) -> None:
    available = free_space(path)
    if available < needed + margin:
        raise DestinationError(
            f"Espace insuffisant : {needed} octets nécessaires (+ marge {margin}), "
            f"{available} disponibles sur la destination."
        )
