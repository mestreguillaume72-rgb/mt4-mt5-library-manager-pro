"""1.4.0 — interface : sélection multiple et actions groupées, filtre par type d'outil,
onglet Dépendances, avertissement avant de supprimer un fichier utilisé par un autre."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mtlm.ui.window import MainWindow
from tests.integration.test_dependencies import build as build_dependencies
from tests.integration.test_trash import FakeTrash
from tests.ui.conftest import FakeDialogs
from tests.ui.test_ui import build_library, click, wait_idle


def analysed(window: MainWindow, qtbot: object, dialogs: FakeDialogs, lib: Path) -> None:
    dialogs.directories.append(lib)
    click(window, qtbot, "tableau.ajouter")
    click(window, qtbot, "tableau.analyser")
    wait_idle(window, qtbot)


def test_doublons_plusieurs_groupes_d_un_coup(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_library(lib)
    (lib / "Copies" / "Scalper.ex4").write_bytes(bytes(range(256)))  # 2e groupe de doublons
    analysed(window, qtbot, dialogs, lib)
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("doublons")
    page: Any = window.pages["doublons"]
    page.refresh()
    assert page.groups.rowCount() == 2
    click(window, qtbot, "doublons.tout_groupes")
    assert len(page.groups.selectionModel().selectedRows()) == 2
    assert page.members.rowCount() == 4  # membres des deux groupes listés ensemble
    dialogs.confirm_answer = True
    before = len(dialogs.confirms)
    click(window, qtbot, "doublons.corbeille_groupe")
    wait_idle(window, qtbot)
    assert len(dialogs.confirms) == before + 1  # une seule confirmation
    assert "2 groupe(s) choisi(s)" in dialogs.confirms[-1]
    assert "2 fichier(s) mis à la Corbeille" in dialogs.infos[-1][1]
    assert not (lib / "Copies" / "Scalper.mq4").exists()
    assert not (lib / "Copies" / "Scalper.ex4").exists()
    assert (lib / "MQL4" / "Experts" / "Scalper.mq4").exists()
    # Remise en place groupée.
    window.navigate("quarantaine")
    quarantine: Any = window.pages["quarantaine"]
    quarantine.refresh()
    click(window, qtbot, "quarantaine.tout_corbeille")
    click(window, qtbot, "quarantaine.remettre")
    assert "2 fichier(s) remis" in dialogs.infos[-1][1]
    assert (lib / "Copies" / "Scalper.mq4").exists() and (lib / "Copies" / "Scalper.ex4").exists()


def test_accepter_la_meilleure_proposition_de_plusieurs_set(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_library(lib)
    (lib / "MQL4" / "Presets" / "Scalper_GBPUSD.set").write_text(
        "Lots=0.3\nTP=45\n", encoding="utf-8"
    )
    analysed(window, qtbot, dialogs, lib)
    window.navigate("sets")
    page: Any = window.pages["sets"]
    page.refresh()
    click(window, qtbot, "sets.tout_sets")
    dialogs.confirm_answer = True
    click(window, qtbot, "sets.accepter_meilleure")
    assert "2 SET" in dialogs.confirms[-1]
    accepted = window.app.ctx.conn.execute(
        "SELECT count(*) FROM association WHERE user_decision = 'accepted'"
    ).fetchone()[0]
    assert accepted == 2


def test_familles_type_dependances_et_avertissement(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_dependencies(lib)
    analysed(window, qtbot, dialogs, lib)
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("familles")
    page: Any = window.pages["familles"]
    page.refresh()
    # Filtre « Indicateurs » : seule la famille SuperTrend.
    index = page.tool_type.findData("indicator")
    page.tool_type.setCurrentIndex(index)
    assert [page.families.item(r, 1).text() for r in range(page.families.rowCount())] == [
        "SuperTrend"
    ]
    assert page.families.item(0, 6).text() == "Indicateur"
    page.tool_type.setCurrentIndex(0)
    for row in range(page.families.rowCount()):
        if page.families.item(row, 1).text() == "Gold Robot":
            page.families.selectRow(row)
    assert page.deps.rowCount() >= 3  # SuperTrend (mq4, ex4) et MathLib.ex4
    # Supprimer l'indicateur utilisé : avertissement nominatif, puis refus de l'utilisateur.
    page.tool_type.setCurrentIndex(index)
    page.families.selectRow(0)
    click(window, qtbot, "familles.tout_fichiers")
    dialogs.confirm_answer = False
    click(window, qtbot, "familles.corbeille")
    assert "ATTENTION" in dialogs.confirms[-1] and "Gold Robot.mq4" in dialogs.confirms[-1]
    assert (lib / "MQL4" / "Indicators" / "SuperTrend.ex4").exists()
