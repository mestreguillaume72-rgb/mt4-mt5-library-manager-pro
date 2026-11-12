"""Lecture des fichiers SET (jeux de paramètres) MT4 et MT5 (F5).

Formats pris en charge :

* MT4 : ``Nom=Valeur`` + lignes d'optimisation ``Nom,F=0|1``, ``Nom,1=début``,
  ``Nom,2=pas``, ``Nom,3=fin`` ;
* MT5 : ``Nom=Valeur||début||pas||fin||Y/N`` ; commentaires ``;`` en tête.

La **valeur brute** est toujours conservée telle quelle ; la valeur normalisée et le type
estimé s'y ajoutent sans la remplacer. Les lignes mal formées et les clés en double sont
conservées et signalées, jamais ignorées silencieusement.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:\d+[.,]\d*|[.,]\d+|\d+)(?:[eE][+-]?\d+)?$")
_DATE_RE = re.compile(r"^(?:D')?\d{4}\.\d{2}\.\d{2}(?:\s+\d{2}:\d{2}(?::\d{2})?)?'?$")
_COLOR_RE = re.compile(r"^(?:clr[A-Za-z]+|C'\d{1,3},\d{1,3},\d{1,3}'|0x[0-9A-Fa-f]{6})$")
_OPT_SUFFIX_RE = re.compile(r"^(?P<name>.+),(?P<suffix>[F123])$")


@dataclass
class SetParam:
    ordinal: int
    name: str
    raw_value: str
    normalized_value: str | None
    estimated_type: str
    line: int
    opt_start: str | None = None
    opt_step: str | None = None
    opt_stop: str | None = None
    opt_enabled: bool | None = None
    comment: str | None = None


@dataclass
class SetDocument:
    format: str = "unknown"  # mt4 | mt5 | unknown
    format_basis: str = "aucun indice de format"
    params: list[SetParam] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    duplicate_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    line_count: int = 0

    def by_name(self) -> dict[str, SetParam]:
        """Dernière occurrence de chaque nom (comme MetaTrader lors du chargement)."""
        return {p.name: p for p in self.params}

    @property
    def normalized_sha256(self) -> bytes:
        items = sorted(
            (p.name, p.normalized_value if p.normalized_value is not None else p.raw_value)
            for p in self.by_name().values()
        )
        payload = "\n".join(f"{n}={v}" for n, v in items)
        return hashlib.sha256(payload.encode()).digest()


def normalize_value(raw: str) -> tuple[str | None, str]:
    """(valeur normalisée, type estimé). La valeur brute n'est jamais modifiée."""
    value = raw.strip()
    lower = value.lower()
    if lower in ("true", "false"):
        return lower, "bool"
    if _INT_RE.match(value):
        return str(int(value)), "int"
    if _FLOAT_RE.match(value) and any(c in value for c in ".,eE"):
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return value, "string"
        return repr(number), "double"
    if _DATE_RE.match(value):
        return value.removeprefix("D'").rstrip("'"), "datetime"
    if _COLOR_RE.match(value):
        return value, "color"
    return value, "string"


def parse_set(text: str, *, encoding: str | None = None) -> SetDocument:
    doc = SetDocument()
    lines = text.splitlines()
    doc.line_count = len(lines)
    seen: dict[str, int] = {}
    optimisation: dict[str, dict[str, str]] = {}
    mt4_hint = mt5_hint = False
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip().lstrip("﻿")
        if not line:
            continue
        if line.startswith((";", "#")):
            doc.comments.append(line[1:].strip())
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            doc.warnings.append(f"ligne {number} mal formée (attendu « nom=valeur ») : {line[:80]}")
            continue
        suffix = _OPT_SUFFIX_RE.match(key)
        if suffix is not None:
            mt4_hint = True
            optimisation.setdefault(suffix.group("name").strip(), {})[suffix.group("suffix")] = (
                value.strip()
            )
            continue
        opt_start = opt_step = opt_stop = None
        opt_enabled: bool | None = None
        main_value = value
        if "||" in value:
            mt5_hint = True
            parts = value.split("||")
            main_value = parts[0]
            if len(parts) >= 4:
                opt_start, opt_step, opt_stop = parts[1], parts[2], parts[3]
            if len(parts) >= 5:
                opt_enabled = parts[4].strip().upper() == "Y"
            if len(parts) not in (4, 5):
                doc.warnings.append(f"ligne {number} : format d'optimisation MT5 inattendu")
        if key in seen:
            if key not in doc.duplicate_keys:
                doc.duplicate_keys.append(key)
            doc.warnings.append(f"clé en double « {key} » (lignes {seen[key]} et {number})")
        seen[key] = number
        normalized, estimated = normalize_value(main_value)
        doc.params.append(
            SetParam(
                ordinal=len(doc.params) + 1,
                name=key,
                raw_value=main_value,
                normalized_value=normalized,
                estimated_type=estimated,
                line=number,
                opt_start=opt_start,
                opt_step=opt_step,
                opt_stop=opt_stop,
                opt_enabled=opt_enabled,
            )
        )
    by_name = doc.by_name()
    for name, values in optimisation.items():
        param = by_name.get(name)
        if param is None:
            doc.warnings.append(f"ligne d'optimisation pour un paramètre absent : {name}")
            continue
        param.opt_start = values.get("1")
        param.opt_step = values.get("2")
        param.opt_stop = values.get("3")
        if "F" in values:
            param.opt_enabled = values["F"].strip() == "1"
    if mt5_hint and not mt4_hint:
        doc.format, doc.format_basis = "mt5", "valeurs avec « || » (optimisation MT5)"
    elif mt4_hint and not mt5_hint:
        doc.format, doc.format_basis = "mt4", "lignes « nom,F= / nom,1= » (optimisation MT4)"
    elif mt4_hint and mt5_hint:
        doc.format_basis = "indices MT4 et MT5 mélangés"
        doc.warnings.append("indices de format MT4 et MT5 mélangés")
    elif encoding and encoding.startswith("utf-16"):
        doc.format_basis = "encodage UTF-16 (habituel pour MT5) — indice faible"
    if not doc.params:
        doc.warnings.append("aucun paramètre trouvé")
    return doc


@dataclass(frozen=True)
class ParamDiff:
    name: str
    left: str | None
    right: str | None
    status: str  # same | different | only_left | only_right


def compare_sets(left: SetDocument, right: SetDocument) -> list[ParamDiff]:
    """Comparaison paramètre par paramètre (valeurs normalisées)."""
    a, b = left.by_name(), right.by_name()
    result: list[ParamDiff] = []
    for name in sorted(a.keys() | b.keys(), key=str.casefold):
        pa, pb = a.get(name), b.get(name)
        va = pa.normalized_value if pa else None
        vb = pb.normalized_value if pb else None
        if pa is None:
            status = "only_right"
        elif pb is None:
            status = "only_left"
        else:
            status = "same" if va == vb else "different"
        result.append(
            ParamDiff(name, pa.raw_value if pa else None, pb.raw_value if pb else None, status)
        )
    return result


_NAMED_RE = re.compile(
    r"(?:testing|optimi[sz]ing|test|optimisation)(?:\s*/\s*(?:testing|optimi[sz]ing))?"
    r"\s+(?:of\s+|de\s+|du\s+)?(.+?)\s+"
    r"(?:expert advisor|expert|indicator|indicateur|script|ea)\b",
    re.IGNORECASE,
)


def robot_named(comments: list[str]) -> str | None:
    """Nom du robot écrit par MetaTrader dans l'en-tête d'un SET, par exemple
    « ; this file contains input parameters for testing/optimizing Scalper expert advisor »."""
    for comment in comments[:10]:
        match = _NAMED_RE.search(comment)
        if match:
            name = match.group(1).strip().strip("\"'«» ")
            if 0 < len(name) <= 120:
                return name
    return None
