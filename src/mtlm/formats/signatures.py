"""Identification par signature binaire (« nombres magiques ») — F3, F4.

Seuls les premiers octets sont examinés. Le résultat sert à classer et à signaler les
extensions trompeuses ; il ne prétend jamais connaître le contenu d'un format opaque
(EX4/EX5 restent « binaire »).
"""

from __future__ import annotations

from dataclasses import dataclass

HEAD_SIZE = 4096

_MAGICS: list[tuple[bytes, str]] = [
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),  # archive ZIP vide
    (b"Rar!\x1a\x07", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"\x1f\x8b", "gzip"),
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"\x7fELF", "elf"),
    (b"\xcf\xfa\xed\xfe", "macho"),
    (b"\xce\xfa\xed\xfe", "macho"),
    (b"\xca\xfe\xba\xbe", "macho"),  # binaire universel (ou classe Java)
    (b"SQLite format 3\x00", "sqlite"),
    (b"RIFF", "riff"),  # WAV, AVI…
]


@dataclass(frozen=True)
class Signature:
    kind: str  # zip, rar, pe, text, utf16-text, binary, empty…
    label: str  # description lisible en français


LABELS = {
    "zip": "archive ZIP",
    "rar": "archive RAR",
    "7z": "archive 7-Zip",
    "gzip": "archive GZIP",
    "pdf": "document PDF",
    "png": "image PNG",
    "jpeg": "image JPEG",
    "gif": "image GIF",
    "bmp": "image BMP",
    "ico": "icône",
    "elf": "exécutable Linux",
    "macho": "exécutable macOS",
    "pe": "exécutable ou bibliothèque Windows (PE)",
    "sqlite": "base SQLite",
    "riff": "fichier RIFF (son/vidéo)",
    "utf16-text": "texte UTF-16",
    "text": "texte",
    "binary": "binaire (format non identifié)",
    "empty": "fichier vide",
}


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        if exc.start >= len(head) - 3:  # caractère coupé en fin d'échantillon
            return True
    # Texte 8 bits (Windows-1252) : majoritairement imprimable.
    printable = sum(1 for c in head if c >= 0x20 or c in (9, 10, 13))
    return printable / max(1, len(head)) > 0.95


def _looks_like_utf16(head: bytes) -> bool:
    sample = head[:512]
    if len(sample) < 4:
        return False
    odd_zero = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0)
    return odd_zero / (len(sample) // 2) > 0.7


def sniff(head: bytes) -> Signature:
    if not head:
        return Signature("empty", LABELS["empty"])
    for magic, kind in _MAGICS:
        if head.startswith(magic):
            return Signature(kind, LABELS[kind])
    if head.startswith(b"MZ"):
        return Signature("pe", LABELS["pe"])
    if head.startswith(b"BM") and len(head) > 14 and head[6:10] == b"\x00\x00\x00\x00":
        return Signature("bmp", LABELS["bmp"])
    if head.startswith(b"\x00\x00\x01\x00"):
        return Signature("ico", LABELS["ico"])
    if head.startswith((b"\xff\xfe", b"\xfe\xff")) or _looks_like_utf16(head):
        return Signature("utf16-text", LABELS["utf16-text"])
    if head.startswith(b"\xef\xbb\xbf") or _looks_like_text(head):
        return Signature("text", LABELS["text"])
    return Signature("binary", LABELS["binary"])


# Signatures attendues par extension (pour détecter les extensions trompeuses).
_TEXTUAL = {"text", "utf16-text", "empty"}
EXPECTED: dict[str, set[str]] = {
    "mq4": _TEXTUAL,
    "mq5": _TEXTUAL,
    "mqh": _TEXTUAL,
    "set": _TEXTUAL,
    "tpl": _TEXTUAL,
    "csv": _TEXTUAL,
    "ini": _TEXTUAL,
    "txt": _TEXTUAL,
    "chr": _TEXTUAL,
    "htm": _TEXTUAL,
    "html": _TEXTUAL,
    "log": _TEXTUAL,
    "mqproj": _TEXTUAL,
    "zip": {"zip"},
    "rar": {"rar"},
    "7z": {"7z"},
    "gz": {"gzip"},
    "dll": {"pe"},
    "exe": {"pe"},
    "pdf": {"pdf"},
    "png": {"png"},
    "jpg": {"jpeg"},
    "jpeg": {"jpeg"},
    "gif": {"gif"},
    "bmp": {"bmp"},
    "ico": {"ico"},
    "wav": {"riff"},
    # Binaires compilés MetaTrader : format propriétaire opaque. Un fichier texte, une archive
    # ou un exécutable portant cette extension est suspect.
    "ex4": {"binary"},
    "ex5": {"binary"},
}


def is_misleading(ext: str, signature: Signature) -> bool:
    """Vrai si l'extension annonce un format incompatible avec la signature lue."""
    expected = EXPECTED.get(ext)
    if expected is None or signature.kind == "empty":
        return False
    return signature.kind not in expected
