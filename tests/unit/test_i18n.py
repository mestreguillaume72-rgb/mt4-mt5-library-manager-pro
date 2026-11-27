"""1.9.0 — langues : chaque texte de l'application a sa traduction anglaise et espagnole,
avec les mêmes valeurs à insérer ; le français reste la langue d'origine."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from mtlm.core.i18n import LANGUAGES, best_language, catalog, language, set_language, tr

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "src" / "mtlm" / "core" / "locales"
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
TAG = re.compile(r"</?[a-z]+>")


def _extractor() -> Any:
    spec = importlib.util.spec_from_file_location("i18n_extract", ROOT / "tools/i18n_extract.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_liste_des_textes_a_jour() -> None:
    """« textes.json » correspond au code : relancer tools/i18n_extract.py sinon."""
    listed = json.loads((LOCALES / "textes.json").read_text(encoding="utf-8"))
    assert listed == _extractor().all_texts()


@pytest.mark.parametrize("code", ["en", "es"])
def test_chaque_texte_est_traduit(code: str) -> None:
    texts = json.loads((LOCALES / "textes.json").read_text(encoding="utf-8"))
    translations = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    missing = [t for t in texts if not translations.get(t, "").strip()]
    assert missing == [], f"{len(missing)} texte(s) sans traduction : {missing[:5]}"
    for source, target in translations.items():
        assert sorted(PLACEHOLDER.findall(source)) == sorted(PLACEHOLDER.findall(target)), source
        assert sorted(TAG.findall(source)) == sorted(TAG.findall(target)), source
        assert source.startswith(" ") == target.startswith(" "), source


def test_tr_langue_et_valeurs() -> None:
    assert language() == "fr"
    assert tr("{n} robot(s)", n=3) == "3 robot(s)"
    set_language("en")
    assert tr("{n} indicateur(s)", n=2) == "2 indicator(s)"
    assert tr("texte inconnu {x}", x=1) == "texte inconnu 1"  # jamais vide
    set_language("es")
    assert tr("Corbeille") == catalog("es")["Corbeille"]
    set_language("xx")
    assert language() == "fr"


def test_langue_proposee_au_premier_lancement() -> None:
    assert best_language("es_ES") == "es"
    assert best_language("fr_CA") == "fr"
    assert best_language("de_DE") == "en"
    assert set(LANGUAGES) == {"fr", "en", "es"}
