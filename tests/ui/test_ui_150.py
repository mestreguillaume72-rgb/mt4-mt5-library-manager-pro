"""1.5.0 — interface : écran Archives, case « Décompresser », écran Fichiers à risque."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from mtlm.ui.window import MainWindow
from tests.integration.test_trash import FakeTrash
from tests.ui.conftest import FakeDialogs
from tests.ui.test_ui import build_library, click, wait_idle


def analysed(window: MainWindow, qtbot: object, dialogs: FakeDialogs, lib: Path) -> None:
    dialogs.directories.append(lib)
    click(window, qtbot, "tableau.ajouter")
    click(window, qtbot, "tableau.analyser")
    wait_idle(window, qtbot)


def test_archives_verdict_et_decompression(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_library(lib)
    robot = (lib / "MQL4" / "Experts" / "Scalper.mq4").read_bytes()
    with zipfile.ZipFile(lib / "deja.zip", "w") as z:
        z.writestr("Scalper.mq4", robot)
    with zipfile.ZipFile(lib / "nouveau.zip", "w") as z:
        z.writestr("Nouveau/Nouveau.set", b"Lots=1\n")
    analysed(window, qtbot, dialogs, lib)
    window.app.ctx.trash = FakeTrash(tmp_path / "Corbeille")
    window.navigate("archives")
    page: Any = window.pages["archives"]
    page.refresh()
    verdicts = {
        page.archives.item(r, 1).text(): page.archives.item(r, 6).text()
        for r in range(page.archives.rowCount())
    }
    assert verdicts["deja.zip"] == "Déjà décompressée : tout est sur le disque"
    assert verdicts["nouveau.zip"] == "Contient 1 fichier(s) absent(s) du disque"
    for row in range(page.archives.rowCount()):
        if page.archives.item(row, 1).text() == "nouveau.zip":
            page.archives.selectRow(row)
    assert page.entries.item(0, 1).text() == "SET"
    dialogs.confirm_answer = True
    click(window, qtbot, "archives.decompresser")
    wait_idle(window, qtbot)
    assert "1 archive(s) décompressée(s)" in dialogs.infos[-1][1]
    assert (lib / "nouveau" / "Nouveau" / "Nouveau.set").exists()
    assert not (lib / "nouveau.zip").exists()


def test_case_decompresser_demande_confirmation(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs
) -> None:
    page: Any = window.pages["analyse"]
    dialogs.confirm_answer = False
    page.decompress.setChecked(True)
    assert not page.decompress.isChecked()  # refusé : rien n'est activé
    assert "Corbeille" in dialogs.confirms[-1]
    dialogs.confirm_answer = True
    page.decompress.setChecked(True)
    from mtlm.app.settings import SettingsService

    ctx = window.app.ctx
    assert SettingsService(ctx.conn, ctx.journal).get("archives.decompresser") == 1


def test_fichiers_a_risque(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_library(lib)
    (lib / "Setup.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 60)
    analysed(window, qtbot, dialogs, lib)
    window.navigate("risques")
    page: Any = window.pages["risques"]
    click(window, qtbot, "risques.rechercher")
    wait_idle(window, qtbot)
    rows = {
        page.findings.item(r, 2).text(): page.findings.item(r, 1).text()
        for r in range(page.findings.rowCount())
    }
    assert rows["Setup.exe"] == "Risque élevé"
    assert "pas des preuves" in page.summary.text()
    from mtlm.ui.bulles import ACTION_TIPS

    assert "pas un antivirus" in ACTION_TIPS["risques.rechercher"]
