"""F4 — classement avec certitude et limites : cas imposés (MT4/MT5 fictifs, fichiers
renommés, extension trompeuse, binaire inconnu)."""

from __future__ import annotations

import pytest

from mtlm.metatrader.classify import COMPILED_LIMIT, classify, folder_hints
from mtlm.metatrader.mql import parse_mql


def test_indices_de_dossier() -> None:
    assert folder_hints("MQL4/Experts/Groupe/Robot.mq4") == ("ea", "mt4")
    assert folder_hints("MQL5/Indicators/x.ex5") == ("indicator", "mt5")
    assert folder_hints("Vrac/x.ex4") == (None, None)


@pytest.mark.parametrize(
    "code, ext, path, expected_type, certainty",
    [
        ("void OnTick(){}", "mq5", "MQL5/Experts/a.mq5", "ea", "certain"),
        ("void OnStart(){}", "mq4", "MQL4/Scripts/a.mq4", "script", "certain"),
        ("int OnCalculate(){return 0;}", "mq5", "Vrac/a.mq5", "indicator", "certain"),
        ("#property service\nvoid OnStart(){}", "mq5", "MQL5/Services/a.mq5", "service", "certain"),
        (
            "#property library\nint f(){return 0;}",
            "mq4",
            "MQL4/Libraries/a.mq4",
            "library",
            "certain",
        ),
        ("int start(){return 0;}", "mq4", "MQL4/Experts/a.mq4", "ea", "certain"),
        ("int start(){return 0;}", "mq4", "Vrac/a.mq4", "unknown", "unknown"),
        ("void OnTick(){}", "mq4", "MQL4/Indicators/a.mq4", "ea", "probable"),  # mal rangé
        ("int x;", "mq4", "MQL4/Experts/a.mq4", "ea", "possible"),  # aucun indice : dossier
        ("#define A 1", "mqh", "MQL4/Include/a.mqh", "include", "certain"),
    ],
)
def test_sources(code: str, ext: str, path: str, expected_type: str, certainty: str) -> None:
    result = classify(
        ext=ext, rel_path=path, signature="text", misleading=False, source=parse_mql(code)
    )
    assert (result.detected_type, result.certainty) == (expected_type, certainty)
    assert result.platform == {"mq4": "mt4", "mq5": "mt5"}.get(ext, result.platform)
    assert result.basis


def test_binaire_compile_opaque() -> None:
    by_folder = classify(
        ext="ex4", rel_path="MQL4/Experts/R.ex4", signature="binary", misleading=False
    )
    assert (by_folder.detected_type, by_folder.certainty) == ("ea", "probable")
    assert by_folder.limits == COMPILED_LIMIT
    paired = classify(
        ext="ex5",
        rel_path="Vrac/R.ex5",
        signature="binary",
        misleading=False,
        paired_source_type="indicator",
    )
    assert (paired.detected_type, paired.certainty) == ("indicator", "probable")
    assert any("non vérifié" in b for b in paired.basis)
    nothing = classify(ext="ex4", rel_path="Vrac/R.ex4", signature="binary", misleading=False)
    assert (nothing.detected_type, nothing.certainty) == ("unknown", "unknown")


def test_extension_trompeuse() -> None:
    fake_source = classify(
        ext="mq4", rel_path="MQL4/Experts/x.mq4", signature="pe", misleading=True
    )
    assert fake_source.detected_type == "unknown"
    assert any("TROMPEUSE" in b for b in fake_source.basis)
    fake_compiled = classify(
        ext="ex4", rel_path="MQL4/Experts/x.ex4", signature="text", misleading=True
    )
    assert (fake_compiled.detected_type, fake_compiled.certainty) == ("unknown", "possible")


def test_fichier_renomme_garde_son_contenu() -> None:
    """Un EA renommé « indicateur.mq5 » reste un EA d'après son contenu."""
    result = classify(
        ext="mq5",
        rel_path="Vrac/indicateur.mq5",
        signature="text",
        misleading=False,
        source=parse_mql("void OnTick(){}"),
    )
    assert result.detected_type == "ea"


@pytest.mark.parametrize(
    "ext, signature, expected",
    [
        ("set", "text", "set"),
        ("dll", "pe", "dll"),
        ("tpl", "text", "template"),
        ("csv", "text", "resource"),
        ("png", "png", "resource"),
        ("xyz", "binary", "unknown"),
        ("", "binary", "unknown"),
        ("bin", "pe", "dll"),
    ],
)
def test_autres_fichiers(ext: str, signature: str, expected: str) -> None:
    result = classify(
        ext=ext, rel_path=f"MQL4/Files/a.{ext}", signature=signature, misleading=False
    )
    assert result.detected_type == expected
    if expected == "unknown":
        assert result.limits and "périmètre ALL" in result.limits
    if expected == "dll":
        assert result.limits and "jamais chargée" in result.limits
