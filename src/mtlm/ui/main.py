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
    SourcesMqPage,
)
from mtlm.ui.pages_analysis import (
    ArchivesPage,
    DuplicatesPage,
    FamiliesPage,
    RiskPage,
    SetsPage,
)
from mtlm.ui.pages_isolated import IndicatorsPage, RobotsPage
from mtlm.ui.pages_main import AnalysisPage, DashboardPage, DetailPage, ExplorerPage, SourcesPage
from mtlm.ui.theme import apply_theme
from mtlm.ui.window import MainWindow, UiApp

#: Les 13 écrans exigés par la spécification (F11) + « Sources MQ4/MQ5 » (1.4.0)
#: + « Robots isolés » et « Indicateurs isolés » (1.6.0).
PAGES = [
    DashboardPage,
    SourcesPage,
    AnalysisPage,
    ExplorerPage,
    DetailPage,
    SetsPage,
    FamiliesPage,
    DuplicatesPage,
    ArchivesPage,
    RiskPage,
    QuarantinePage,
    OrganizePage,
    SourcesMqPage,
    RobotsPage,
    IndicatorsPage,
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

    def ask_text(self, parent: object, title: str, text: str, default: str = "") -> str | None:
        return None  # l'auto-diagnostic ne saisit rien

    def choose_items(
        self, parent: object, title: str, text: str, items: list[tuple[str, str]]
    ) -> list[str] | None:
        return []  # l'auto-diagnostic ne valide jamais de lien


def autotest(source: Path, report: Path | None = None) -> int:
    """Auto-diagnostic de l'application installée (sans écran possible) : ouvre tous les écrans,
    ajoute ``source`` (lecture seule), lance toute l'analyse et vérifie les résultats. Les
    données de l'application sont placées dans un dossier temporaire supprimé à la fin."""
    import tempfile
    import time

    qt_app = QApplication.instance() or QApplication([])
    apply_theme(qt_app)  # type: ignore[arg-type]
    from mtlm.app.context import close_logs

    # Windows : un fichier ouvert (journal) ne peut pas être effacé ; le journal est fermé
    # avant le nettoyage, et un reste éventuel n'interrompt jamais l'auto-diagnostic.
    with tempfile.TemporaryDirectory(prefix="mtlm-autotest-", ignore_cleanup_errors=True) as home:
        dialogs = AutoDialogs(source)
        window = build_window(default_paths({"MTLM_HOME": home}), dialogs)
        window.show()
        pages = list(window.pages)

        def trace(text: str) -> None:
            if report is not None:  # suivi pas à pas : utile si l'auto-diagnostic se bloque
                with report.open("a", encoding="utf-8") as handle:
                    handle.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")

        trace("écrans ouverts ; ajout de la source")
        window.pages["sources"].add()
        trace(f"sources : {window.pages['sources'].table.rowCount()} ; analyse lancée")
        window.pages["analyse"].start_all()
        deadline = time.monotonic() + 20 * 60
        last = ""
        while window.app.busy:
            qt_app.processEvents()
            window.app.wait(50)
            message = window.app.last_message or ""
            if message != last:
                last = message
                trace(message)
            if time.monotonic() > deadline:
                dialogs.errors.append("analyse trop longue (plus de 20 minutes) : arrêtée")
                if window.app.control is not None:
                    window.app.control.cancel()
                break
        qt_app.processEvents()
        for key in pages:
            window.navigate(key)
        files = int(window.pages["tableau"].values["files"].text())
        log = window.pages["analyse"].log.toPlainText()
        window.app.ctx.close()
        close_logs()
    ok = len(pages) == len(PAGES) and files > 0 and not dialogs.errors and log.count("✔") == 8
    lines = [
        f"Auto-diagnostic : {'RÉUSSI' if ok else 'ÉCHEC'} — {len(pages)} écran(s), "
        f"{files} fichier(s) analysé(s) dans {source}",
        log,
        *(f"Erreur : {error}" for error in dialogs.errors),
    ]
    text = "\n".join(lines)
    # Application fenêtrée de Windows : pas de console, le rapport va dans un fichier.
    if report is not None:
        with report.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    if sys.stdout is not None:
        print(text)
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv)
    if "--autotest" in args:
        index = args.index("--autotest")
        target = Path(args[index + 1]) if len(args) > index + 1 else Path(sys.executable).parent
        report = None
        if "--rapport" in args and len(args) > args.index("--rapport") + 1:
            report = Path(args[args.index("--rapport") + 1])
        try:
            return autotest(target, report)
        except Exception as exc:  # jamais de fenêtre d'erreur bloquante : un rapport d'échec
            text = f"Auto-diagnostic : ÉCHEC — {type(exc).__name__} : {exc}"
            if report is not None:
                with report.open("a", encoding="utf-8") as handle:
                    handle.write(text + "\n")
            if sys.stdout is not None:
                print(text)
            return 1
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
