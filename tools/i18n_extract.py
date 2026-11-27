"""Outil de développement (1.9.0) : liste tous les textes français à traduire.

Utilisation : python tools/i18n_extract.py  → écrit ``src/mtlm/core/locales/textes.json``
(liste triée). Sources : les appels ``tr("…")`` du code, et les libellés définis une fois
(titres d'écran, bulles, paramètres, étapes, libellés de types et de placements…).
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "mtlm"


def literal_texts() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("tr", "N_")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.add(node.args[0].value)
    return found


def registry_texts() -> set[str]:
    sys.path.insert(0, str(ROOT / "src"))
    from mtlm.app import archives, companions, families, pipeline, presenters, reports, risk, sets
    from mtlm.app.settings import SPECS
    from mtlm.ui import bulles, main, window
    from mtlm.ui.pages_isolated import IndicatorsPage, RobotsPage

    found: set[str] = set()

    def add(values: object) -> None:
        if isinstance(values, dict):
            values = values.values()
        for value in values:  # type: ignore[attr-defined]
            if isinstance(value, str) and value.strip():
                found.add(value)

    add(bulles.ACTION_TIPS)
    add(bulles.WIDGET_TIPS)
    for spec in SPECS.values():
        add([spec.label, spec.help])
    add([step.label for step in pipeline.STEPS])
    add([spec.label for spec in reports.KINDS.values()])
    add([section for section, _keys in window.SECTIONS])
    for page in main.PAGES:
        add([page.title, getattr(page, "subtitle", "")])
    for page in (RobotsPage, IndicatorsPage):
        add([page.singular, page.plural])
    for module in (sets, companions, families, presenters, risk, archives):
        for name in dir(module):
            value = getattr(module, name)
            if (
                name.isupper()
                and name.endswith(("LABELS", "DECISIONS", "TYPES"))
                and isinstance(value, dict)
            ):
                add(value)
    add([f"{v}s" if not v.endswith("s") else v for v in families.TYPE_LABELS.values()])
    from mtlm.app import organize

    add(organize.BASIS_TEXTS)
    add(organize.BASIS_PREFIXES)
    nouns = {"élément", "sélectionné"}
    for path in (SRC / "ui").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "noun"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                nouns.add(node.value.value)
    for noun in nouns:
        add([noun, noun if noun.endswith(("s", "x")) else noun + "s"])
    from mtlm.metatrader import risk as mt_risk

    add([why for _level, why in mt_risk.DANGEROUS_FUNCTIONS.values()])
    add([why for _level, why in mt_risk.SENSITIVE_DLLS.values()])
    add(mt_risk.MQL_INFO)
    add(mt_risk.EXECUTABLE_EXTS)
    return found


def all_texts() -> list[str]:
    return sorted(literal_texts() | registry_texts())


def main() -> int:
    texts = all_texts()
    target = SRC / "core" / "locales" / "textes.json"
    target.write_text(json.dumps(texts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(texts)} textes → {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
