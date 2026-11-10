"""F6 — familles et versions : cas imposés par la spécification."""

from __future__ import annotations

from mtlm.matching.families import Family, FamilyInput, build_families

PARAMS = frozenset({"Lots", "TakeProfit", "StopLoss"})


def item(
    file_id: int,
    rel_path: str,
    *,
    content: int,
    ext: str | None = None,
    detected: str = "ea",
    platform: str = "mt4",
    version: str | None = None,
    inputs: frozenset[str] = PARAMS,
    description: str | None = None,
    mtime: int = 0,
) -> FamilyInput:
    ext = ext or rel_path.rsplit(".", 1)[-1]
    return FamilyInput(
        file_id, rel_path, 1, ext, detected, platform, content, version, description, inputs, mtime
    )


def relations(family: Family) -> dict[int, str]:
    return {m.file_id: m.relation for m in family.members}


def only(families: list[Family]) -> Family:
    assert len(families) == 1, families
    return families[0]


def test_copie_identique_renommee() -> None:
    family = only(
        build_families(
            [
                item(1, "MQL4/Experts/Scalper.mq4", content=10),
                item(2, "Copies/MQL4/Experts/Scalper.mq4", content=10),
                item(3, "MQL4/Experts/Scalper - Copie.mq4", content=10),
            ]
        )
    )
    assert relations(family) == {1: "version_variant", 2: "exact_copy", 3: "renamed_copy"}
    assert all(m.confidence == "certain" for m in family.members if m.file_id != 1)


def test_version_dans_le_nom() -> None:
    family = only(
        build_families(
            [
                item(1, "Experts/Scalper_v1.2.mq4", content=10),
                item(2, "Experts/Scalper_v1.3.mq4", content=11),
            ]
        )
    )
    versions = {m.file_id: (m.estimated_version, m.version_basis) for m in family.members}
    assert versions == {1: ("1.2", "nom du fichier"), 2: ("1.3", "nom du fichier")}
    assert set(relations(family).values()) == {"version_variant"}


def test_version_dans_les_metadonnees() -> None:
    family = only(
        build_families(
            [
                item(1, "Experts/Scalper.mq4", content=10, version="2.00"),
                item(2, "Archives/Scalper.mq4", content=11, version="2.10"),
            ]
        )
    )
    assert {m.estimated_version for m in family.members} == {"2.00", "2.10"}
    assert {m.version_basis for m in family.members} == {"#property version"}


def test_meme_nom_contenu_different_homonymes() -> None:
    families = build_families(
        [
            item(1, "A/Grid.mq4", content=10, inputs=frozenset({"Lots", "Grille", "Pas"})),
            item(2, "B/Grid.mq4", content=11, inputs=frozenset({"Rsi", "Periode", "Seuil"})),
        ]
    )
    assert len(families) == 2  # jamais fusionnées
    for family in families:
        assert set(relations(family).values()) == {"homonym_different"}
        assert any("HOMONYMES" in b for b in family.basis)


def test_meme_nom_contenu_different_meme_robot() -> None:
    family = only(
        build_families(
            [
                item(1, "A/Grid.mq4", content=10),
                item(2, "B/Grid.mq4", content=11, inputs=PARAMS | {"Nouveau"}),
            ]
        )
    )
    assert set(relations(family).values()) == {"version_variant"}


def test_compilation_differente() -> None:
    family = only(
        build_families(
            [
                item(1, "Experts/Scalper.mq4", content=10, version="1.5"),
                item(2, "Experts/Scalper.ex4", content=20, detected="ea"),
                item(3, "Vrac/Scalper.ex4", content=21, detected="unknown"),
            ]
        )
    )
    rel = relations(family)
    assert rel == {1: "source_of", 2: "compiled_variant", 3: "compiled_variant"}
    paired = next(m for m in family.members if m.file_id == 2)
    assert (paired.estimated_version, paired.version_basis, paired.confidence) == (
        "1.5",
        "source appariée (supposé)",
        "probable",
    )
    lone = next(m for m in family.members if m.file_id == 3)
    assert lone.confidence == "possible"


def test_plateformes_separees() -> None:
    families = build_families(
        [
            item(1, "MQL4/Experts/Scalper.mq4", content=10, platform="mt4"),
            item(2, "MQL5/Experts/Scalper.mq5", content=11, platform="mt5"),
        ]
    )
    assert len(families) == 2


def test_ordre_suppose_par_date() -> None:
    family = only(
        build_families(
            [
                item(1, "A/Robot.mq4", content=10, mtime=300),
                item(2, "B/Robot.mq4", content=11, mtime=100),
            ]
        )
    )
    by_id = {m.file_id: m for m in family.members}
    assert by_id[2].estimated_version == "n°1" and by_id[1].estimated_version == "n°2"
    assert "supposé" in (by_id[1].version_basis or "")


def test_compiles_seuls_regroupes_par_nom() -> None:
    family = only(
        build_families(
            [
                item(1, "A/Opaque.ex4", content=10, detected="unknown"),
                item(2, "B/Opaque.ex4", content=10, detected="unknown"),
            ]
        )
    )
    assert family.confidence == "possible"
    assert relations(family) == {1: "compiled_variant", 2: "exact_copy"}
