"""Tests de l'interface : Qt sans écran (offscreen) et dialogues simulés."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWidget

from mtlm.core.clock import FixedClock
from mtlm.core.paths import AppPaths
from mtlm.ui.main import build_window
from mtlm.ui.window import MainWindow


class FakeDialogs:
    """Remplace les fenêtres de dialogue : réponses programmées, messages enregistrés."""

    def __init__(self) -> None:
        self.directories: list[Path | None] = []
        self.save_paths: list[Path | None] = []
        self.confirm_answer = True
        self.infos: list[tuple[str, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.confirms: list[str] = []
        self.choices: list[list[str] | None] = []  # réponses programmées des listes à cocher
        self.offered: list[list[tuple[str, str]]] = []

    def choose_directory(self, parent: QWidget, title: str) -> Path | None:
        return self.directories.pop(0) if self.directories else None

    def save_file(self, parent: QWidget, title: str, suggestion: str) -> Path | None:
        return self.save_paths.pop(0) if self.save_paths else None

    def confirm(self, parent: QWidget, title: str, text: str) -> bool:
        self.confirms.append(text)
        return self.confirm_answer

    def info(self, parent: QWidget, title: str, text: str) -> None:
        self.infos.append((title, text))

    def error(self, parent: QWidget, title: str, text: str) -> None:
        self.errors.append((title, text))

    def choose_items(
        self, parent: QWidget, title: str, text: str, items: list[tuple[str, str]]
    ) -> list[str] | None:
        self.offered.append(items)
        answer = self.choices.pop(0) if self.choices else []
        if answer == ["*"]:  # « tout cocher »
            return [key for key, _caption in items]
        return answer


@pytest.fixture
def dialogs() -> FakeDialogs:
    return FakeDialogs()


@pytest.fixture
def window(
    qtbot: object, paths: AppPaths, clock: FixedClock, dialogs: FakeDialogs
) -> Iterator[MainWindow]:
    win = build_window(paths, dialogs, clock)
    qtbot.addWidget(win)  # type: ignore[attr-defined]
    win.show()
    yield win
    win.app.wait()
    win.app.ctx.close()
