"""F4 — encodages et analyse lexicale des sources MQL fictives."""

from __future__ import annotations

import pytest

from mtlm.metatrader.encoding import decode_text
from mtlm.metatrader.mql import parse_mql, shingle_hashes, sketch, source_text_parts, tokens

EA_MT4 = """//+------------------------------------------------------------------+
//| Robot FICTIF                                                     |
//+------------------------------------------------------------------+
#property copyright "Exemple fictif — données de test"
#property link      "https://exemple.invalid"
#property version   "1.07"
#property description "Première ligne"
#property description "Deuxième ligne // pas un commentaire"
#property strict
#include <stdlib.mqh>
#include "MesOutils.mqh"
#import "user32.dll"
   int MessageBoxW(int, string, string, int);
#import
/* input int Faux = 99;  (commentaire : pas un paramètre) */
// extern double FauxAussi = 1;
extern double Lots = 0.10;      // taille
extern int    TakeProfit = 50, StopLoss = 30;
input  string Commentaire = "Robot; avec point-virgule";
sinput bool   Debug = false;
input group "Gestion du risque"
input ENUM_TIMEFRAMES Periode = PERIOD_H1;
input color   Couleur = clrRed;
int start()
  {
   string s = "input int PasUnParametre = 1;";
   return(0);
  }
"""

EA_MT5 = """#property copyright "Fictif"
#property version "2.00"
input int MagicNumber = 12345;
input double Risque = 1.5;
int OnInit() { return(INIT_SUCCEEDED); }
void OnTick()
  {
   int local_input = 3;   // pas global
  }
"""


def test_proprietes_includes_imports() -> None:
    src = parse_mql(EA_MT4)
    assert src.properties["copyright"] == "Exemple fictif — données de test"
    assert src.properties["version"] == "1.07"
    assert src.properties["description"] == ("Première ligne\nDeuxième ligne // pas un commentaire")
    assert "strict" in src.property_flags
    assert [(t, system) for t, system, _ in src.includes] == [
        ("stdlib.mqh", True),
        ("MesOutils.mqh", False),
    ]
    assert [m for m, _ in src.imports] == ["user32.dll"]


def test_parametres_declares_seulement() -> None:
    src = parse_mql(EA_MT4)
    names = [(i.modifier, i.mql_type, i.name, i.default_raw) for i in src.inputs]
    assert names == [
        ("extern", "double", "Lots", "0.10"),
        ("extern", "int", "TakeProfit", "50"),
        ("extern", "int", "StopLoss", "30"),
        ("input", "string", "Commentaire", '"Robot; avec point-virgule"'),
        ("sinput", "bool", "Debug", "false"),
        ("input", "ENUM_TIMEFRAMES", "Periode", "PERIOD_H1"),
        ("input", "color", "Couleur", "clrRed"),
    ]
    assert src.inputs[0].line == 17
    assert "start" in src.entry_points


def test_mt5_fonctions_d_entree() -> None:
    src = parse_mql(EA_MT5)
    assert src.entry_points == ["OnInit", "OnTick"]
    assert [i.name for i in src.inputs] == ["MagicNumber", "Risque"]


def test_indicateur_et_bibliotheque() -> None:
    ind = parse_mql(
        "#property indicator_chart_window\n#property indicator_buffers 2\n"
        "int OnCalculate(const int rates_total) { return(rates_total); }\n"
    )
    assert ind.is_indicator and "OnCalculate" in ind.entry_points
    lib = parse_mql("#property library\nint Ajouter(int a, int b) export { return a+b; }\n")
    assert "library" in lib.property_flags


def test_normalisation_ignore_commentaires_et_espaces() -> None:
    a = parse_mql("input int X = 1;\nvoid OnTick() { }\n")
    b = parse_mql("// en-tête\r\ninput  int X =   1;   /* c */\r\n\r\nvoid OnTick()\n{\n}\n")
    c = parse_mql("input int X = 2;\nvoid OnTick() { }\n")
    assert a.normalized_sha256 == b.normalized_sha256 != c.normalized_sha256


def test_declaration_non_terminee_signalee() -> None:
    src = parse_mql("input int X = 1")
    assert src.inputs == [] and src.warnings


@pytest.mark.parametrize(
    "garbage",
    [
        b"\x00\xff" * 500,
        '{{{{ ((( "non fermé'.encode(),
        b"/* jamais ferme",
        b"#property",
        b"#include",
        b"input ;",
        b"input group",
        "é".encode("cp1252") * 2000,
    ],
)
def test_entrees_malformees_sans_plantage(garbage: bytes) -> None:
    parse_mql(decode_text(garbage).text)


@pytest.mark.parametrize(
    "data, encoding, confidence",
    [
        (b"\xff\xfe" + "input int É=1;".encode("utf-16-le"), "utf-16-le-bom", 1.0),
        (b"\xfe\xff" + "input".encode("utf-16-be"), "utf-16-be-bom", 1.0),
        ("input int X=1;".encode("utf-16-le"), "utf-16-le", 0.8),
        (b"\xef\xbb\xbf#property", "utf-8-bom", 1.0),
        ("// Été".encode(), "utf-8", 0.9),
        (b"input int X;", "ascii", 1.0),
        ("// Été".encode("cp1252"), "cp1252", 0.6),
        (b"\x81\x8d\x8f", "latin-1", 0.3),
    ],
)
def test_encodages(data: bytes, encoding: str, confidence: float) -> None:
    decoded = decode_text(data)
    assert (decoded.encoding, decoded.confidence) == (encoding, confidence)


def test_encodage_mt5_utf16_puis_analyse() -> None:
    data = b"\xff\xfe" + EA_MT5.encode("utf-16-le")
    assert [i.name for i in parse_mql(decode_text(data).text).inputs] == ["MagicNumber", "Risque"]


def test_esquisse_similarite() -> None:
    nc, _ = source_text_parts(EA_MT5)
    first = shingle_hashes(tokens(nc))
    nc2, _ = source_text_parts(EA_MT5.replace("1.5", "2.5"))
    second = shingle_hashes(tokens(nc2))
    jaccard = len(first & second) / len(first | second)
    assert 0.7 < jaccard < 1.0
    assert len(sketch(first)) == 8 * min(128, len(first))
    assert shingle_hashes([]) == set() and len(shingle_hashes(["a", "b"])) == 1
