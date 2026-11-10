"""Instantané d'une arborescence pour l'invariant « sources inchangées » (PLAN_DE_TESTS § 5).

Pour chaque entrée (sans suivre les liens) : type, taille, SHA-256 du contenu,
``mtime_ns``, ``ctime_ns``, mode, propriétaire, attributs étendus. Comparer deux
instantanés détecte toute création, suppression, modification de contenu ou de
métadonnées. ``atime`` est volontairement exclu (dépend des options de montage).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EntryState:
    kind: str
    size: int
    sha256: str | None
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int
    gid: int
    xattrs: tuple[tuple[str, str], ...]


Snapshot = dict[bytes, EntryState]


def _hash_file(path: bytes) -> str:
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        while chunk := os.read(fd, 1 << 20):
            digest.update(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest()


def _xattrs_linux(path: bytes) -> tuple[tuple[str, str], ...]:
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError:
        return ()
    values = []
    for name in sorted(names):
        try:
            value = os.getxattr(path, name, follow_symlinks=False)
        except OSError:
            value = b"<illisible>"
        values.append((name, hashlib.sha256(value).hexdigest()))
    return tuple(values)


_XATTR_NOFOLLOW = 0x0001
_libc = None


def _xattrs_darwin(path: bytes) -> tuple[tuple[str, str], ...]:
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    size = _libc.listxattr(path, None, 0, _XATTR_NOFOLLOW)
    if size <= 0:
        return ()
    buffer = ctypes.create_string_buffer(size)
    size = _libc.listxattr(path, buffer, size, _XATTR_NOFOLLOW)
    names = [n for n in buffer.raw[:size].split(b"\x00") if n]
    values = []
    for name in sorted(names):
        vsize = _libc.getxattr(path, name, None, 0, 0, _XATTR_NOFOLLOW)
        value = b""
        if vsize > 0:
            vbuf = ctypes.create_string_buffer(vsize)
            vsize = _libc.getxattr(path, name, vbuf, vsize, 0, _XATTR_NOFOLLOW)
            value = vbuf.raw[: max(vsize, 0)]
        values.append((name.decode("utf-8", "replace"), hashlib.sha256(value).hexdigest()))
    return tuple(values)


def _xattrs(path: bytes) -> tuple[tuple[str, str], ...]:
    if sys.platform == "darwin":
        return _xattrs_darwin(path)
    if hasattr(os, "listxattr"):
        return _xattrs_linux(path)
    return ()


def take_snapshot(root: Path) -> Snapshot:
    base = os.fsencode(root)
    result: Snapshot = {}
    stack = [base]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                st = entry.stat(follow_symlinks=False)
                rel = os.path.relpath(entry.path, base)
                if stat.S_ISLNK(st.st_mode):
                    target = Path(os.fsdecode(entry.path)).readlink()
                    kind, digest = "link", hashlib.sha256(os.fsencode(target)).hexdigest()
                elif stat.S_ISDIR(st.st_mode):
                    kind, digest = "dir", None
                    stack.append(entry.path)
                elif stat.S_ISREG(st.st_mode):
                    kind = "file"
                    digest = _hash_file(entry.path) if st.st_mode & stat.S_IRUSR else None
                else:
                    kind, digest = "other", None
                result[rel] = EntryState(
                    kind,
                    st.st_size,
                    digest,
                    st.st_mtime_ns,
                    st.st_ctime_ns,
                    st.st_mode,
                    st.st_uid,
                    st.st_gid,
                    _xattrs(entry.path),
                )
    return result


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[str]:
    """Liste lisible des différences (vide si identiques)."""
    problems: list[str] = []
    for rel in sorted(before.keys() - after.keys()):
        problems.append(f"supprimé : {rel!r}")
    for rel in sorted(after.keys() - before.keys()):
        problems.append(f"créé : {rel!r}")
    for rel in sorted(before.keys() & after.keys()):
        if before[rel] != after[rel]:
            problems.append(f"modifié : {rel!r} {before[rel]} -> {after[rel]}")
    return problems
