"""Comparaisons de chemins robustes (lecture seule).

Sur macOS, un même dossier peut s'écrire avec des casses ou des formes Unicode
différentes. On compare donc les dossiers par identité (périphérique, inode) et non
par texte.
"""

from __future__ import annotations

import os
from pathlib import Path


def identity(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def is_within(child: Path, ancestor: Path) -> bool:
    """Vrai si ``child`` est ``ancestor`` ou se trouve dedans (liens résolus)."""
    target = identity(ancestor)
    if target is None:
        return False
    current = Path(os.path.realpath(child))
    return any(identity(candidate) == target for candidate in (current, *current.parents))


def overlaps(a: Path, b: Path) -> bool:
    return is_within(a, b) or is_within(b, a)
