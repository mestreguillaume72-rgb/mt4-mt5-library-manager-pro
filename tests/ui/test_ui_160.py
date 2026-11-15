"""1.6.0 — écrans « Robots isolés » et « Indicateurs isolés » : à part des sources MQ4/MQ5,
groupes de dossiers nommés, un dossier par outil ou un seul grand dossier."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mtlm.ui.window import MainWindow
from tests.integration.test_dependencies import build as build_dependencies
from tests.ui.conftest import FakeDialogs
from tests.ui.test_ui import click, wait_idle
from tests.ui.test_ui_140 import analysed

EXTRA_ROBOT = "extern int X = 1;\nint start(){return 0;}\n"


def _copied(dest: Path) -> set[str]:
    folder = next(dest.iterdir())
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def _row(page: Any, name: str) -> int:
    return next(r for r in range(page.tools.rowCount()) if page.tools.item(r, 1).text() == name)


def test_robots_isoles_groupes_et_dossier_par_robot(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_dependencies(lib)
    (lib / "MQL4" / "Experts" / "Scalper.mq4").write_text(EXTRA_ROBOT, encoding="utf-8")
    analysed(window, qtbot, dialogs, lib)
    window.navigate("robots_isoles")
    page: Any = window.pages["robots_isoles"]
    page.refresh()
    names = {page.tools.item(r, 1).text() for r in range(page.tools.rowCount())}
    assert names == {"Gold Robot", "Scalper"}  # aucun indicateur ici
    # Groupe « Or » pour Gold Robot seulement.
    page.tools.selectRow(_row(page, "Gold Robot"))
    dialogs.texts.append("Or")
    click(window, qtbot, "robots_isoles.grouper")
    assert page.tools.item(_row(page, "Gold Robot"), 5).text() == "Or"
    click(window, qtbot, "robots_isoles.tout_outils")
    dest = tmp_path / "Dest"
    dest.mkdir()
    dialogs.directories.append(dest)
    dialogs.confirm_answer = True
    click(window, qtbot, "robots_isoles.isoler")
    assert "Groupes : Or" in dialogs.confirms[-1]
    wait_idle(window, qtbot)
    assert next(dest.iterdir()).name.startswith("Robots isolés")
    copied = _copied(dest)
    # Le robot du groupe et ce qui va avec (indicateur utilisé) dans « Or/Gold Robot/ ».
    assert any(c.startswith("Or/Gold Robot/") and c.endswith("Gold Robot.mq4") for c in copied)
    assert any(c.startswith("Or/Gold Robot/") and "SuperTrend" in c for c in copied)
    assert any(c.startswith("Scalper/") for c in copied)
    assert not any(c.startswith(("MQ4/", "MQ5/")) for c in copied)  # pas de mélange MQ4/MQ5


def test_indicateurs_isoles_un_seul_grand_dossier(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_dependencies(lib)
    analysed(window, qtbot, dialogs, lib)
    window.navigate("indicateurs_isoles")
    page: Any = window.pages["indicateurs_isoles"]
    page.refresh()
    names = {page.tools.item(r, 1).text() for r in range(page.tools.rowCount())}
    assert "SuperTrend" in names and "Gold Robot" not in names
    page.mode.setCurrentIndex(1)  # un seul grand dossier
    dest = tmp_path / "Dest"
    dest.mkdir()
    dialogs.directories.append(dest)
    dialogs.confirm_answer = True
    click(window, qtbot, "indicateurs_isoles.isoler_tout")
    assert "un seul grand dossier" in dialogs.confirms[-1]
    wait_idle(window, qtbot)
    assert next(dest.iterdir()).name.startswith("Indicateurs isolés")
    copied = _copied(dest)
    assert {"SuperTrend.mq4", "SuperTrend.ex4"} <= copied  # tous ensemble, sans sous-dossier


def test_groupe_sans_selection_et_annulation(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs
) -> None:
    window.navigate("robots_isoles")
    click(window, qtbot, "robots_isoles.grouper")
    click(window, qtbot, "robots_isoles.isoler")
    click(window, qtbot, "robots_isoles.isoler_tout")
    assert len(dialogs.infos) == 3
    click(window, qtbot, "robots_isoles.degrouper")


def test_sources_mq_cases_robots_et_indicateurs(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    """Le type est dit pour chaque source, même rangée n'importe où ; deux cases filtrent."""
    lib = tmp_path / "lib"
    build_dependencies(lib)
    (lib / "Telechargements" / "Tendance.mq4").write_text(
        "int init(){SetIndexBuffer(0,B);return 0;}\nint start(){return 0;}\n", encoding="utf-8"
    )
    (lib / "MQL4" / "Experts" / "Faux robot.mq4").write_text(
        "int start(){SetIndexBuffer(0,B);return 0;}\n", encoding="utf-8"
    )
    analysed(window, qtbot, dialogs, lib)
    window.navigate("sources_mq")
    page: Any = window.pages["sources_mq"]
    page.refresh()
    kinds = {
        page.sources.item(r, 1).text(): page.sources.item(r, 2).text()
        for r in range(page.sources.rowCount())
    }
    assert kinds["Telechargements/Tendance.mq4"] == "Indicateur"
    assert kinds["MQL4/Experts/Faux robot.mq4"] == ("Indicateur (probable) — peut-être mal rangé")
    assert kinds["MQL4/Experts/Gold/Gold Robot.mq4"] == "Robot"
    page.show_indicators.setChecked(False)
    page.show_others.setChecked(False)
    shown = {page.sources.item(r, 1).text() for r in range(page.sources.rowCount())}
    assert shown == {"MQL4/Experts/Gold/Gold Robot.mq4"}
    assert page.counts.text().startswith("1 robot(s), 0 indicateur(s)")
    page.show_robots.setChecked(False)
    assert page.sources.rowCount() == 0
