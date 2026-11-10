"""Point d'entrée de l'application graphique : ``mtlm-gui`` (et l'application macOS .app)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mtlm import APP_NAME, __version__
from mtlm.app.context import open_app
from mtlm.core.clock import Clock
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths, default_paths
from mtlm.ui.base import Dialogs, QtDialogs
from mtlm.ui.pages_actions import (
    HelpPage,
    OrganizePage,
    QuarantinePage,
    ReportsPage,
    SettingsPage,
)
from mtlm.ui.pages_analysis import DuplicatesPage, FamiliesPage, SetsPage
from mtlm.ui.pages_main import AnalysisPage, DashboardPage, DetailPage, ExplorerPage, SourcesPage
from mtlm.ui.theme import apply_theme
from mtlm.ui.window import MainWindow, UiApp

#: Les 13 écrans exigés par la spécification (F11), dans l'ordre de la barre latérale.
PAGES = [
    DashboardPage,
    SourcesPage,
    AnalysisPage,
    ExplorerPage,
    DetailPage,
    SetsPage,
    FamiliesPage,
    DuplicatesPage,
    QuarantinePage,
    OrganizePage,
    ReportsPage,
    SettingsPage,
    HelpPage,
]


def build_window(
    paths: AppPaths, dialogs: Dialogs | None = None, clock: Clock | None = None
) -> MainWindow:
    ctx = open_app(paths, clock)
    app = UiApp(ctx, dialogs or QtDialogs(), clock)
    return MainWindow(app, list(PAGES))


class AutoDialogs:
    """Dialogues automatiques de l'auto-diagnostic : aucune intervention humaine."""

    def __init__(self, source: Path) -> None:
        self.source = source
        self.errors: list[str] = []

    def choose_directory(self, parent: object, title: str) -> Path | None:
        return self.source

    def save_file(self, parent: object, title: str, suggestion: str) -> Path | None:
        return None

    def confirm(self, parent: object, title: str, text: str) -> bool:
        return False  # l'auto-diagnostic ne confirme jamais d'opération d'écriture

    def info(self, parent: object, title: str, text: str) -> None:
        return None

    def error(self, parent: object, title: str, text: str) -> None:
        self.errors.append(f"{title} : {text}")


def autotest(source: Path) -> int:
    """Auto-diagnostic de l'application installée (sans écran possible) : ouvre les 13 écrans,
    ajoute ``source`` (lecture seule), lance toute l'analyse et vérifie les résultats. Les
    données de l'application sont placées dans un dossier temporaire supprimé à la fin."""
    import tempfile

    qt_app = QApplication.instance() or QApplication([])
    apply_theme(qt_app)  # type: ignore[arg-type]
    with tempfile.TemporaryDirectory(prefix="mtlm-autotest-") as home:
        dialogs = AutoDialogs(source)
        window = build_window(default_paths({"MTLM_HOME": home}), dialogs)
        window.show()
        pages = list(window.pages)
        window.pages["sources"].add()
        window.pages["analyse"].start_all()
        while window.app.busy:
            qt_app.processEvents()
            window.app.wait(50)
        qt_app.processEvents()
        for key in pages:
            window.navigate(key)
        files = int(window.pages["tableau"].values["files"].text())
        log = window.pages["analyse"].log.toPlainText()
        window.app.ctx.close()
    ok = len(pages) == 13 and files > 0 and not dialogs.errors and log.count("✔") == 8
    print(
        f"Auto-diagnostic : {'RÉUSSI' if ok else 'ÉCHEC'} — {len(pages)} écran(s), "
        f"{files} fichier(s) analysé(s) dans {source}"
    )
    print(log)
    for error in dialogs.errors:
        print(f"Erreur : {error}")
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv)
    if "--autotest" in args:
        index = args.index("--autotest")
        target = Path(args[index + 1]) if len(args) > index + 1 else Path(sys.executable).parent
        return autotest(target)
    qt_app = QApplication.instance() or QApplication(args)
    qt_app.setApplicationName(APP_NAME)
    apply_theme(qt_app)  # type: ignore[arg-type]
    qt_app.setApplicationVersion(__version__)
    try:
        window = build_window(default_paths())
    except MtlmError as exc:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(None, APP_NAME, f"Démarrage impossible : {exc}")
        return 1
    window.show()
    code = qt_app.exec()
    window.app.ctx.close()
    return int(code)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
