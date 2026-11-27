"""1.6.0 (suite) — supprimer où je veux, exemplaires uniques au choix, nombre d'éléments
sous chaque liste, « Recommencer l'analyse à zéro »."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mtlm.ui.window import MainWindow
from tests.integration.test_trash import FakeTrash
from tests.ui.conftest import FakeDialogs
from tests.ui.test_ui import click, wait_idle
from tests.ui.test_ui_130 import analysed


def _select(table: Any, column: int, predicate: Any) -> None:
    for row in range(table.rowCount()):
        item = table.item(row, column)
        if item is not None and predicate(item.text()):
            table.selectRow(row)


def test_explorateur_supprime_ce_que_je_choisis_avec_choix_pour_les_uniques(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = analysed(window, qtbot, dialogs, tmp_path)
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("explorateur")
    page: Any = window.pages["explorateur"]
    page.search()
    assert page.table.count_label.text() == "4 fichiers"
    assert page.table.count_label.parent() is not None  # affiché sous la liste
    for each in window.pages.values():  # chaque liste de chaque écran a son compteur affiché
        for table in each.findChildren(type(page.table)):
            assert table.count_label.parent() is not None, (each.key, table)
    _select(page.table, 1, lambda name: name in ("Scalper.ex4", "Scalper.mq4"))
    assert page.table.count_label.text() == "4 fichiers — 3 sélectionnés"
    # Scalper.ex4 est unique ; les deux Scalper.mq4 identiques : le dernier choisi l'est aussi.
    dialogs.confirm_answer = True
    click(window, qtbot, "explorateur.corbeille")
    wait_idle(window, qtbot)
    assert "SEUL exemplaire" in dialogs.confirms[-2]
    assert "Supprimer AUSSI" in dialogs.confirms[-1]
    assert "3 fichier(s) mis à la Corbeille" in dialogs.infos[-1][1]
    assert not (lib / "MQL4" / "Experts" / "Scalper.ex4").exists()


def test_uniques_gardes_si_je_refuse(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = analysed(window, qtbot, dialogs, tmp_path)
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("explorateur")
    page: Any = window.pages["explorateur"]
    page.search()
    _select(page.table, 1, lambda name: name in ("Scalper.ex4", "Scalper.mq4"))
    dialogs.answers = [True, False]  # oui à la Corbeille, non aux exemplaires uniques
    click(window, qtbot, "explorateur.corbeille")
    wait_idle(window, qtbot)
    assert "1 fichier(s) mis à la Corbeille" in dialogs.infos[-1][1]
    assert (lib / "MQL4" / "Experts" / "Scalper.ex4").exists()
    remaining = [
        p for p in (lib / "MQL4" / "Experts" / "Scalper.mq4", lib / "Copies" / "Scalper.mq4")
    ]
    assert sum(p.exists() for p in remaining) == 1  # une copie identique reste toujours


def test_recommencer_a_zero_depuis_l_ecran_analyse(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    analysed(window, qtbot, dialogs, tmp_path)
    conn = window.app.ctx.conn
    assert conn.execute("SELECT count(*) FROM file_analysis").fetchone()[0] > 0
    window.navigate("analyse")
    dialogs.confirm_answer = False
    click(window, qtbot, "analyse.zero")
    assert conn.execute("SELECT count(*) FROM file_analysis").fetchone()[0] > 0  # refusé
    dialogs.answers = [True, True]
    click(window, qtbot, "analyse.zero")
    wait_idle(window, qtbot)
    assert "RIEN n'est touché sur le disque" in dialogs.confirms[-2]
    # Relancée tout de suite : les résultats sont revenus.
    assert conn.execute("SELECT count(*) FROM file_analysis").fetchone()[0] > 0


def test_etapes_numerotees_dans_le_journal(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    analysed(window, qtbot, dialogs, tmp_path)
    assert window.app.last_message is not None
    page: Any = window.pages["analyse"]
    assert page.jobs.count_label.text().endswith(("tâche", "tâches"))
