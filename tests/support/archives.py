"""Fabrication d'archives ZIP de test, saines ou hostiles (générées à la volée, jamais
versionnées)."""

from __future__ import annotations

import io
import stat
import struct
import warnings
import zipfile
from pathlib import Path


def make_zip(path: Path, files: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> Path:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # noms en double volontaires
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, data in files.items():
                archive.writestr(name, data)
    return path


def make_zip_entries(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    """Comme :func:`make_zip`, mais autorise plusieurs entrées de même nom."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in entries:
                archive.writestr(name, data)
    return path


def make_symlink_zip(path: Path) -> Path:
    info = zipfile.ZipInfo("lien_vers_etc")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, "/etc/passwd")
        archive.writestr("normal.mq4", b"// ok")
    return path


def make_bomb(path: Path, size: int = 64 * 1024 * 1024) -> Path:
    """Archive piégée simulée : beaucoup de zéros très compressés (ratio ~1000:1)."""
    chunk = b"\x00" * (1024 * 1024)
    with (
        zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive,
        archive.open("bombe.bin", "w", force_zip64=True) as entry,
    ):
        for _ in range(size // len(chunk)):
            entry.write(chunk)
    return path


def make_encrypted(path: Path) -> Path:
    """ZIP dont les entrées sont marquées chiffrées (bit 0 des drapeaux)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("secret.set", b"Lots=0.1\n")
    data = bytearray(buffer.getvalue())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (pos := data.find(signature, start)) != -1:
            flags = struct.unpack_from("<H", data, pos + offset)[0]
            struct.pack_into("<H", data, pos + offset, flags | 0x1)
            start = pos + 4
    path.write_bytes(bytes(data))
    return path


def make_bad_crc(path: Path) -> Path:
    make_zip(path, {"a.mq4": b"A" * 1000, "b.mq4": b"B" * 1000}, compression=zipfile.ZIP_STORED)
    data = bytearray(path.read_bytes())
    pos = data.find(b"A" * 100)
    data[pos] = ord("Z")  # contenu altéré : CRC incorrect
    path.write_bytes(bytes(data))
    return path
