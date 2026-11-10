"""Normalisation des noms de fichiers pour l'identité logique (F5, F6).

« Robot_v1.2 - Copie (3).mq4 » et « ROBOT.ex4 » donnent la même clé « robot ».
Les marqueurs de version sont extraits séparément (version estimée).
"""

from __future__ import annotations

import re
import unicodedata

_VERSION_RE = re.compile(r"(?:^|[\s_\-.(\[])v?(\d+(?:[._]\d+)+)(?=$|[\s_\-)\]])", re.I)
_VERSION_SIMPLE_RE = re.compile(r"(?:^|[\s_\-(\[])v(\d+)(?=$|[\s_\-)\]])", re.I)
_NOISE_RE = re.compile(
    r"(?:[\s_\-]*\(\d+\)|[\s_\-]+(?:copie|copy|kopie|copia|backup|old|new|final)(?:\s*\d+)?)",
    re.I,
)


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def stem(file_name: str) -> str:
    name = file_name.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name[1:] else name


def version_in_name(file_name: str) -> str | None:
    base = stem(file_name)
    match = _VERSION_RE.search(base) or _VERSION_SIMPLE_RE.search(base)
    return match.group(1).replace("_", ".") if match else None


def logical_key(file_name: str) -> str:
    """Clé d'identité logique : minuscules, sans accents, sans version ni « copie »."""
    base = stem(file_name)
    base = _VERSION_RE.sub(" ", base)
    base = _VERSION_SIMPLE_RE.sub(" ", base)
    base = _NOISE_RE.sub(" ", base)
    base = strip_accents(base).casefold()
    return re.sub(r"[^0-9a-z]+", "", base)


def parse_version(value: str | None) -> tuple[int, ...] | None:
    if not value:
        return None
    numbers = re.findall(r"\d+", value)
    return tuple(int(n) for n in numbers) if numbers else None
