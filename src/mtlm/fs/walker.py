"""Énumération récursive en lecture seule d'une racine source (F1).

* Itératif (pile explicite) : aucune limite de profondeur de récursion.
* Les liens symboliques sont **enregistrés mais jamais suivis**.
* Protection contre les cycles : chaque dossier est identifié par (périphérique, inode).
* Chemins manipulés en **octets** : aucun nom n'est perdu, même mal encodé.
* Toute erreur (permission refusée, nom trop long, fichier disparu…) est rendue comme
  :class:`WalkError` et n'interrompt jamais l'inventaire.
* Seuls ``os.scandir`` et ``stat`` sont utilisés : aucun fichier n'est ouvert.
"""

from __future__ import annotations

import errno as errno_module
import os
import stat
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Drapeau macOS des fichiers iCloud non téléchargés (sys/stat.h : SF_DATALESS).
SF_DATALESS = 0x40000000


@dataclass(frozen=True)
class WalkEntry:
    rel_path_bytes: bytes
    rel_path: str
    name: str
    ext: str
    file_type: str  # 'file' | 'symlink' | 'other'
    size: int
    mtime_ns: int
    ctime_ns: int
    birthtime_ns: int | None
    inode: int
    device: int
    mode: int
    is_dataless: bool


@dataclass(frozen=True)
class WalkError:
    rel_path_bytes: bytes
    rel_path: str
    errno: int | None
    message: str


@dataclass
class WalkStats:
    directories: int = 0
    entries: int = 0
    errors: int = 0
    cycles_skipped: int = 0


def display_path(raw: bytes) -> str:
    """Chemin lisible : UTF-8 (caractères invalides remplacés), forme Unicode NFC."""
    return unicodedata.normalize("NFC", raw.decode("utf-8", errors="replace"))


def extension_of(name: str) -> str:
    """Extension en minuscules sans le point ; '' si absente. « .bashrc » n'a pas d'extension."""
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem or not ext:
        return ""
    return ext.lower()


def _entry_from_stat(rel: bytes, st: os.stat_result) -> WalkEntry:
    if stat.S_ISLNK(st.st_mode):
        file_type = "symlink"
    elif stat.S_ISREG(st.st_mode):
        file_type = "file"
    else:
        file_type = "other"
    shown = display_path(rel)
    name = shown.rsplit("/", 1)[-1]
    birth = getattr(st, "st_birthtime", None)
    flags = getattr(st, "st_flags", 0) or 0
    return WalkEntry(
        rel_path_bytes=rel,
        rel_path=shown,
        name=name,
        ext=extension_of(name),
        file_type=file_type,
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        ctime_ns=st.st_ctime_ns,
        birthtime_ns=int(birth * 1_000_000_000) if birth is not None else None,
        inode=st.st_ino,
        device=st.st_dev,
        mode=st.st_mode,
        is_dataless=bool(flags & SF_DATALESS),
    )


def _error(rel: bytes, exc: OSError) -> WalkError:
    code = exc.errno
    label = errno_module.errorcode.get(code, "") if code is not None else ""
    message = f"{label} {exc.strerror or exc}".strip()
    return WalkError(rel, display_path(rel), code, message)


def walk(
    root: Path,
    *,
    stats: WalkStats | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[WalkEntry | WalkError]:
    """Parcourt ``root`` en lecture seule. Les dossiers eux-mêmes ne sont pas rendus."""
    counters = stats if stats is not None else WalkStats()
    base = os.fsencode(root)
    root_stat = os.stat(base)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise NotADirectoryError(errno_module.ENOTDIR, "La source n'est pas un dossier", str(root))
    visited: set[tuple[int, int]] = {(root_stat.st_dev, root_stat.st_ino)}
    stack: list[bytes] = [b""]
    while stack:
        if should_stop is not None and should_stop():
            return
        rel_dir = stack.pop()
        absolute_dir = os.path.join(base, rel_dir) if rel_dir else base
        counters.directories += 1
        try:
            with os.scandir(absolute_dir) as iterator:
                children = sorted(iterator, key=lambda e: e.name)
        except OSError as exc:
            counters.errors += 1
            yield _error(rel_dir, exc)
            continue
        subdirs: list[bytes] = []
        for child in children:
            name = child.name if isinstance(child.name, bytes) else os.fsencode(child.name)
            rel = os.path.join(rel_dir, name) if rel_dir else name
            try:
                st = child.stat(follow_symlinks=False)
            except OSError as exc:
                counters.errors += 1
                yield _error(rel, exc)
                continue
            if stat.S_ISDIR(st.st_mode):
                key = (st.st_dev, st.st_ino)
                if key in visited:
                    counters.cycles_skipped += 1
                    continue
                visited.add(key)
                subdirs.append(rel)
                continue
            counters.entries += 1
            yield _entry_from_stat(rel, st)
        # Ordre déterministe : on dépile les sous-dossiers dans l'ordre alphabétique.
        stack.extend(reversed(subdirs))
