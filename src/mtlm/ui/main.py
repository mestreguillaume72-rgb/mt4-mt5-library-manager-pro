"""Point d'entrée de l'application graphique : ``mtlm-gui`` (et l'application macOS .app)."""

from __future__ import annotations

import sys
from collections.abc import Sequence

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


def main(argv: Sequence[str] | None = None) -> int:
    qt_app = QApplication.instance() or QApplication(list(argv or sys.argv))
    qt_app.setApplicationName(APP_NAME)
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
