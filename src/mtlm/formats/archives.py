"""Inspection sécurisée des archives ZIP (F3, D-006). RAR, 7z, GZIP, BZIP2, XZ et TAR sont
lus par :mod:`mtlm.formats.libarchive` (bibliothèque de macOS), avec les mêmes garanties.

Garanties :

* **rien n'est extrait sur disque** : chaque entrée est décompressée en mémoire, par blocs,
  directement vers le calcul d'empreinte, puis oubliée ;
* aucun contenu n'est exécuté ni interprété ;
* limites configurables, comptées sur les octets **réellement décompressés** (et non sur
  les tailles annoncées par l'archive, falsifiables) : profondeur d'imbrication, nombre
  d'entrées, taille totale, taille par entrée, ratio de compression ;
* entrées refusées : chemins absolus, lecteurs Windows, « .. » (traversée), liens
  symboliques ; noms en double signalés ; entrées chiffrées non lues ;
* une archive corrompue échoue proprement, avec un motif journalisable.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import BinaryIO

from mtlm.fs.reader import NotRegularFileError

READ_CHUNK = 256 * 1024
_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


@dataclass(frozen=True)
class ArchiveLimits:
    max_depth: int = 2
    max_entries: int = 10_000
    max_total_bytes: int = 2 * 1024**3
    max_entry_bytes: int = 512 * 1024**2
    max_ratio: float = 100.0
    max_nested_bytes: int = 64 * 1024**2  # une archive imbriquée est lue en mémoire


@dataclass
class EntryReport:
    inner_path: str
    depth: int
    size: int | None
    compressed_size: int | None
    is_encrypted: bool
    is_dir: bool
    # inspected | skipped_limit | rejected_traversal | rejected_symlink | encrypted | corrupt
    status: str
    reason: str | None = None
    sha256: bytes | None = None


@dataclass
class ArchiveReport:
    format: str
    status: str  # ok | partial | corrupt | encrypted | not_supported | rejected
    entries: list[EntryReport] = field(default_factory=list)
    entries_total: int = 0
    bytes_read: int = 0
    reason: str | None = None

    @property
    def entries_read(self) -> int:
        return sum(1 for e in self.entries if e.status == "inspected" and not e.is_dir)


class _Budget:
    def __init__(self, limits: ArchiveLimits) -> None:
        self.limits = limits
        self.total = 0
        self.entries = 0


def unsafe_name_reason(name: str) -> str | None:
    """Motif de refus d'un nom d'entrée, ou ``None`` s'il est sûr."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return "chemin absolu"
    if len(normalized) >= 2 and normalized[1] == ":" and normalized[0].isalpha():
        return "lecteur Windows"
    if any(part == ".." for part in normalized.split("/")):
        return "traversée de dossier (« .. »)"
    if "\x00" in name:
        return "caractère nul dans le nom"
    return None


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return info.create_system == 3 and stat.S_ISLNK(info.external_attr >> 16)


def _hash_entry(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: _Budget, keep_bytes: bool
) -> tuple[bytes, int, bytes | None, str | None]:
    """Décompresse en mémoire en comptant les octets réels. Retourne
    (sha256, taille, contenu éventuel, motif de dépassement)."""
    limits = budget.limits
    digest = hashlib.sha256()
    read = 0
    kept = bytearray() if keep_bytes else None
    compressed = max(1, info.compress_size)
    with archive.open(info) as stream:
        while chunk := stream.read(READ_CHUNK):
            read += len(chunk)
            budget.total += len(chunk)
            if read > limits.max_entry_bytes:
                return b"", read, None, "taille de l'entrée au-delà de la limite"
            if budget.total > limits.max_total_bytes:
                return b"", read, None, "taille totale décompressée au-delà de la limite"
            if read > 1024 * 1024 and read / compressed > limits.max_ratio:
                return (
                    b"",
                    read,
                    None,
                    (f"ratio de compression > {limits.max_ratio:.0f}:1 (archive piégée probable)"),
                )
            digest.update(chunk)
            if kept is not None:
                if read > limits.max_nested_bytes:
                    kept = None
                else:
                    kept.extend(chunk)
    return digest.digest(), read, bytes(kept) if kept is not None else None, None


def _inspect_zip(
    source: BinaryIO, depth: int, prefix: str, budget: _Budget, report: ArchiveReport
) -> None:
    limits = budget.limits
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        report.entries_total += len(infos)
        seen: set[str] = set()
        for info in infos:
            name = info.filename
            shown = f"{prefix}{name}"
            entry = EntryReport(
                inner_path=shown,
                depth=depth,
                size=info.file_size,
                compressed_size=info.compress_size,
                is_encrypted=bool(info.flag_bits & 0x1),
                is_dir=info.is_dir(),
                status="inspected",
            )
            report.entries.append(entry)
            budget.entries += 1
            if budget.entries > limits.max_entries:
                entry.status = "skipped_limit"
                entry.reason = "nombre d'entrées au-delà de la limite"
                report.status = "partial"
                continue
            reason = unsafe_name_reason(name)
            if reason is not None:
                entry.status, entry.reason = "rejected_traversal", reason
                report.status = "partial"
                continue
            if _is_symlink(info):
                entry.status, entry.reason = "rejected_symlink", "lien symbolique dans l'archive"
                report.status = "partial"
                continue
            key = name.replace("\\", "/").casefold()
            if key in seen:
                entry.reason = "nom en double dans l'archive"
            seen.add(key)
            if entry.is_dir:
                continue
            if entry.is_encrypted:
                entry.status, entry.reason = "encrypted", "entrée chiffrée : non lue"
                report.status = "partial"
                continue
            nested = name.lower().endswith(".zip")
            try:
                digest, size, data, over = _hash_entry(archive, info, budget, keep_bytes=nested)
            except (
                zipfile.BadZipFile,
                zlib.error,
                EOFError,
                NotImplementedError,
                RuntimeError,
                ValueError,
            ) as exc:
                entry.status, entry.reason = "corrupt", f"entrée illisible : {exc}"
                report.status = "partial"
                continue
            report.bytes_read += size
            if over is not None:
                entry.status, entry.reason = "skipped_limit", over
                report.status = "partial"
                continue
            entry.sha256, entry.size = digest, size
            if nested:
                if depth >= limits.max_depth:
                    entry.reason = "archive imbriquée non ouverte (profondeur maximale)"
                elif data is None:
                    entry.reason = "archive imbriquée trop volumineuse pour être ouverte"
                elif data[:2] == b"PK":
                    try:
                        _inspect_zip(io.BytesIO(data), depth + 1, f"{shown}!/", budget, report)
                    except zipfile.BadZipFile as exc:
                        entry.reason = f"archive imbriquée corrompue : {exc}"
                        report.status = "partial"


def open_readonly_stream(path: bytes) -> BinaryIO:
    fd = os.open(path, _FLAGS | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise NotRegularFileError(0, "pas un fichier ordinaire : non lu")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def inspect_archive(
    path: bytes, signature_kind: str, limits: ArchiveLimits | None = None
) -> ArchiveReport:
    """Inspecte l'archive ``path`` (lecture seule). ``signature_kind`` vient de
    :func:`mtlm.formats.signatures.sniff`."""
    if signature_kind in ("rar", "7z", "gzip", "bzip2", "xz", "tar"):
        from mtlm.formats import libarchive

        stored = signature_kind if signature_kind in ("rar", "7z", "gzip") else "other"
        return libarchive.inspect(path, stored, limits or ArchiveLimits(), signature_kind)
    if signature_kind != "zip":
        return ArchiveReport("other", "rejected", reason="pas une archive ZIP")
    report = ArchiveReport("zip", "ok")
    budget = _Budget(limits or ArchiveLimits())
    try:
        with open_readonly_stream(path) as stream:
            _inspect_zip(stream, 1, "", budget, report)
    except zipfile.BadZipFile as exc:
        report.status, report.reason = "corrupt", f"archive corrompue : {exc}"
    except OSError as exc:
        report.status, report.reason = "corrupt", f"lecture impossible : {exc.strerror or exc}"
    if (
        report.status != "corrupt"
        and report.entries
        and all(e.is_encrypted for e in report.entries if not e.is_dir)
    ):
        report.status = "encrypted"
    return report


def iter_inspected(report: ArchiveReport) -> Iterator[EntryReport]:
    return (e for e in report.entries if e.status == "inspected" and e.sha256 is not None)
