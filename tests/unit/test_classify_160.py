"""1.6.0 — MQL4 ancien (start()) : le code dit si c'est un robot ou un indicateur."""

from __future__ import annotations

from mtlm.metatrader.classify import classify
from mtlm.metatrader.mql import parse_mql


def kind(code: str, rel_path: str = "Telechargements/x.mq4") -> tuple[str, str]:
    result = classify(
        ext="mq4", rel_path=rel_path, signature=None, misleading=False, source=parse_mql(code)
    )
    return result.detected_type, result.certainty


def test_indicateur_reconnu_par_ses_tampons_hors_dossier() -> None:
    code = "int init(){IndicatorBuffers(1);SetIndexBuffer(0,B);return 0;}\nint start(){return 0;}"
    assert kind(code) == ("indicator", "certain")


def test_robot_reconnu_par_ses_ordres_hors_dossier() -> None:
    assert kind("int start(){OrderSend(Symbol(),0,1,Ask,3,0,0);return 0;}") == ("ea", "certain")


def test_contradiction_avec_le_dossier_signalee() -> None:
    code = "int start(){SetIndexBuffer(0,B);return 0;}"
    assert kind(code, "MQL4/Experts/x.mq4") == ("indicator", "probable")


def test_commentaires_et_chaines_ignores() -> None:
    code = '// OrderSend\nstring s = "SetIndexBuffer";\nint start(){return 0;}'
    assert kind(code) == ("unknown", "unknown")


def test_les_deux_ou_aucun_indice_laisse_le_dossier_trancher() -> None:
    code = "int start(){OrderSend(1);SetIndexBuffer(0,B);return 0;}"
    assert kind(code, "MQL4/Experts/x.mq4") == ("ea", "certain")
