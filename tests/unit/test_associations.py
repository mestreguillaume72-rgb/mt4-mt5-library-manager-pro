"""F5 — moteur d'association : score explicable, règles dures, ambiguïté."""

from __future__ import annotations

from mtlm.matching.associations import (
    RobotInfo,
    SetInfo,
    name_similarity,
    rank_candidates,
    score_pair,
    value_fits_type,
)
from mtlm.matching.names import logical_key, parse_version, version_in_name

INPUTS = {
    "Lots": ("double", "0.1"),
    "TakeProfit": ("int", "50"),
    "StopLoss": ("int", "30"),
    "UseTrailing": ("bool", "false"),
    "Comment": ("string", '"x"'),
}


def robot(
    file_id: int = 1,
    name: str = "Scalper.mq4",
    directory: str = "MQL4/Experts",
    inputs: dict[str, tuple[str, str | None]] | None = None,
    has_source: bool = True,
    platform: str = "mt4",
) -> RobotInfo:
    return RobotInfo(
        file_id,
        name,
        directory,
        1,
        platform,
        file_id,
        has_source,
        INPUTS if inputs is None else inputs,
    )


def set_info(
    params: dict[str, str],
    name: str = "Scalper_EURUSD.set",
    directory: str = "MQL4/Presets",
    fmt: str = "mt4",
) -> SetInfo:
    from mtlm.setfiles.parser import normalize_value

    return SetInfo(
        100, name, directory, 1, fmt, {k: (v, *normalize_value(v)) for k, v in params.items()}
    )


GOOD = {
    "Lots": "0.10",
    "TakeProfit": "50",
    "StopLoss": "30",
    "UseTrailing": "false",
    "Comment": "x",
}


def test_noms_logiques_et_versions() -> None:
    assert logical_key("Scalper_v1.2 - Copie (3).mq4") == "scalper"
    assert logical_key("Élan Pro.ex4") == "elanpro"
    assert version_in_name("Scalper_v1.2.mq4") == "1.2"
    assert version_in_name("Robot v3.mq5") == "3"
    assert version_in_name("Robot.mq5") is None
    assert parse_version("1.10") > parse_version("1.9")  # type: ignore[operator]


def test_association_forte_avec_preuves() -> None:
    candidate = score_pair(robot(), set_info(GOOD))
    assert candidate.level == "forte" and candidate.score >= 90
    kinds = {e.kind: e for e in candidate.evidence}
    assert kinds["couverture_parametres"].polarity == "pour"
    assert kinds["couverture_parametres"].detail["communs"] == 5
    assert kinds["compatibilite_types"].value == 1.0
    assert kinds["plateforme"].polarity == "pour"


def test_parametres_inconnus_penalisent() -> None:
    params = {"Lots": "0.1", "Inconnu1": "1", "Inconnu2": "2", "Inconnu3": "3"}
    candidate = score_pair(robot(), set_info(params))
    assert candidate.level != "forte"
    assert any(
        e.kind == "parametres_inconnus_du_robot" and e.polarity == "contre"
        for e in candidate.evidence
    )


def test_types_incompatibles() -> None:
    params = dict(GOOD, TakeProfit="cinquante", StopLoss="3.5")
    candidate = score_pair(robot(), set_info(params))
    types = next(e for e in candidate.evidence if e.kind == "compatibilite_types")
    assert types.value == 3 / 5 and types.polarity == "contre"


def test_robot_sans_source_plafonne_a_verifier() -> None:
    compiled = robot(name="Scalper.ex4", inputs={}, has_source=False)
    candidate = score_pair(compiled, set_info(GOOD))
    assert candidate.level == "a_verifier"
    assert any(e.polarity == "incertitude" for e in candidate.evidence)


def test_plateforme_contradictoire() -> None:
    candidate = score_pair(robot(platform="mt5"), set_info(GOOD, fmt="mt4"))
    assert next(e for e in candidate.evidence if e.kind == "plateforme").polarity == "contre"


def test_sans_rapport_non_propose() -> None:
    unrelated = robot(name="Autre.mq4", directory="Ailleurs", inputs={"X": ("int", "1")})
    assert score_pair(unrelated, set_info(GOOD)).level == "none"
    assert rank_candidates(set_info(GOOD), [unrelated]) == []


def test_ambiguite_deux_robots_distincts() -> None:
    twin = robot(file_id=2, name="Scalpel.mq4")  # autre robot, mêmes paramètres
    ranked = rank_candidates(set_info(GOOD, name="Scalp.set", directory="Presets"), [robot(), twin])
    assert len(ranked) == 2
    assert all(c.level in ("moyenne", "faible") for c in ranked)
    assert all(any(e.kind == "ambiguite" for e in c.evidence) for c in ranked)


def test_copies_du_meme_robot_ne_sont_pas_une_ambiguite() -> None:
    copy = robot(file_id=2, name="Scalper - Copie.mq4", directory="Copies/MQL4/Experts")
    ranked = rank_candidates(set_info(GOOD), [robot(), copy])
    assert ranked[0].level == "forte"
    assert not any(e.kind == "ambiguite" for e in ranked[0].evidence)


def test_compatibilite_valeurs() -> None:
    assert value_fits_type("int", "5", "5") and not value_fits_type("int", "5.5", "5.5")
    assert value_fits_type("ENUM_TIMEFRAMES", "16385", "16385")
    assert value_fits_type("double", "0,5", "0.5")
    assert value_fits_type("bool", "1", "1") and not value_fits_type("bool", "oui", "oui")
    assert value_fits_type("string", "n'importe", None)


def test_similarite_noms() -> None:
    assert name_similarity("Scalper.mq4", "Scalper_EURUSD_M15.set") == 1.0
    assert name_similarity("Scalper.mq4", "Mon Scalper agressif.set") == 0.85
    assert name_similarity("Scalper.mq4", "Grid.set") < 0.5
