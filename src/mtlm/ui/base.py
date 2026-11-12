"""Briques communes de l'interface : registre d'actions, dialogues, tâches de fond, tableaux."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from mtlm.app.context import AppContext, open_app
from mtlm.core.clock import Clock
from mtlm.core.control import Cancelled, TaskControl
from mtlm.core.errors import MtlmError
from mtlm.core.paths import AppPaths

log = logging.getLogger("mtlm.ui")


# ---- dialogues (remplaçables dans les tests) -----------------------------------------------
class Dialogs(Protocol):
    def choose_directory(self, parent: QWidget, title: str) -> Path | None: ...
    def save_file(self, parent: QWidget, title: str, suggestion: str) -> Path | None: ...
    def confirm(self, parent: QWidget, title: str, text: str) -> bool: ...
    def info(self, parent: QWidget, title: str, text: str) -> None: ...
    def error(self, parent: QWidget, title: str, text: str) -> None: ...


class QtDialogs:
    def choose_directory(self, parent: QWidget, title: str) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(parent, title)
        return Path(chosen) if chosen else None

    def save_file(self, parent: QWidget, title: str, suggestion: str) -> Path | None:
        chosen, _ = QFileDialog.getSaveFileName(
            parent, title, suggestion, "CSV (*.csv);;JSON (*.json);;JSONL (*.jsonl)"
        )
        return Path(chosen) if chosen else None

    def confirm(self, parent: QWidget, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            parent,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def info(self, parent: QWidget, title: str, text: str) -> None:
        QMessageBox.information(parent, title, text)

    def error(self, parent: QWidget, title: str, text: str) -> None:
        QMessageBox.critical(parent, title, text)


# ---- registre d'actions ---------------------------------------------------------------------
#: Rôle visuel des boutons : « primary » = action principale de l'écran, « danger » = action
#: à risque ou d'annulation, « ghost » = action secondaire discrète.
DEFAULT_ROLES = {
    "sources.ajouter": "primary",
    "analyse.tout": "primary",
    "analyse.lancer": "primary",
    "analyse.annuler": "danger",
    "explorateur.rechercher": "primary",
    "detail.afficher": "primary",
    "sets.accepter": "primary",
    "sets.rejeter": "danger",
    "familles.rechercher": "primary",
    "quarantaine.simuler": "primary",
    "quarantaine.executer": "primary",
    "quarantaine.annuler": "danger",
    "organisation.previsualiser": "primary",
    "organisation.executer": "primary",
    "rapports.exporter": "primary",
    "parametres.enregistrer": "primary",
    "aide.demarrer": "primary",
    "sources.retirer": "danger",
    "quarantaine.corbeille": "danger",
    "doublons.corbeille_groupe": "danger",
    "doublons.corbeille_fichier": "danger",
    "familles.corbeille": "danger",
    "familles.dossier": "primary",
    "familles.isoler": "primary",
}


@dataclass
class ActionSpec:
    action_id: str
    label: str
    handler: Callable[[], None] | None
    reason_unavailable: str | None = None
    calls: int = 0


class ActionRegistry:
    """Chaque bouton est créé ici : identifiant unique, libellé, gestionnaire réel. Un bouton
    sans fonctionnalité est **désactivé et marqué « non disponible »** avec la raison."""

    def __init__(self, on_error: Callable[[str, Exception], None]) -> None:
        self.specs: dict[str, ActionSpec] = {}
        self._on_error = on_error

    def button(
        self,
        action_id: str,
        label: str,
        handler: Callable[[], None],
        tooltip: str = "",
        role: str = "",
    ) -> QPushButton:
        if action_id in self.specs:
            raise ValueError(f"Action en double : {action_id}")
        spec = ActionSpec(action_id, label, handler)
        self.specs[action_id] = spec
        button = QPushButton(label)
        button.setObjectName(action_id)
        button.setAccessibleName(label)
        button.setToolTip(tooltip or label)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        role = role or DEFAULT_ROLES.get(action_id, "")
        if role:
            button.setProperty("role", role)
        button.clicked.connect(lambda _checked=False: self.trigger(action_id))
        return button

    def unavailable(self, action_id: str, label: str, reason: str) -> QPushButton:
        spec = ActionSpec(action_id, label, None, reason)
        self.specs[action_id] = spec
        button = QPushButton(f"{label} (non disponible)")
        button.setObjectName(action_id)
        button.setEnabled(False)
        button.setToolTip(f"Non disponible : {reason}")
        button.setAccessibleName(f"{label} (non disponible)")
        return button

    def trigger(self, action_id: str) -> None:
        spec = self.specs[action_id]
        if spec.handler is None:
            return
        spec.calls += 1
        try:
            spec.handler()
        except MtlmError as exc:
            self._on_error(spec.label, exc)
        except Exception as exc:  # erreur inattendue : affichée et journalisée, jamais muette
            log.error("Erreur inattendue dans « %s » :\n%s", spec.label, traceback.format_exc())
            self._on_error(spec.label, exc)


# ---- tâches de fond ---------------------------------------------------------------------------
TaskFunction = Callable[[AppContext, TaskControl, Callable[[str], None]], Any]


class TaskRunner(QThread):
    """Exécute une tâche longue dans un fil séparé, avec sa propre connexion à la base."""

    message = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        paths: AppPaths,
        clock: Clock | None,
        function: TaskFunction,
        control: TaskControl,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._clock = clock
        self._function = function
        self.control = control

    def run(self) -> None:
        try:
            with open_app(self._paths, self._clock, recover=False) as ctx:
                result = self._function(ctx, self.control, self.message.emit)
        except Cancelled:
            self.cancelled.emit()
        except MtlmError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            log.error("Tâche en échec :\n%s", traceback.format_exc())
            self.failed.emit(f"Erreur inattendue : {exc}")
        else:
            self.succeeded.emit(result)


# ---- tableaux -----------------------------------------------------------------------------------
#: Mots-clés de statut → ton du badge (le premier ton qui correspond l'emporte).
BADGE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "danger",
        ("échec", "failed", "erreur", "error", "rejetée", "corrompue", "non admissible", "refus"),
    ),
    (
        "warning",
        (
            "à vérifier",
            "a_verifier",
            "interrompue",
            "pause",
            "annulée",
            "cancelled",
            "moyenne",
            "conflict",
            "conflit",
            "admissible",
            "partial",
            "stale",
            "avec un autre robot",
            "corbeille",
        ),
    ),
    (
        "success",
        (
            "terminée",
            "completed",
            "forte",
            "acceptée",
            "verified",
            "vérifiée",
            "validated",
            "saine",
            "référence",
            "restored",
            "restaurée",
            "certain",
            "oui",
            "avec son robot",
            "remis en place",
        ),
    ),
    (
        "info",
        (
            "en cours",
            "running",
            "copying",
            "simulated",
            "preview",
            "planned",
            "probable",
            "copie",
            "en vrac",
        ),
    ),
]


def badge_tone(text: str) -> str:
    lowered = text.lower()
    for tone, words in BADGE_RULES:
        if any(word in lowered for word in words):
            return tone
    return "neutral"


class BadgeDelegate(QStyledItemDelegate):
    """Affiche la valeur d'une cellule de statut comme une pastille colorée arrondie."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        from mtlm.ui.theme import TONES

        text = str(index.data() or "")
        if not text:
            super().paint(painter, option, index)
            return
        painter.save()
        # Les annotations de PySide6 6.9 omettent state/rect/font (présents à l'exécution).
        opt: Any = option
        if opt.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(opt.rect, QColor(59, 130, 246, 46))
        color, soft = TONES[badge_tone(text)]
        font = QFont(opt.font)
        font.setPointSizeF(max(opt.font.pointSizeF() - 1.0, 9.0))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = min(metrics.horizontalAdvance(text) + 20, opt.rect.width() - 12)
        height = metrics.height() + 6
        rect = QRectF(opt.rect.x() + 8, opt.rect.center().y() - height / 2 + 1, width, height)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(color)
        background.setAlpha(40)
        painter.setBrush(background)
        border = QColor(color)
        border.setAlpha(110)
        painter.setPen(border)
        painter.drawRoundedRect(rect, height / 2, height / 2)
        painter.setPen(QColor(color).lighter(115))
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width - 14))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, elided)
        painter.restore()
        _ = soft

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + 24, max(hint.height(), 30))


def make_table(headers: Sequence[str], badge_columns: Sequence[int] = ()) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels([h.upper() for h in headers])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(40)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    table.horizontalHeader().setHighlightSections(False)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setAlternatingRowColors(True)
    table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    delegate = BadgeDelegate(table)
    for column in badge_columns:
        table.setItemDelegateForColumn(column, delegate)
    table.setProperty("badge_delegate", delegate)
    return table


def fill_table(table: QTableWidget, rows: Sequence[Sequence[Any]]) -> None:
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem("" if value is None else str(value))
            if isinstance(value, int | float) and not isinstance(value, bool):
                item.setData(Qt.ItemDataRole.EditRole, value)
            table.setItem(r, c, item)
    table.resizeColumnsToContents()


def selected_value(table: QTableWidget, column: int = 0) -> str | None:
    rows = table.selectionModel().selectedRows()
    if not rows:
        return None
    item = table.item(rows[0].row(), column)
    return item.text() if item is not None else None
