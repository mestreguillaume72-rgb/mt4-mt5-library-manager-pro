"""Décompression **vérifiée** d'une archive (1.5.0, option choisie par l'utilisateur).

* les fichiers sont écrits dans un **nouveau dossier** (créé ici, jamais existant) ;
* seuls les fichiers déjà inspectés et jugés sûrs sont écrits (``expected``), chacun en
  création exclusive (jamais d'écrasement), puis synchronisé sur disque ;
* l'empreinte de chaque fichier écrit doit être **identique** à celle relevée à
  l'inspection ; sinon, ou si un fichier attendu manque, tout ce qui a été extrait est retiré
  (le nouveau dossier) et l'erreur est levée : l'archive n'est alors jamais supprimée ;
* rien n'est exécuté.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import zipfile
from collections.abc import Iterator
from typing import IO

from mtlm.core.errors import MtlmError
from mtlm.core.filenames import portable_name
from mtlm.formats import libarchive
from mtlm.formats.archives import open_readonly_stream, unsafe_name_reason

_WRITE = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)  # Windows : jamais de conversion des fins de ligne
    | getattr(os, "O_NOINHERIT", 0)
)


class ExtractError(MtlmError):
    """Décompression impossible ou non conforme : rien n'est gardé, l'archive reste."""


def _read_all(handle: IO[bytes]) -> Iterator[bytes]:
    while chunk := handle.read(256 * 1024):
        yield chunk


def _entries(path: bytes, kind: str) -> Iterator[tuple[str, Iterator[bytes]]]:
    if kind == "zip":
        with open_readonly_stream(path) as stream, zipfile.ZipFile(stream) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                with archive.open(info) as handle:
                    yield info.filename, _read_all(handle)
        return
    for entry in libarchive.iter_entries(path, kind):
        if entry.is_regular and not entry.is_dir:
            yield entry.name, entry.chunks()


def extract_verified(
    archive_path: bytes, kind: str, destination: bytes, expected: dict[str, bytes]
) -> tuple[int, int]:
    """Extrait les fichiers ``expected`` (nom dans l'archive → SHA-256) dans
    ``destination`` (nouveau dossier). Retourne (fichiers, octets)."""
    if not expected:
        raise ExtractError("aucun fichier vérifiable dans l'archive")
    try:
        os.mkdir(destination)
    except FileExistsError as exc:
        raise ExtractError("le dossier de destination existe déjà : rien n'est écrasé") from exc
    except OSError as exc:
        raise ExtractError(f"dossier de destination impossible : {exc.strerror or exc}") from exc
    written: dict[str, bool] = {}
    # Le disque du Mac ne distingue pas majuscules et minuscules : « Lot.set » et « lot.set »
    # seraient le même fichier. Contenu identique : écrit une fois ; différent : « (2) ».
    placed: dict[str, bytes] = {}
    total = 0
    try:
        for name, chunks in _entries(archive_path, kind):
            if name not in expected or name in written or unsafe_name_reason(name):
                continue
            # Chaque partie du chemin rendue valable sous Windows (« : », « ? »… → « _ »).
            clean = "/".join(portable_name(p) for p in name.replace("\\", "/").split("/") if p)
            key = clean.casefold()
            if key in placed:
                if placed[key] == expected[name]:
                    written[name] = True  # même contenu déjà extrait sous l'autre nom
                    continue
                stem, dot, ext = clean.rpartition(".")
                n = 2
                while True:
                    candidate = f"{stem} ({n}).{ext}" if dot and stem else f"{clean} ({n})"
                    if candidate.casefold() not in placed:
                        break
                    n += 1
                clean, key = candidate, candidate.casefold()
            placed[key] = expected[name]
            relative = os.fsencode(clean)
            target = os.path.join(destination, relative)
            parent = os.path.dirname(target)
            os.makedirs(parent, exist_ok=True)
            if not os.path.realpath(parent).startswith(os.path.realpath(destination)):
                raise ExtractError(f"chemin hors du dossier de destination : {name}")
            digest = hashlib.sha256()
            fd = os.open(target, _WRITE, 0o644)
            try:
                for chunk in chunks:
                    os.write(fd, chunk)
                    digest.update(chunk)
                    total += len(chunk)
                os.fsync(fd)
            finally:
                os.close(fd)
            if digest.digest() != expected[name]:
                raise ExtractError(f"empreinte différente après décompression : {name}")
            written[name] = True
        missing = sorted(set(expected) - set(written))
        if missing:
            raise ExtractError(f"{len(missing)} fichier(s) non retrouvé(s), dont {missing[0]}")
    except (ExtractError, OSError, zipfile.BadZipFile, libarchive.LibArchiveError) as exc:
        with contextlib.suppress(OSError):
            shutil.rmtree(destination)
        if isinstance(exc, ExtractError):
            raise
        raise ExtractError(f"décompression interrompue : {exc}") from exc
    return len(written), total
