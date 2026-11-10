"""Lecture en flux, en lecture seule, d'un fichier ordinaire (F2).

* Ouverture ``O_RDONLY | O_NOFOLLOW`` : jamais d'écriture, jamais de suivi de lien.
* Lecture par blocs : la mémoire utilisée ne dépend pas de la taille du fichier.
* Les fichiers non ordinaires (tubes, périphériques…) sont refusés avant toute lecture.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass

DEFAULT_CHUNK = 1024 * 1024
_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class NotRegularFileError(OSError):
    """Le chemin ne désigne pas un fichier ordinaire : il ne sera pas lu."""


@dataclass(frozen=True)
class FileIdentity:
    size: int
    mtime_ns: int
    inode: int
    device: int

    @classmethod
    def of(cls, st: os.stat_result) -> FileIdentity:
        return cls(st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)


class ReadOnlyFile:
    """Fichier ouvert en lecture seule ; à utiliser comme gestionnaire de contexte."""

    def __init__(self, path: bytes) -> None:
        self.path = path
        # O_NONBLOCK évite tout blocage si le chemin a été remplacé par un tube entre-temps.
        fd = os.open(path, _FLAGS | getattr(os, "O_NONBLOCK", 0))
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise NotRegularFileError(0, "pas un fichier ordinaire : non lu")
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        self.opened_identity = FileIdentity.of(st)

    def chunks(self, size: int = DEFAULT_CHUNK) -> Iterator[bytes]:
        while chunk := os.read(self._fd, size):
            yield chunk

    def current_identity(self) -> FileIdentity:
        return FileIdentity.of(os.fstat(self._fd))

    def close(self) -> None:
        os.close(self._fd)

    def __enter__(self) -> ReadOnlyFile:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def path_identity(path: bytes) -> FileIdentity:
    return FileIdentity.of(os.lstat(path))
