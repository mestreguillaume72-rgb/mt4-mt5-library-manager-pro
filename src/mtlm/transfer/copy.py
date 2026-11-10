"""Copie **vérifiée** d'un fichier vers une destination (F8, F9).

Protocole (aucun octet de la source n'est jamais modifié) :

1. la source est ouverte en lecture seule ; son identité doit correspondre à l'inventaire ;
2. écriture dans un fichier temporaire ``*.mtlm-partial`` créé en exclusivité (jamais
   d'écrasement), en calculant le SHA-256 des octets lus ;
3. ``fsync`` du fichier ; la source doit être restée stable pendant la copie ;
4. **relecture** du fichier écrit et comparaison de son SHA-256 à l'empreinte attendue ;
5. mise en place sous le nom final **sans écrasement possible** (lien matériel puis suppression
   du temporaire ; repli contrôlé si le système de fichiers ne gère pas les liens) ; ``fsync``
   du dossier ;
6. la date de modification de la **copie** reprend celle de l'original (traçabilité).

En cas d'échec à n'importe quelle étape : le temporaire est supprimé (il est dans la
destination), l'erreur est levée, l'original reste intact.
"""

from __future__ import annotations

import errno
import hashlib
import os
from dataclasses import dataclass

from mtlm.core.errors import MtlmError
from mtlm.fs.reader import FileIdentity, ReadOnlyFile, path_identity

PARTIAL_SUFFIX = b".mtlm-partial"
CHUNK = 1024 * 1024
_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)


class CopyError(MtlmError):
    """La copie n'a pas pu être réalisée ou vérifiée ; l'original est intact."""


@dataclass(frozen=True)
class CopyResult:
    destination: bytes
    size: int
    sha256: bytes


def _fsync_dir(path: bytes) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _sha_of(path: bytes) -> bytes:
    digest = hashlib.sha256()
    with ReadOnlyFile(path) as handle:
        for chunk in handle.chunks(CHUNK):
            digest.update(chunk)
    return digest.digest()


def _place_without_overwrite(temp: bytes, destination: bytes) -> None:
    try:
        os.link(temp, destination)
    except FileExistsError as exc:
        raise CopyError(f"La destination existe déjà : {os.fsdecode(destination)}") from exc
    except OSError as exc:
        if exc.errno not in (
            errno.EPERM,
            errno.ENOTSUP,
            errno.EOPNOTSUPP,
            errno.EXDEV,
            errno.EMLINK,
        ):
            raise
        # Système de fichiers sans liens matériels (exFAT, certains partages réseau).
        if os.path.lexists(destination):
            raise CopyError(f"La destination existe déjà : {os.fsdecode(destination)}") from exc
        os.rename(temp, destination)
        return
    os.unlink(temp)


def copy_verified(
    source: bytes,
    destination: bytes,
    *,
    expected_sha256: bytes,
    expected_identity: FileIdentity | None = None,
) -> CopyResult:
    if os.path.lexists(destination):
        raise CopyError(f"La destination existe déjà : {os.fsdecode(destination)}")
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    temp = destination + PARTIAL_SUFFIX
    if os.path.lexists(temp):
        os.unlink(temp)  # reste d'une copie interrompue, dans la destination
    digest = hashlib.sha256()
    size = 0
    try:
        with ReadOnlyFile(source) as reader:
            if expected_identity is not None and reader.opened_identity != expected_identity:
                raise CopyError("L'original a changé depuis l'inventaire : copie refusée")
            before = reader.opened_identity
            fd = os.open(temp, _WRITE_FLAGS, 0o644)
            try:
                for chunk in reader.chunks(CHUNK):
                    digest.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(fd, view)
                        view = view[written:]
                    size += len(chunk)
                os.fsync(fd)
            finally:
                os.close(fd)
            if reader.current_identity() != before or path_identity(source) != before:
                raise CopyError("L'original a changé pendant la copie : copie annulée")
        if digest.digest() != expected_sha256:
            raise CopyError("Le contenu lu ne correspond pas à l'empreinte attendue")
        if _sha_of(temp) != expected_sha256:
            raise CopyError("Copie corrompue : l'empreinte relue est différente")
        os.utime(temp, ns=(before.mtime_ns, before.mtime_ns), follow_symlinks=False)
        _place_without_overwrite(temp, destination)
        _fsync_dir(parent)
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise CopyError("Disque de destination plein : copie annulée") from exc
        raise CopyError(f"Copie impossible : {exc.strerror or exc}") from exc
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)
    return CopyResult(destination, size, expected_sha256)
