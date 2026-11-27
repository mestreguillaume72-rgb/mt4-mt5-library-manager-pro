"""Langue de l'interface (1.9.0) : français (langue d'origine), anglais, espagnol.

* ``tr(texte, **valeurs)`` : le texte français sert de clé ; sa traduction est cherchée dans
  le catalogue de la langue choisie (``locales/en.json``, ``locales/es.json``), puis les
  valeurs sont insérées (``{n}``, ``{nom}``…). Texte absent du catalogue : le français est
  affiché (jamais de texte vide).
* La langue se change dans Paramètres ; l'interface est reconstruite aussitôt.
* Les noms de fichiers, de dossiers et de paramètres des SET ne sont jamais traduits.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

LANGUAGES = {"fr": "Français", "en": "English", "es": "Español"}
DEFAULT = "fr"
_LOCALES = Path(__file__).with_name("locales")
_current = DEFAULT


@cache
def catalog(code: str) -> dict[str, str]:
    """Traductions d'une langue (texte français → texte traduit)."""
    if code == DEFAULT:
        return {}
    path = _LOCALES / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def set_language(code: str) -> str:
    """Choisit la langue (code inconnu : français). Retourne la langue retenue."""
    global _current
    _current = code if code in LANGUAGES else DEFAULT
    return _current


def language() -> str:
    return _current


def tr(text: str, /, **values: object) -> str:
    """Texte dans la langue choisie, avec ses valeurs insérées."""
    translated = catalog(_current).get(text, text) if _current != DEFAULT else text
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):
        return text.format(**values)  # traduction abîmée : le français, jamais d'erreur


def best_language(system_name: str) -> str:
    """Langue proposée au premier lancement d'après celle de l'ordinateur (« es_ES »…)."""
    code = system_name.replace("-", "_").split("_")[0].lower()
    return code if code in LANGUAGES else ("en" if code else DEFAULT)
