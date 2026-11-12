"""Fenêtre principale : barre latérale (13 écrans), pile de pages, barre d'état, tâches."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mtlm import APP_NAME, __version__
from mtlm.app.context import AppContext
from mtlm.core.clock import Clock
from mtlm.core.control import TaskControl
from mtlm.ui.base import ActionRegistry, Dialogs, TaskFunction, TaskRunner
from mtlm.ui.theme import app_icon


class UiApp:
    """État partagé par les pages : contexte, dialogues, registre, exécution des tâches."""

    def __init__(self, ctx: AppContext, dialogs: Dialogs, clock: Clock | None = None) -> None:
        self.ctx = ctx
        self.dialogs = dialogs
        self.clock = clock
        self.window: MainWindow | None = None
        self.registry = ActionRegistry(self._show_error)
        self.runner: TaskRunner | None = None
        self.control: TaskControl | None = None
        self._listeners: list[Callable[[], None]] = []
        self.last_message = ""

    # -- erreurs et messages --------------------------------------------------------------------
    def _show_error(self, action: str, exc: Exception) -> None:
        if self.window is not None:
            self.dialogs.error(self.window, action, str(exc))

    def status(self, text: str) -> None:
        self.last_message = text
        if self.window is not None:
            self.window.statusBar().showMessage(text)

    def on_task_finished(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    # -- tâches de fond -------------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.runner is not None and self.runner.isRunning()

    def run_task(
        self,
        title: str,
        function: TaskFunction,
        on_success: Callable[[Any], None],
        on_message: Callable[[str], None] | None = None,
    ) -> bool:
        if self.busy:
            if self.window is not None:
                self.dialogs.info(
                    self.window,
                    title,
                    "Une autre tâche est en cours : attendez "
                    "sa fin, ou mettez-la en pause / annulez-la (écran Analyse).",
                )
            return False
        self.control = TaskControl()
        runner = TaskRunner(self.ctx.paths, self.clock, function, self.control)
        self.runner = runner

        def message(text: str) -> None:
            self.status(text)
            if on_message is not None:
                on_message(text)

        def done(result: Any) -> None:
            self.status(f"{title} : terminé.")
            on_success(result)
            self._finished()

        def failed(text: str) -> None:
            self.status(f"{title} : échec.")
            if self.window is not None:
                self.dialogs.error(self.window, title, text)
            self._finished()

        def cancelled() -> None:
            self.status(f"{title} : annulé (état cohérent conservé).")
            self._finished()

        runner.message.connect(message)
        runner.succeeded.connect(done)
        runner.failed.connect(failed)
        runner.cancelled.connect(cancelled)
        self.status(f"{title}…")
        runner.start()
        return True

    def _finished(self) -> None:
        for callback in self._listeners:
            callback()

    def wait(self, timeout_ms: int = 600_000) -> None:
        if self.runner is not None:
            self.runner.wait(timeout_ms)


SECTIONS: list[tuple[str, list[str]]] = [
    ("COMMENCER", ["tableau", "sources", "analyse"]),
    ("RÉSULTATS", ["explorateur", "detail", "sets", "familles", "doublons"]),
    ("ACTIONS", ["quarantaine", "organisation", "rapports"]),
    ("RÉGLAGES", ["parametres", "aide"]),
]


class MainWindow(QMainWindow):
    def __init__(self, app: UiApp, page_factories: list[Callable[[UiApp], Any]]) -> None:
        super().__init__()
        self.app = app
        app.window = self
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1320, 840)
        self.setMinimumSize(1080, 700)
        self.pages: dict[str, Any] = {}
        self.stack = QStackedWidget()
        for factory in page_factories:
            page = factory(app)
            self.pages[page.key] = page
            self.stack.addWidget(page)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("navigation")
        self.sidebar.setAccessibleName("Navigation entre les écrans")
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        placed: list[str] = []
        for section, keys in SECTIONS:
            header = QListWidgetItem(section)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.sidebar.addItem(header)
            for key in keys:
                if key in self.pages:
                    self._add_nav(key)
                    placed.append(key)
        for key in self.pages:  # écrans non classés (sécurité) : ajoutés à la fin
            if key not in placed:
                self._add_nav(key)
        self.sidebar.currentItemChanged.connect(self._on_item)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(262)
        left = QVBoxLayout(side)
        left.setContentsMargins(14, 22, 14, 16)
        brand_row = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon(64).pixmap(40, 40))
        brand = QLabel("MT4 MT5\nLibrary Manager PRO")
        brand.setObjectName("brand")
        brand_row.addWidget(logo)
        brand_row.addWidget(brand, 1)
        left.addLayout(brand_row)
        safe = QLabel("🔒 Rien n'est supprimé sans votre accord")
        safe.setObjectName("brandSub")
        left.addWidget(safe)
        left.addSpacing(6)
        left.addWidget(self.sidebar, 1)
        version = QLabel(f"Version {__version__}")
        version.setObjectName("brandSub")
        left.addWidget(version)
        container = QWidget()
        container.setObjectName("central")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(side)
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 30, 36, 22)
        content_layout.addWidget(self.stack)
        layout.addWidget(content, 1)
        self.setCentralWidget(container)
        self._menu()
        self.navigate(next(iter(self.pages)))
        app.on_task_finished(self.refresh_current)
        self.statusBar().showMessage(
            "Prêt. Rien n'est modifié dans vos dossiers sans votre confirmation."
        )

    def _add_nav(self, key: str) -> None:
        page = self.pages[key]
        item = QListWidgetItem(f"{page.icon}   {page.title}")
        item.setData(Qt.ItemDataRole.UserRole, key)
        self.sidebar.addItem(item)

    def _row_of(self, key: str) -> int:
        for row in range(self.sidebar.count()):
            if self.sidebar.item(row).data(Qt.ItemDataRole.UserRole) == key:
                return row
        raise KeyError(key)

    def _on_item(self, current: QListWidgetItem | None, _previous: object = None) -> None:
        if current is None:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if key is None:
            return
        self.stack.setCurrentWidget(self.pages[key])
        self.refresh_current()

    def _menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Aller à")
        for index, page in enumerate(self.pages.values()):
            action = QAction(page.title, self)
            if index < 9:
                action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(lambda _c=False, k=page.key: self.navigate(k))
            file_menu.addAction(action)
        file_menu.addSeparator()
        quit_action = QAction("Quitter", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def current_key(self) -> str:
        page = self.stack.currentWidget()
        return str(getattr(page, "key", ""))

    def navigate(self, key: str, **kwargs: Any) -> None:
        self.sidebar.setCurrentRow(self._row_of(key))
        page = self.pages[key]
        if kwargs and hasattr(page, "show_item"):
            page.show_item(**kwargs)

    def refresh_current(self) -> None:
        refresh = getattr(self.stack.currentWidget(), "refresh", None)
        if callable(refresh):
            refresh()

    def closeEvent(self, event: Any) -> None:
        if self.app.busy and self.app.control is not None:
            self.app.control.cancel()
            self.app.wait(30_000)
        super().closeEvent(event)
