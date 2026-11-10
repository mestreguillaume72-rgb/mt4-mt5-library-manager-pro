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

    # -- erreurs et messages --------------------------------------------------------------------
    def _show_error(self, action: str, exc: Exception) -> None:
        if self.window is not None:
            self.dialogs.error(self.window, action, str(exc))

    def status(self, text: str) -> None:
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


class MainWindow(QMainWindow):
    def __init__(self, app: UiApp, page_factories: list[Callable[[UiApp], Any]]) -> None:
        super().__init__()
        self.app = app
        app.window = self
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1280, 820)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("navigation")
        self.sidebar.setAccessibleName("Navigation entre les écrans")
        self.sidebar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.sidebar.setFixedWidth(230)
        self.stack = QStackedWidget()
        self.pages: dict[str, Any] = {}
        for factory in page_factories:
            page = factory(app)
            self.pages[page.key] = page
            self.stack.addWidget(page)
            item = QListWidgetItem(page.title)
            item.setData(Qt.ItemDataRole.UserRole, page.key)
            self.sidebar.addItem(item)
        self.sidebar.currentRowChanged.connect(self._show_row)
        header = QLabel(f"<b>{APP_NAME}</b><br><small>Originaux en lecture seule</small>")
        header.setTextFormat(Qt.TextFormat.RichText)
        left = QVBoxLayout()
        left.addWidget(header)
        left.addWidget(self.sidebar)
        container = QWidget()
        layout = QHBoxLayout(container)
        side = QWidget()
        side.setLayout(left)
        layout.addWidget(side)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(container)
        self._menu()
        self.sidebar.setCurrentRow(0)
        app.on_task_finished(self.refresh_current)
        self.statusBar().showMessage("Prêt. Vos fichiers d'origine ne sont jamais modifiés.")

    def _menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Fichier")
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

    def _show_row(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        self.refresh_current()

    def navigate(self, key: str, **kwargs: Any) -> None:
        keys = list(self.pages)
        self.sidebar.setCurrentRow(keys.index(key))
        page = self.pages[key]
        if kwargs and hasattr(page, "show_item"):
            page.show_item(**kwargs)

    def refresh_current(self) -> None:
        refresh = getattr(self.stack.currentWidget(), "refresh", None)
        if callable(refresh):
            refresh()

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — API Qt
        if self.app.busy and self.app.control is not None:
            self.app.control.cancel()
            self.app.wait(30_000)
        super().closeEvent(event)
