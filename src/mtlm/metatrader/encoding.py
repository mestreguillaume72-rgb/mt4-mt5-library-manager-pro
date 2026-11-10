"""Détection d'encodage des fichiers texte MetaTrader (sources MQL, SET).

Ordre : BOM (UTF-8, UTF-16 LE/BE) → UTF-16 sans BOM (octets nuls alternés) → UTF-8 strict →
Windows-1252 → Latin-1 (toujours décodable, confiance faible). La confiance est indiquée :
l'application ne présente jamais un décodage incertain comme certain.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str
    confidence: float


def _utf16_without_bom(data: bytes) -> str | None:
    sample = data[:1024]
    if len(sample) < 4:
        return None
    pairs = len(sample) // 2
    odd = sum(1 for i in range(1, len(sample), 2) if sample[i] == 0) / pairs
    even = sum(1 for i in range(0, len(sample), 2) if sample[i] == 0) / pairs
    if odd > 0.7:
        return "utf-16-le"
    if even > 0.7:
        return "utf-16-be"
    return None


def decode_text(data: bytes) -> DecodedText:
    if data.startswith(b"\xef\xbb\xbf"):
        return DecodedText(data[3:].decode("utf-8", errors="replace"), "utf-8-bom", 1.0)
    if data.startswith(b"\xff\xfe"):
        return DecodedText(data[2:].decode("utf-16-le", errors="replace"), "utf-16-le-bom", 1.0)
    if data.startswith(b"\xfe\xff"):
        return DecodedText(data[2:].decode("utf-16-be", errors="replace"), "utf-16-be-bom", 1.0)
    utf16 = _utf16_without_bom(data)
    if utf16 is not None:
        return DecodedText(data.decode(utf16, errors="replace"), utf16, 0.8)
    try:
        text = data.decode("utf-8")
        return DecodedText(
            text, "ascii" if text.isascii() else "utf-8", 1.0 if text.isascii() else 0.9
        )
    except UnicodeDecodeError:
        pass
    try:
        return DecodedText(data.decode("cp1252"), "cp1252", 0.6)
    except UnicodeDecodeError:
        return DecodedText(data.decode("latin-1"), "latin-1", 0.3)
