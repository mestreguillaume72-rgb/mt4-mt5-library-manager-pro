"""Modèles de graphique MetaTrader (``.tpl``) : quels robots et indicateurs ils chargent.

Un modèle est un fichier texte (souvent UTF-16 sous MT5) structuré en blocs ``<expert>``,
``<indicator>`` et ``<ind>`` (MT4), chacun avec ``name=`` et souvent ``path=``
(« Indicators\\SuperTrend.ex4 »). On en tire uniquement les **noms** des outils chargés, en
lecture seule ; les indicateurs intégrés à MetaTrader (Moving Average…) ne correspondent à
aucun fichier et sont simplement ignorés ensuite. Aucun contenu n'est exécuté.
"""

from __future__ import annotations

from dataclasses import dataclass

_BLOCKS = {"expert": "robot", "indicator": "indicateur", "ind": "indicateur"}
_GENERIC = {"custom indicator", "custom", "main", ""}


@dataclass(frozen=True)
class TemplateTool:
    kind: str  # « robot » ou « indicateur »
    name: str  # nom du fichier sans extension


def _stem(value: str) -> str:
    name = value.replace("\\", "/").rstrip("/").rpartition("/")[2].strip()
    stem, dot, ext = name.rpartition(".")
    if dot and ext.casefold() in ("ex4", "ex5", "mq4", "mq5"):
        return stem
    return name


def parse_template(text: str) -> list[TemplateTool]:
    tools: list[TemplateTool] = []
    seen: set[tuple[str, str]] = set()
    stack: list[dict[str, str]] = []
    kinds: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("</") and line.endswith(">"):
            if kinds and line[2:-1].strip().casefold() == kinds[-1]:
                block, values = kinds.pop(), stack.pop()
                name = values.get("path") or values.get("name", "")
                stem = _stem(name)
                if stem.casefold() in _GENERIC and values.get("name"):
                    stem = _stem(values["name"])
                ident = (_BLOCKS[block], stem.casefold())
                if stem.casefold() not in _GENERIC and ident not in seen:
                    seen.add(ident)
                    tools.append(TemplateTool(_BLOCKS[block], stem))
            continue
        if line.startswith("<") and line.endswith(">") and not line.startswith("</"):
            tag = line[1:-1].strip().casefold()
            if tag in _BLOCKS:
                kinds.append(tag)
                stack.append({})
            continue
        if stack and "=" in line:
            field, _, value = line.partition("=")
            field = field.strip().casefold()
            if field in ("name", "path") and field not in stack[-1]:
                stack[-1][field] = value.strip()
    return tools
