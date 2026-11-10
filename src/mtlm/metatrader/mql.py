"""Analyse lexicale tolérante des sources MQL4/MQL5 (F4).

Extrait uniquement ce qui est **déclaré** dans le texte : ``#property``, ``#include``,
``#import``, paramètres ``input``/``extern``/``sinput`` et fonctions d'entrée. Les
commentaires et chaînes sont neutralisés avant toute recherche (un ``input`` en commentaire
n'est jamais pris pour un paramètre). Aucune compilation, aucune exécution, aucune résolution
du préprocesseur conditionnel (limite documentée).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

ENTRY_FUNCTIONS = (
    "OnTick",
    "OnCalculate",
    "OnStart",
    "OnInit",
    "OnDeinit",
    "OnTimer",
    "OnTester",
    "OnChartEvent",
    "OnTrade",
    "OnTradeTransaction",
    "OnBookEvent",
)
_ENTRY_RE = re.compile(
    r"\b(?:void|int|double|bool)\s+(" + "|".join(ENTRY_FUNCTIONS) + r"|start|init|deinit)\s*\("
)
_DIRECTIVE_RE = re.compile(r"^\s*#\s*([A-Za-z_]+)\b(.*)$")
_INPUT_START_RE = re.compile(r"\b(input|extern|sinput)\b")
_DECL_HEAD_RE = re.compile(
    r"^\s*(?:const\s+)?(?P<type>(?:unsigned\s+)?[A-Za-z_]\w*)\s+(?P<rest>.+)$", re.S
)
_DECLARATOR_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:=\s*(?P<default>.*))?$", re.S
)


@dataclass(frozen=True)
class MqlInput:
    ordinal: int
    name: str
    mql_type: str
    default_raw: str | None
    modifier: str
    line: int


@dataclass
class MqlSource:
    properties: dict[str, str] = field(default_factory=dict)
    property_flags: set[str] = field(default_factory=set)
    includes: list[tuple[str, bool, int]] = field(default_factory=list)  # (cible, système, ligne)
    imports: list[tuple[str, int]] = field(default_factory=list)
    inputs: list[MqlInput] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    line_count: int = 0
    normalized_sha256: bytes = b""
    warnings: list[str] = field(default_factory=list)

    @property
    def is_indicator(self) -> bool:
        return any(f.startswith("indicator_") for f in self.property_flags)


def _neutralize(text: str) -> tuple[str, str]:
    """Retourne (sans_commentaires, code) de même longueur que ``text`` :

    * ``sans_commentaires`` : commentaires remplacés par des espaces, chaînes conservées ;
    * ``code`` : commentaires ET contenu des chaînes/caractères remplacés par des espaces.
    Les sauts de ligne sont conservés (numéros de ligne exacts).
    """
    no_comments = list(text)
    code = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                no_comments[i] = code[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            for j in range(i, end):
                if text[j] != "\n":
                    no_comments[j] = code[j] = " "
            i = end
        elif c in ('"', "'"):
            quote = c
            i += 1
            while i < n and text[i] != quote and text[i] != "\n":
                if text[i] == "\\" and i + 1 < n:
                    code[i] = " "
                    i += 1
                code[i] = " "
                i += 1
            i += 1
        else:
            i += 1
    return "".join(no_comments), "".join(code)


def _string_literal(value: str) -> str | None:
    match = re.match(r'\s*"((?:[^"\\]|\\.)*)"', value)
    if match is None:
        return None
    return re.sub(
        r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), match.group(1)
    )


def _split_top_level(text: str) -> list[str]:
    parts, depth, current, quote = [], 0, [], ""
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return parts


def _brace_depths(code: str) -> list[int]:
    depths, depth = [], 0
    for ch in code:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        depths.append(depth)
    return depths


def normalized_text(no_comments: str) -> str:
    """Texte normalisé pour comparer des sources : sans commentaires, espaces réduits."""
    return " ".join(no_comments.split())


def parse_mql(text: str) -> MqlSource:
    result = MqlSource()
    no_comments, code = _neutralize(text)
    result.line_count = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    result.normalized_sha256 = hashlib.sha256(normalized_text(no_comments).encode()).digest()

    # Directives du préprocesseur (lignes commençant par #).
    nc_lines = no_comments.split("\n")
    for index, code_line in enumerate(code.split("\n")):
        match = _DIRECTIVE_RE.match(code_line)
        if match is None:
            continue
        directive = match.group(1)
        value = nc_lines[index][match.start(2) :].strip()
        line = index + 1
        if directive == "property":
            name, _, rest = value.partition(" ")
            name = name.strip()
            rest = rest.strip()
            if not name:
                continue
            literal = _string_literal(rest)
            if literal is None and not rest:
                result.property_flags.add(name)
            elif name == "description" and "description" in result.properties:
                result.properties[name] += "\n" + (literal if literal is not None else rest)
            elif name not in result.properties:
                result.properties[name] = literal if literal is not None else rest
            if name.startswith("indicator_"):
                result.property_flags.add(name)
        elif directive == "include":
            target = value.strip()
            if target.startswith("<") and ">" in target:
                result.includes.append((target[1 : target.index(">")], True, line))
            else:
                literal = _string_literal(target)
                if literal is not None:
                    result.includes.append((literal, False, line))
        elif directive == "import":
            literal = _string_literal(value)
            if literal:
                result.imports.append((literal, line))

    # Paramètres déclarés au niveau global (profondeur d'accolades 0).
    depths = _brace_depths(code)
    ordinal = 0
    for match in _INPUT_START_RE.finditer(code):
        start = match.start()
        if depths[start] != 0:
            continue
        line_start = code.rfind("\n", 0, start) + 1
        if code[line_start:start].strip().startswith("#"):
            continue
        end = code.find(";", match.end())
        if end == -1:
            result.warnings.append(
                f"déclaration « {match.group(1)} » non terminée (ligne "
                f"{code.count(chr(10), 0, start) + 1})"
            )
            continue
        statement = no_comments[match.end() : end].strip()
        if statement.startswith("group"):
            continue  # « input group "Titre" » : séparateur visuel, pas un paramètre
        head = _DECL_HEAD_RE.match(statement)
        line = code.count("\n", 0, start) + 1
        if head is None:
            result.warnings.append(f"paramètre illisible ligne {line}")
            continue
        for declarator in _split_top_level(head.group("rest")):
            decl = _DECLARATOR_RE.match(declarator)
            if decl is None:
                result.warnings.append(f"paramètre illisible ligne {line}")
                continue
            default = decl.group("default")
            ordinal += 1
            result.inputs.append(
                MqlInput(
                    ordinal,
                    decl.group("name"),
                    head.group("type"),
                    " ".join(default.split()) if default else None,
                    match.group(1),
                    line,
                )
            )

    result.entry_points = sorted({m.group(1) for m in _ENTRY_RE.finditer(code)})
    return result


# ---------------------------------------------------------------------------------------
# Empreinte de similarité (« bottom-k MinHash ») sur des fragments de 5 jetons.

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")
SKETCH_SIZE = 128
SHINGLE = 5


def tokens(no_comments: str) -> list[str]:
    return _TOKEN_RE.findall(no_comments)


def shingle_hashes(token_list: list[str], k: int = SHINGLE) -> set[int]:
    if not token_list:
        return set()
    if len(token_list) < k:
        grams = ["\x1f".join(token_list)]
    else:
        grams = ["\x1f".join(token_list[i : i + k]) for i in range(len(token_list) - k + 1)]
    return {
        int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big") for g in grams
    }


def sketch(hashes: set[int], size: int = SKETCH_SIZE) -> bytes:
    """Les ``size`` plus petites valeurs, triées, sur 8 octets chacune."""
    return b"".join(h.to_bytes(8, "big") for h in sorted(hashes)[:size])


def source_text_parts(text: str) -> tuple[str, str]:
    return _neutralize(text)
