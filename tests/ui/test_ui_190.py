"""1.9.0 — changer la langue dans Paramètres : toute l'interface est reconstruite aussitôt,
dans la langue choisie, et le choix est gardé."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLabel, QPushButton

from mtlm.app.settings import SettingsService
from mtlm.core.i18n import catalog, language
from mtlm.ui.window import MainWindow
from tests.ui.conftest import FakeDialogs


def _texts(window: Any) -> set[str]:
    return {b.text() for b in window.findChildren(QPushButton)} | {
        lab.text() for lab in window.findChildren(QLabel)
    }


def test_changer_de_langue(window: MainWindow, qtbot: object, dialogs: FakeDialogs) -> None:
    window.navigate("parametres")
    page: Any = window.pages["parametres"]
    assert "Actualiser" in _texts(window) or "Enregistrer" in _texts(window)
    page.language.setCurrentIndex(1)  # English
    english: Any = window.rebuilt
    assert english is not None and language() == "en"
    texts = _texts(english)
    assert catalog("en")["Enregistrer"] in texts
    assert "Enregistrer" not in texts
    assert english.current_key() == "parametres"
    ctx = english.app.ctx
    assert SettingsService(ctx.conn, ctx.journal).language() == "en"
    spanish_page: Any = english.pages["parametres"]
    spanish_page.language.setCurrentIndex(2)  # Español
    spanish: Any = english.rebuilt
    assert language() == "es"
    assert catalog("es")["Enregistrer"] in _texts(spanish)
    back: Any = spanish.pages["parametres"]
    back.language.setCurrentIndex(0)
    assert language() == "fr"
    assert "Enregistrer" in _texts(spanish.rebuilt)
