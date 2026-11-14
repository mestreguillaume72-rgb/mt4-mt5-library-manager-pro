"""Lecture des archives RAR, 7z, GZIP, BZIP2, XZ (et TAR qu'elles contiennent) avec
**libarchive**, la bibliothèque de décompression fournie avec macOS (celle de l'Utilitaire
d'archive). Les ZIP restent lus par :mod:`mtlm.formats.archives`.

* lecture seule : le fichier est ouvert par l'application (``O_RDONLY | O_NOFOLLOW``) et
  libarchive ne reçoit que ce descripteur ; rien n'est écrit, rien n'est exécuté ;
* mêmes limites que pour les ZIP, comptées sur les octets **réellement décompressés** ;
* noms dangereux (« .. », chemins absolus), liens et fichiers spéciaux refusés ;
* ``ctypes`` ne charge **que** libarchive du système (exception documentée D-020, vérifiée
  par un test statique). Si elle est absente, ces formats sont « non pris en charge ».
"""

from __future__ import annotations

import ctypes
import hashlib
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from mtlm.formats.archives import (
    READ_CHUNK,
    ArchiveLimits,
    ArchiveReport,
    EntryReport,
    open_readonly_stream,
    unsafe_name_reason,
)

#: Seules bibliothèques chargées : libarchive de macOS, et celle du système Linux (tests).
LIBARCHIVE_MACOS = "/usr/lib/libarchive.2.dylib"
LIBARCHIVE_LINUX = "libarchive.so.13"

_OK, _EOF, _WARN = 0, 1, -20
_IFMT, _IFREG, _IFDIR = 0o170000, 0o100000, 0o040000


class LibArchiveError(Exception):
    """L'archive ne peut pas être lue (corrompue, chiffrée, format non reconnu…)."""


class _Lib:
    def __init__(self) -> None:
        lib = ctypes.CDLL(LIBARCHIVE_MACOS if sys.platform == "darwin" else LIBARCHIVE_LINUX)
        vp, ci, cs = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        signatures: dict[str, tuple[object, list[object]]] = {
            "archive_read_new": (vp, []),
            "archive_read_support_filter_all": (ci, [vp]),
            "archive_read_support_format_all": (ci, [vp]),
            "archive_read_support_format_raw": (ci, [vp]),
            "archive_read_open_fd": (ci, [vp, ci, ctypes.c_size_t]),
            "archive_read_next_header": (ci, [vp, ctypes.POINTER(vp)]),
            "archive_read_data": (ctypes.c_ssize_t, [vp, vp, ctypes.c_size_t]),
            "archive_read_data_skip": (ci, [vp]),
            "archive_read_free": (ci, [vp]),
            "archive_error_string": (cs, [vp]),
            "archive_format_name": (cs, [vp]),
            "archive_filter_code": (ci, [vp, ci]),
            "archive_entry_pathname": (cs, [vp]),
            "archive_entry_pathname_utf8": (cs, [vp]),
            "archive_entry_size": (ctypes.c_int64, [vp]),
            "archive_entry_size_is_set": (ci, [vp]),
            "archive_entry_filetype": (ctypes.c_uint, [vp]),
            "archive_entry_is_encrypted": (ci, [vp]),
        }
        for function, (restype, argtypes) in signatures.items():
            symbol = getattr(lib, function)
            symbol.restype = restype
            symbol.argtypes = argtypes
        self.lib = lib


_cached: _Lib | None = None
_unavailable_reason: str | None = None


def _library() -> _Lib | None:
    global _cached, _unavailable_reason
    if _cached is None and _unavailable_reason is None:
        try:
            _cached = _Lib()
        except (OSError, AttributeError) as exc:
            _unavailable_reason = f"libarchive indisponible sur ce système : {exc}"
    return _cached


def available() -> bool:
    return _library() is not None


@dataclass
class Entry:
    name: str
    is_dir: bool
    is_regular: bool
    is_encrypted: bool
    size: int | None
    chunks: Callable[[], Iterator[bytes]]


def _text(raw: bytes | None) -> str:
    return raw.decode("utf-8", "replace") if raw else ""


#: Compression d'un seul fichier : lue « brute » (une seule entrée). Jamais pour RAR/7z/TAR,
#: pour qu'un faux RAR ne soit pas pris pour un fichier ordinaire.
RAW_KINDS = {"gzip", "bzip2", "xz"}


def iter_entries(path: bytes, kind: str = "") -> Iterator[Entry]:
    """Parcourt l'archive. Chaque entrée n'est lisible (``chunks()``) qu'avant de passer à
    la suivante. Lève :class:`LibArchiveError` si l'archive est illisible."""
    wrapper = _library()
    if wrapper is None:
        raise LibArchiveError(_unavailable_reason or "libarchive indisponible")
    lib = wrapper.lib
    with open_readonly_stream(path) as stream:
        handle = lib.archive_read_new()
        if not handle:
            raise LibArchiveError("mémoire insuffisante")
        try:
            lib.archive_read_support_filter_all(handle)
            lib.archive_read_support_format_all(handle)
            if kind in RAW_KINDS:
                lib.archive_read_support_format_raw(handle)
            if lib.archive_read_open_fd(handle, stream.fileno(), READ_CHUNK) != _OK:
                raise LibArchiveError(_text(lib.archive_error_string(handle)) or "illisible")
            entry = ctypes.c_void_p()
            buffer = ctypes.create_string_buffer(READ_CHUNK)
            first = True
            while True:
                status = lib.archive_read_next_header(handle, ctypes.byref(entry))
                if status == _EOF:
                    return
                if status not in (_OK, _WARN):
                    raise LibArchiveError(_text(lib.archive_error_string(handle)) or "corrompue")
                if first and kind in RAW_KINDS and lib.archive_filter_code(handle, 0) == 0:
                    # Lecture « brute » sans aucune décompression : ce n'est pas une archive.
                    raise LibArchiveError("pas une archive compressée valide")
                first = False
                raw_name = lib.archive_entry_pathname_utf8(entry) or lib.archive_entry_pathname(
                    entry
                )
                filetype = lib.archive_entry_filetype(entry) & _IFMT
                size = (
                    int(lib.archive_entry_size(entry))
                    if lib.archive_entry_size_is_set(entry)
                    else None
                )

                def chunks() -> Iterator[bytes]:
                    while True:
                        count = lib.archive_read_data(handle, buffer, READ_CHUNK)
                        if count == 0:
                            return
                        if count < 0:
                            raise LibArchiveError(
                                _text(lib.archive_error_string(handle)) or "données illisibles"
                            )
                        yield buffer.raw[:count]

                yield Entry(
                    _text(raw_name),
                    filetype == _IFDIR,
                    filetype == _IFREG,
                    bool(lib.archive_entry_is_encrypted(entry)),
                    size,
                    chunks,
                )
        finally:
            lib.archive_read_free(handle)


def inspect(
    path: bytes, archive_format: str, limits: ArchiveLimits, kind: str = ""
) -> ArchiveReport:
    """Empreinte SHA-256 de chaque fichier de l'archive, en mémoire, avec les limites."""
    report = ArchiveReport(archive_format, "ok")
    if not available():
        report.status = "not_supported"
        report.reason = _unavailable_reason or "libarchive indisponible"
        return report
    total = 0
    try:
        for entry in iter_entries(path, kind or archive_format):
            report.entries_total += 1
            name = entry.name
            if entry.is_dir:
                report.entries.append(EntryReport(name, 1, None, None, False, True, "inspected"))
                continue
            if len(report.entries) >= limits.max_entries:
                report.status = "partial"
                report.reason = "nombre d'entrées au-delà de la limite"
                break
            reason = unsafe_name_reason(name)
            if reason is not None:
                report.entries.append(
                    EntryReport(
                        name, 1, entry.size, None, False, False, "rejected_traversal", reason
                    )
                )
                report.status = "partial"
                continue
            if not entry.is_regular:
                report.entries.append(
                    EntryReport(
                        name,
                        1,
                        None,
                        None,
                        False,
                        False,
                        "rejected_symlink",
                        "lien ou fichier spécial : non lu",
                    )
                )
                continue
            if entry.is_encrypted:
                report.entries.append(
                    EntryReport(name, 1, entry.size, None, True, False, "encrypted", "chiffré")
                )
                continue
            digest = hashlib.sha256()
            read = 0
            exceeded: str | None = None
            for chunk in entry.chunks():
                read += len(chunk)
                total += len(chunk)
                if read > limits.max_entry_bytes:
                    exceeded = "taille de l'entrée au-delà de la limite"
                    break
                if total > limits.max_total_bytes:
                    exceeded = "taille totale décompressée au-delà de la limite"
                    break
                digest.update(chunk)
            report.bytes_read = total
            if exceeded:
                report.entries.append(
                    EntryReport(name, 1, read, None, False, False, "skipped_limit", exceeded)
                )
                report.status = "partial"
                if total > limits.max_total_bytes:
                    report.reason = exceeded
                    break
                continue
            report.entries.append(
                EntryReport(name, 1, read, None, False, False, "inspected", sha256=digest.digest())
            )
    except LibArchiveError as exc:
        message = str(exc)
        encrypted = any(word in message.casefold() for word in ("encrypt", "password", "chiffr"))
        if encrypted:
            report.status, report.reason = "encrypted", "archive protégée par mot de passe"
        elif report.entries:
            report.status, report.reason = "partial", f"lecture interrompue : {message}"
        else:
            report.status, report.reason = "corrupt", f"archive illisible : {message}"
    except OSError as exc:
        report.status, report.reason = "corrupt", f"lecture impossible : {exc.strerror or exc}"
    if (
        report.status == "ok"
        and report.entries
        and all(e.is_encrypted for e in report.entries if not e.is_dir)
    ):
        report.status = "encrypted"
    return report
