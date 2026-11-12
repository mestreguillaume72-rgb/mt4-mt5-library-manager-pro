"""1.3.0 — interface : placement des SET, Corbeille (Doublons, Familles, Quarantaine),
remise en place, propositions de dossiers. Corbeille de test (un dossier) hors macOS."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mtlm.ui.window import MainWindow
from tests.integration.test_trash import FakeTrash
from tests.ui.conftest import FakeDialogs
from tests.ui.test_ui import build_library, click, wait_idle


def analysed(window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path) -> Path:
    lib = tmp_path / "lib"
    build_library(lib)
    dialogs.directories.append(lib)
    click(window, qtbot, "tableau.ajouter")
    click(window, qtbot, "tableau.analyser")
    wait_idle(window, qtbot)
    return lib


def test_placement_affiche_et_filtre(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    analysed(window, qtbot, dialogs, tmp_path)
    window.navigate("sets")
    page: Any = window.pages["sets"]
    page.refresh()
    assert page.sets.rowCount() == 1
    # Le SET est dans « Presets », sans robot : en vrac, mais son robot a été retrouvé.
    assert page.sets.item(0, 5).text() == "En vrac — correspondance trouvée"
    page.placement.setCurrentIndex(1)  # « Rangé avec son robot »
    assert page.sets.rowCount() == 0
    page.placement.setCurrentIndex(2)
    assert page.sets.rowCount() == 1
    window.navigate("tableau")
    assert "en vrac dont le robot a été retrouvé" in window.pages["tableau"].summary.text()


def test_corbeille_doublons_puis_remise_en_place(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = analysed(window, qtbot, dialogs, tmp_path)
    copy = lib / "Copies" / "Scalper.mq4"
    reference = lib / "MQL4" / "Experts" / "Scalper.mq4"
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("doublons")
    page: Any = window.pages["doublons"]
    page.refresh()
    page.groups.selectRow(0)
    dialogs.confirm_answer = False
    click(window, qtbot, "doublons.corbeille_groupe")
    assert copy.exists() and "Corbeille" in dialogs.confirms[-1]
    dialogs.confirm_answer = True
    click(window, qtbot, "doublons.corbeille_groupe")
    wait_idle(window, qtbot)
    assert not copy.exists() and reference.exists()
    assert "1 fichier(s) mis à la Corbeille" in dialogs.infos[-1][1]
    # Historique et remise en place depuis l'écran Quarantaine.
    window.navigate("quarantaine")
    quarantine: Any = window.pages["quarantaine"]
    quarantine.refresh()
    assert quarantine.trashed.rowCount() == 1
    assert quarantine.trashed.item(0, 4).text() == "à la Corbeille"
    quarantine.trashed.selectRow(0)
    click(window, qtbot, "quarantaine.remettre")
    assert copy.exists()
    assert quarantine.trashed.item(0, 4).text() == "remis en place"


def test_corbeille_indisponible_hors_mac(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = analysed(window, qtbot, dialogs, tmp_path)
    window.app.ctx.trash = None
    window.navigate("doublons")
    page: Any = window.pages["doublons"]
    page.refresh()
    page.groups.selectRow(0)
    click(window, qtbot, "doublons.corbeille_groupe")
    assert "que sur Mac" in dialogs.infos[-1][1]
    assert (lib / "Copies" / "Scalper.mq4").exists()


def test_reference_protegee_et_version_unique_signalee(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = analysed(window, qtbot, dialogs, tmp_path)
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("doublons")
    page: Any = window.pages["doublons"]
    page.refresh()
    page.groups.selectRow(0)
    reference = page.groups.item(0, 4).text()
    for row in range(page.members.rowCount()):
        if page.members.item(row, 0).text() == reference:
            page.members.selectRow(row)
    click(window, qtbot, "doublons.corbeille_fichier")
    assert "RÉFÉRENCE" in dialogs.infos[-1][1]
    # Familles : le fichier compilé est un exemplaire unique, signalé avant confirmation.
    window.navigate("familles")
    families: Any = window.pages["familles"]
    families.refresh()
    families.families.selectRow(0)
    for row in range(families.members.rowCount()):
        if families.members.item(row, 4).text().endswith(".ex4"):
            families.members.selectRow(row)
    dialogs.confirm_answer = False
    click(window, qtbot, "familles.corbeille")
    assert "SEUL exemplaire" in dialogs.confirms[-1]
    assert (lib / "MQL4" / "Experts" / "Scalper.ex4").exists()


def test_propositions_de_dossiers_validees(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    analysed(window, qtbot, dialogs, tmp_path)
    dest = tmp_path / "Dest"
    dest.mkdir()
    window.navigate("familles")
    families: Any = window.pages["familles"]
    families.refresh()
    families.families.selectRow(0)
    name = families.families.item(0, 1).text()
    # Proposition refusée : rien n'est copié.
    dialogs.directories.append(dest)
    dialogs.confirm_answer = False
    click(window, qtbot, "familles.dossier")
    assert "PROPOSITION" in dialogs.confirms[-1]
    assert list(dest.iterdir()) == []
    # Proposition validée : dossier au nom du robot.
    dialogs.directories.append(dest)
    dialogs.confirm_answer = True
    click(window, qtbot, "familles.dossier")
    wait_idle(window, qtbot)
    assert (dest / name).is_dir()
    assert "copié(s) et vérifié(s)" in dialogs.infos[-1][1]
    dialogs.directories.append(dest)
    window.navigate("organisation")
    click(window, qtbot, "organisation.isoler")
    wait_idle(window, qtbot)
    isolated = [p for p in dest.iterdir() if p.name.startswith("Sources MQ4-MQ5")]
    assert len(isolated) == 1
    assert list(isolated[0].rglob("*.set")) and list(isolated[0].rglob("*.mq4"))


def test_bulles_d_aide_partout(window: MainWindow) -> None:
    """1.3.0 : chaque bouton a une vraie bulle d'aide en français (pas seulement son libellé),
    chaque bulle de zone désigne un élément existant, chaque écran du menu a la sienne."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    from mtlm.ui.bulles import ACTION_TIPS, WIDGET_TIPS

    registry = window.app.registry
    missing = [k for k in registry.specs if k not in ACTION_TIPS]
    assert missing == []
    assert set(ACTION_TIPS) <= set(registry.specs), set(ACTION_TIPS) - set(registry.specs)
    for action_id, spec in registry.specs.items():
        button = window.findChild(QPushButton, action_id)
        assert button is not None
        assert button.toolTip() == ACTION_TIPS[action_id] != spec.label
    for (key, attribute), text in WIDGET_TIPS.items():
        widget = getattr(window.pages[key], attribute)
        assert widget.toolTip() == text, (key, attribute)
    for row in range(window.sidebar.count()):
        item = window.sidebar.item(row)
        if item.data(Qt.ItemDataRole.UserRole) is not None:
            assert item.toolTip()
