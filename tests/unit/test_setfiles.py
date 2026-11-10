"""F5 — lecteur SET : cas imposés (vide, mal formé, encodages, doublons de clés, paramètres
inconnus, variantes MT4/MT5, SET presque identiques)."""

from __future__ import annotations

import pytest

from mtlm.metatrader.encoding import decode_text
from mtlm.setfiles.parser import compare_sets, normalize_value, parse_set

MT4_SET = """Lots=0.10
Lots,F=0
Lots,1=0.01
Lots,2=0.01
Lots,3=1.00
TakeProfit=50
TakeProfit,F=1
TakeProfit,1=10
TakeProfit,2=5
TakeProfit,3=100
UseTrailing=1
Comment=Robot Été
"""

MT5_SET = """; saved automatically on 2026.01.01 10:00:00
; this file contains input parameters for testing/optimizing Robot expert advisor
MagicNumber=12345||12345||1||123450||N
Risque=1.5||0.5||0.5||3.0||Y
Actif=true||false||0||true||N
Debut=2024.01.01 00:00||0||0||0||N
"""


def test_mt4_et_optimisation() -> None:
    doc = parse_set(MT4_SET)
    assert doc.format == "mt4" and "MT4" in doc.format_basis
    params = doc.by_name()
    assert [p.name for p in doc.params] == ["Lots", "TakeProfit", "UseTrailing", "Comment"]
    lots = params["Lots"]
    assert (lots.raw_value, lots.normalized_value, lots.estimated_type) == ("0.10", "0.1", "double")
    assert (lots.opt_start, lots.opt_step, lots.opt_stop, lots.opt_enabled) == (
        "0.01",
        "0.01",
        "1.00",
        False,
    )
    assert params["TakeProfit"].opt_enabled is True
    assert params["UseTrailing"].estimated_type == "int"  # 0/1 : ambigu, gardé en entier
    assert params["Comment"].raw_value == "Robot Été"
    assert doc.warnings == []


def test_mt5_et_commentaires() -> None:
    doc = parse_set(MT5_SET)
    assert doc.format == "mt5" and len(doc.comments) == 2
    params = doc.by_name()
    assert params["Risque"].opt_enabled is True and params["Risque"].opt_stop == "3.0"
    assert params["Actif"].estimated_type == "bool"
    assert params["Debut"].estimated_type == "datetime"
    assert params["MagicNumber"].raw_value == "12345"


def test_set_vide() -> None:
    doc = parse_set("")
    assert doc.params == [] and doc.warnings == ["aucun paramètre trouvé"]
    assert doc.format == "unknown"


def test_set_mal_forme_conserve_et_signale() -> None:
    doc = parse_set("Lots=0.1\nligne sans egal\n=valeur sans nom\nTP=5\n")
    assert [p.name for p in doc.params] == ["Lots", "TP"]
    assert len(doc.warnings) == 2 and "mal formée" in doc.warnings[0]


def test_cles_en_double() -> None:
    doc = parse_set("Lots=0.1\nTP=5\nLots=0.2\n")
    assert doc.duplicate_keys == ["Lots"]
    assert doc.by_name()["Lots"].raw_value == "0.2"  # dernière valeur, comme MetaTrader
    assert len(doc.params) == 3 and any("double" in w for w in doc.warnings)


def test_optimisation_orpheline() -> None:
    doc = parse_set("Lots,F=1\n")
    assert any("absent" in w for w in doc.warnings)


@pytest.mark.parametrize(
    "data, encoding",
    [
        (b"\xff\xfe" + MT5_SET.encode("utf-16-le"), "utf-16-le-bom"),
        (MT4_SET.encode("cp1252"), "cp1252"),
        (MT4_SET.encode("utf-8"), "utf-8"),
        (b"\xef\xbb\xbf" + MT4_SET.encode(), "utf-8-bom"),
    ],
)
def test_encodages(data: bytes, encoding: str) -> None:
    decoded = decode_text(data)
    assert decoded.encoding == encoding
    doc = parse_set(decoded.text, encoding=decoded.encoding)
    assert len(doc.params) == 4


def test_format_indetermine_et_indice_utf16() -> None:
    plain = parse_set("Lots=0.1\n")
    assert plain.format == "unknown"
    hinted = parse_set("Lots=0.1\n", encoding="utf-16-le-bom")
    assert hinted.format == "unknown" and "UTF-16" in hinted.format_basis
    mixed = parse_set("A=1||1||1||2||N\nB,F=0\nB=1\n")
    assert mixed.format == "unknown" and any("mélangés" in w for w in mixed.warnings)


@pytest.mark.parametrize(
    "raw, normalized, kind",
    [
        ("1", "1", "int"),
        ("-5", "-5", "int"),
        ("0.50", "0.5", "double"),
        ("1e-3", "0.001", "double"),
        ("0,5", "0.5", "double"),
        ("TRUE", "true", "bool"),
        ("clrRed", "clrRed", "color"),
        ("C'255,0,0'", "C'255,0,0'", "color"),
        ("D'2024.01.01'", "2024.01.01", "datetime"),
        ("texte libre", "texte libre", "string"),
        ("", "", "string"),
    ],
)
def test_normalisation(raw: str, normalized: str, kind: str) -> None:
    assert normalize_value(raw) == (normalized, kind)


def test_sets_presque_identiques() -> None:
    a = parse_set("Lots=0.10\nTP=50\nSL=30\n")
    b = parse_set("Lots=0.1\nTP=60\nTrailing=1\n")
    diffs = {d.name: d.status for d in compare_sets(a, b)}
    assert diffs == {"Lots": "same", "TP": "different", "SL": "only_left", "Trailing": "only_right"}
    assert a.normalized_sha256 == parse_set("TP=50\nSL=30\nLots=0.1\n").normalized_sha256
