"""F11 — interface : écrans, actions réellement branchées, états vides, parcours complet,
clavier, réactivité. Chaque action déclenchée produit un effet observable en base ou sur disque."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QPushButton

from mtlm.ui.main import PAGES
from mtlm.ui.window import MainWindow
from tests.support.fs_snapshot import diff_snapshots, take_snapshot
from tests.synthetic.generate import generate_corpus
from tests.ui.conftest import FakeDialogs

ROBOT = (
    '#property version "1.0"\nextern double Lots = 0.1;\nextern int TP = 50;\n'
    "int start(){return 0;}\n"
)


def build_library(root: Path) -> None:
    experts = root / "MQL4" / "Experts"
    experts.mkdir(parents=True)
    (root / "MQL4" / "Presets").mkdir()
    (root / "Copies").mkdir()
    (experts / "Scalper.mq4").write_text(ROBOT, encoding="utf-8")
    (root / "Copies" / "Scalper.mq4").write_text(ROBOT, encoding="utf-8")
    (experts / "Scalper.ex4").write_bytes(bytes(range(256)))
    (root / "MQL4" / "Presets" / "Scalper_EURUSD.set").write_text(
        "Lots=0.2\nTP=40\n", encoding="utf-8"
    )


def wait_idle(window: MainWindow, qtbot: object) -> None:
    qtbot.waitUntil(lambda: not window.app.busy, timeout=120_000)  # type: ignore[attr-defined]
    qtbot.wait(50)  # type: ignore[attr-defined]


def click(window: MainWindow, qtbot: object, action_id: str) -> None:
    button = window.findChild(QPushButton, action_id)
    assert button is not None, action_id
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]


def page_keys(window: MainWindow) -> list[str]:
    keys = []
    for row in range(window.sidebar.count()):
        key = window.sidebar.item(row).data(Qt.ItemDataRole.UserRole)
        if key is not None:
            keys.append(key)
    return keys


def test_les_13_ecrans(window: MainWindow) -> None:
    keys = page_keys(window)
    assert len(PAGES) == 13 == len(keys) == len(set(keys))
    assert set(keys) == {p.key for p in PAGES}
    for key in keys:
        window.navigate(key)
        assert window.stack.currentWidget() is window.pages[key]
        assert window.current_key() == key
    # Les titres de section de la barre latérale ne sont pas sélectionnables.
    headers = [
        window.sidebar.item(r)
        for r in range(window.sidebar.count())
        if window.sidebar.item(r).data(Qt.ItemDataRole.UserRole) is None
    ]
    assert len(headers) == 4 and all(h.flags() == Qt.ItemFlag.NoItemFlags for h in headers)


def test_etat_vide_honnete(window: MainWindow) -> None:
    dashboard = window.pages["tableau"]
    assert "Aucune source" in dashboard.empty.text()
    assert dashboard.values["files"].text() == "0"
    for page in window.pages.values():
        page.refresh()
    assert window.pages["sources"].table.rowCount() == 0
    assert window.pages["explorateur"].table.rowCount() == 0
    assert window.pages["doublons"].groups.rowCount() == 0


def test_chaque_bouton_est_enregistre_accessible_et_branche(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs
) -> None:
    registry = window.app.registry.specs
    buttons = window.findChildren(QPushButton)
    assert len(buttons) >= 40
    for button in buttons:
        if button.objectName().startswith("qt_"):  # boutons internes de Qt
            continue
        spec = registry.get(button.objectName())
        assert spec is not None, f"bouton non enregistré : {button.text()}"
        assert button.accessibleName(), button.text()
        assert button.focusPolicy() & Qt.FocusPolicy.TabFocus, button.text()
        if not button.isEnabled():
            assert "non disponible" in button.text() and spec.reason_unavailable
        else:
            assert spec.handler is not None
    # Cliquer chaque bouton : son gestionnaire réel doit s'exécuter.
    dialogs.confirm_answer = False
    for action_id, spec in registry.items():
        if spec.handler is None:
            continue
        before = spec.calls
        page_key = action_id.split(".")[0]
        window.navigate(page_key)
        click(window, qtbot, action_id)
        wait_idle(window, qtbot)
        assert spec.calls == before + 1, action_id
    unexpected = [e for e in dialogs.errors if "Erreur inattendue" in e[1] or "Traceback" in e[1]]
    assert unexpected == []


def test_erreur_affichee_jamais_muette(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    dialogs.directories.append(tmp_path / "inexistant")
    window.navigate("sources")
    click(window, qtbot, "sources.ajouter")
    assert dialogs.errors and "Source refusée" in dialogs.errors[-1][1]


def test_parcours_complet(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    lib = tmp_path / "lib"
    build_library(lib)
    before = take_snapshot(lib)
    conn = window.app.ctx.conn
    # 1. Ajouter la source.
    dialogs.directories.append(lib)
    window.navigate("sources")
    click(window, qtbot, "sources.ajouter")
    assert window.pages["sources"].table.rowCount() == 1
    # 2. Tout analyser.
    window.navigate("tableau")
    click(window, qtbot, "tableau.analyser")
    wait_idle(window, qtbot)
    log = window.pages["analyse"].log.toPlainText()
    assert "Doublons et similarités" in log and "✔" in log
    # 3. Tableau de bord = valeurs réelles de la base.
    window.navigate("tableau")
    values = window.pages["tableau"].values
    assert values["files"].text() == "4"
    assert (
        values["dup_groups"].text()
        == str(conn.execute("SELECT count(*) FROM duplicate_group").fetchone()[0])
        == "1"
    )
    # 4. Explorateur → détail.
    explorer = window.pages["explorateur"]
    window.navigate("explorateur")
    explorer.text.setText("scalper")
    click(window, qtbot, "explorateur.rechercher")
    assert explorer.table.rowCount() == 4
    explorer.ext.setText("mq4")
    click(window, qtbot, "explorateur.rechercher")
    assert explorer.table.rowCount() == 2
    explorer.table.selectRow(0)
    click(window, qtbot, "explorateur.detail")
    assert window.stack.currentWidget() is window.pages["detail"]
    detail_page: Any = window.pages["detail"]
    assert "Type reconnu" in detail_page.text.toPlainText()
    # 5. SET : accepter l'association proposée.
    sets = window.pages["sets"]
    window.navigate("sets")
    sets.sets.selectRow(0)
    assert sets.assoc.rowCount() >= 1
    sets.assoc.selectRow(0)
    assert "couverture_parametres" in sets.evidence.toPlainText()
    click(window, qtbot, "sets.accepter")
    assert (
        conn.execute(
            "SELECT count(*) FROM association WHERE user_decision = 'accepted'"
        ).fetchone()[0]
        == 1
    )
    # 6. Familles.
    window.navigate("familles")
    assert window.pages["familles"].families.rowCount() >= 1
    # 7. Doublons.
    duplicates = window.pages["doublons"]
    window.navigate("doublons")
    duplicates.groups.selectRow(0)
    assert duplicates.members.rowCount() == 2
    # 8. Quarantaine : simulation puis confirmation (copie vérifiée).
    qdir = tmp_path / "quarantaine"
    qdir.mkdir()
    dialogs.directories.append(qdir)
    dialogs.confirm_answer = True
    window.navigate("quarantaine")
    click(window, qtbot, "quarantaine.destination")
    click(window, qtbot, "quarantaine.simuler")
    assert "SIMULATION" in window.pages["quarantaine"].summary.toPlainText()
    assert not any(qdir.rglob("*.mq4"))
    click(window, qtbot, "quarantaine.executer")
    wait_idle(window, qtbot)
    assert len(list(qdir.rglob("*.mq4"))) == 1
    assert (
        conn.execute("SELECT count(*) FROM file_record WHERE in_quarantine = 1").fetchone()[0] == 1
    )
    window.pages["quarantaine"].batches.selectRow(0)
    click(window, qtbot, "quarantaine.restaurer")
    assert (
        conn.execute("SELECT count(*) FROM file_record WHERE in_quarantine = 1").fetchone()[0] == 0
    )
    # 9. Organisation.
    odir = tmp_path / "rangement"
    odir.mkdir()
    dialogs.directories.append(odir)
    window.navigate("organisation")
    click(window, qtbot, "organisation.destination")
    click(window, qtbot, "organisation.previsualiser")
    assert "PRÉVISUALISATION" in window.pages["organisation"].summary.toPlainText()
    click(window, qtbot, "organisation.executer")
    wait_idle(window, qtbot)
    assert any(odir.rglob("Scalper.mq4"))
    # 10. Rapports.
    export = tmp_path / "export.csv"
    dialogs.save_paths.append(export)
    window.navigate("rapports")
    click(window, qtbot, "rapports.exporter")
    assert export.exists() and "Scalper" in export.read_text(encoding="utf-8-sig")
    click(window, qtbot, "rapports.audit_verifier")
    assert "Journal intact" in dialogs.infos[-1][1]
    # 11. Paramètres.
    settings = window.pages["parametres"]
    window.navigate("parametres")
    settings.fields["similarite.seuil"].setValue(0.9)
    click(window, qtbot, "parametres.enregistrer")
    assert (
        conn.execute("SELECT value_json FROM setting WHERE key = 'similarite.seuil'").fetchone()[0]
        == "0.9"
    )
    # Les originaux n'ont jamais été touchés pendant tout le parcours.
    assert diff_snapshots(before, take_snapshot(lib)) == []


def test_annulation_et_reactivite(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    generate_corpus(tmp_path / "lib", seed=8, n_files=3000)
    dialogs.directories.append(tmp_path / "lib")
    window.navigate("sources")
    click(window, qtbot, "sources.ajouter")
    gaps: list[float] = []
    last = [time.perf_counter()]

    def tick() -> None:
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(20)
    window.navigate("analyse")
    click(window, qtbot, "analyse.tout")
    assert window.app.busy
    qtbot.wait(300)  # type: ignore[attr-defined]
    click(window, qtbot, "analyse.pause")
    assert window.app.control is not None and window.app.control.paused
    click(window, qtbot, "analyse.reprendre")
    click(window, qtbot, "analyse.annuler")
    wait_idle(window, qtbot)
    timer.stop()
    states = {r[0] for r in window.app.ctx.conn.execute("SELECT state FROM job")}
    assert "running" not in states
    assert max(gaps) < 0.5, f"interface bloquée {max(gaps):.2f} s"


def test_navigation_au_clavier(window: MainWindow, qtbot: object) -> None:
    window.navigate("tableau")
    window.sidebar.setFocus()
    qtbot.keyClick(window.sidebar, Qt.Key.Key_Down)  # type: ignore[attr-defined]
    assert window.current_key() == "sources"
    qtbot.keyClick(window.sidebar, Qt.Key.Key_Down)  # type: ignore[attr-defined]
    qtbot.keyClick(window.sidebar, Qt.Key.Key_Down)  # type: ignore[attr-defined]
    assert window.current_key() == "explorateur"  # le titre de section est sauté
    qtbot.keyClick(window.sidebar, Qt.Key.Key_End)  # type: ignore[attr-defined]
    assert window.current_key() == "aide"


def test_accueil_guide(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    home: Any = window.pages["tableau"]
    assert [s.text() for s in home.step_status] == [
        "À faire",
        "Ajoutez d'abord un dossier",
        "Après l'analyse",
    ]
    lib = tmp_path / "lib"
    build_library(lib)
    dialogs.directories.append(lib)
    click(window, qtbot, "tableau.ajouter")
    assert home.step_status[0].text().startswith("✓")
    click(window, qtbot, "tableau.analyser")
    wait_idle(window, qtbot)
    window.navigate("tableau")
    assert home.step_status[1].text().startswith("✓  4 fichier")
    assert "Votre bibliothèque" in home.summary.text()
    click(window, qtbot, "tableau.resultats")
    assert window.current_key() == "sets"


def test_badges_de_statut() -> None:
    from mtlm.ui.base import badge_tone

    assert badge_tone("terminée") == "success"
    assert badge_tone("RÉFÉRENCE (conservée)") == "success"
    assert badge_tone("échec") == "danger"
    assert badge_tone("non admissible") == "danger"
    assert badge_tone("admissible à la quarantaine") == "warning"
    assert badge_tone("à vérifier") == "warning"
    assert badge_tone("en cours") == "info"
    assert badge_tone("non décidée") == "neutral"


def test_cartes_kpi_tons_reels_et_cliquables(
    window: MainWindow, qtbot: object, dialogs: FakeDialogs, tmp_path: Path
) -> None:
    home: Any = window.pages["tableau"]
    # Avant analyse : aucun ton inventé.
    assert all(frame.property("tone") in ("", None) for frame in home.tiles.values())
    lib = tmp_path / "lib"
    build_library(lib)
    dialogs.directories.append(lib)
    click(window, qtbot, "tableau.ajouter")
    click(window, qtbot, "tableau.analyser")
    wait_idle(window, qtbot)
    window.navigate("tableau")
    # La bibliothèque contient un doublon exact (Scalper.mq4 copié) : carte en alerte.
    assert home.tiles["dup_groups"].property("tone") == "warning"
    assert home.hints["dup_groups"].text() == "Action recommandée"
    assert home.tiles["files"].property("tone") == "info"
    qtbot.mouseClick(home.tiles["dup_groups"], Qt.MouseButton.LeftButton)  # type: ignore[attr-defined]
    assert window.current_key() == "doublons"
