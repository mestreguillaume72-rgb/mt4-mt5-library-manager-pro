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
_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)  # Windows : jamais de conversion des fins de ligne
    | getattr(os, "O_NOINHERIT", 0)
)


class NotRegularFileError(OSError):
    """Le chemin ne désigne pas un fichier ordinaire : il ne sera pas lu."""


_MASK64 = (1 << 64) - 1


def stored_id(value: int) -> int:
    """Numéro de fichier ou de disque ramené à un entier SQLite (64 bits signé). Sous
    Windows (NTFS, ReFS), ces numéros peuvent dépasser 2⁶³, voire tenir sur 128 bits."""
    folded = value
    while folded > _MASK64:
        folded = (folded & _MASK64) ^ (folded >> 64)
    return folded - (1 << 64) if folded >= 1 << 63 else folded


@dataclass(frozen=True)
class FileIdentity:
    size: int
    mtime_ns: int
    inode: int
    device: int

    def same_file(self, other: FileIdentity) -> bool:
        """Fichier inchangé depuis le relevé ``other`` : même taille et même date de
        modification (à la nanoseconde). Les numéros de **disque** et de **fichier** ne sont
        pas comparés : sur un disque externe exFAT/FAT, macOS les attribue à chaque
        branchement (vérifié sur un vrai Mac, CI « disque rebranché »)."""
        return (self.size, self.mtime_ns) == (other.size, other.mtime_ns)

    def same_content_state(self, other: FileIdentity) -> bool:
        """Même taille et même date de modification. Sert à comparer l'état relevé par le
        chemin (``lstat``) à celui du fichier ouvert (``fstat``) : sur certains disques
        externes (exFAT, NTFS, réseau), macOS ne donne pas le même numéro de fichier aux deux,
        alors que c'est bien le même fichier."""
        return self.size == other.size and self.mtime_ns == other.mtime_ns

    @classmethod
    def of(cls, st: os.stat_result) -> FileIdentity:
        return cls(st.st_size, st.st_mtime_ns, stored_id(st.st_ino), stored_id(st.st_dev))


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
