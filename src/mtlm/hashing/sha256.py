"""Calcul d'empreinte SHA-256 en flux avec protocole de **stabilité** (F2, F7).

Une empreinte n'est déclarée valide que si le fichier n'a pas changé pendant la lecture :
taille, date de modification, inode et périphérique sont identiques avant et après lecture,
sur le descripteur ouvert **et** sur le chemin (détecte un remplacement du fichier), et le
nombre d'octets lus correspond à la taille. Sinon : :class:`UnstableFileError`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from mtlm.fs.reader import DEFAULT_CHUNK, FileIdentity, ReadOnlyFile, path_identity


class UnstableFileError(Exception):
    """Le fichier a changé pendant ou depuis sa lecture : empreinte non fiable."""


@dataclass(frozen=True)
class HashResult:
    sha256: bytes
    size: int
    identity: FileIdentity


def hash_file(
    path: bytes,
    *,
    expected: FileIdentity | None = None,
    chunk_size: int = DEFAULT_CHUNK,
    on_chunk: Callable[[int], None] | None = None,
) -> HashResult:
    """Calcule le SHA-256 de ``path`` en lecture seule.

    ``expected`` : identité relevée lors de l'inventaire ; si le fichier a changé depuis,
    l'empreinte est refusée (il faut ré-inventorier). ``on_chunk`` est appelé après chaque
    bloc avec le nombre d'octets lus (progression, pause, annulation).
    """
    with ReadOnlyFile(path) as handle:
        before = handle.opened_identity
        if expected is not None and before != expected:
            raise UnstableFileError("modifié depuis l'inventaire : relancez l'inventaire")
        digest = hashlib.sha256()
        total = 0
        for chunk in handle.chunks(chunk_size):
            digest.update(chunk)
            total += len(chunk)
            if on_chunk is not None:
                on_chunk(len(chunk))
        after_fd = handle.current_identity()
    after_path = path_identity(path)
    if not (before == after_fd == after_path) or total != before.size:
        raise UnstableFileError("modifié pendant la lecture : empreinte non fiable")
    return HashResult(digest.digest(), total, before)
