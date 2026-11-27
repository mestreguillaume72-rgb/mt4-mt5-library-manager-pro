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
    QLabel,
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
from mtlm.core.i18n import tr
from mtlm.core.paths import AppPaths

log = logging.getLogger("mtlm.ui")


# ---- dialogues (remplaçables dans les tests) -----------------------------------------------
class Dialogs(Protocol):
    def choose_directory(self, parent: QWidget, title: str) -> Path | None: ...
    def save_file(self, parent: QWidget, title: str, suggestion: str) -> Path | None: ...
    def confirm(self, parent: QWidget, title: str, text: str) -> bool: ...
    def info(self, parent: QWidget, title: str, text: str) -> None: ...
    def error(self, parent: QWidget, title: str, text: str) -> None: ...
    def ask_text(self, parent: QWidget, title: str, text: str, default: str = "") -> str | None:
        """Texte saisi par l'utilisateur (nom d'un groupe…), ou ``None`` s'il annule."""
        ...

    def choose_items(
        self, parent: QWidget, title: str, text: str, items: list[tuple[str, str]]
    ) -> list[str] | None:
        """Liste à cocher : (clé, libellé). Retourne les clés cochées, ou ``None`` si
        l'utilisateur annule. Rien n'est coché d'avance : chaque lien est validé par lui."""
        ...


class QtDialogs:
    def choose_directory(self, parent: QWidget, title: str) -> Path | None:
        chosen = QFileDialog.getExistingDirectory(parent, title)
        return Path(chosen) if chosen else None

    def save_file(self, parent: QWidget, title: str, suggestion: str) -> Path | None:
        chosen, _ = QFileDialog.getSaveFileName(
            parent, title, suggestion, tr("CSV (*.csv);;JSON (*.json);;JSONL (*.jsonl)")
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

    def ask_text(self, parent: QWidget, title: str, text: str, default: str = "") -> str | None:
        from PySide6.QtWidgets import QInputDialog

        value, ok = QInputDialog.getText(parent, title, text, text=default)
        return value if ok else None

    def choose_items(
        self, parent: QWidget, title: str, text: str, items: list[tuple[str, str]]
    ) -> list[str] | None:
        from PySide6.QtWidgets import (
            QDialog,
            QDialogButtonBox,
            QHBoxLayout,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QPushButton,
            QVBoxLayout,
        )

        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.resize(760, 520)
        layout = QVBoxLayout(dialog)
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        listing = QListWidget()
        for key, caption in items:
            item = QListWidgetItem(caption)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            listing.addItem(item)
        listing.itemClicked.connect(
            lambda it: it.setCheckState(
                Qt.CheckState.Unchecked
                if it.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
        )
        layout.addWidget(listing, 1)
        row = QHBoxLayout()
        for caption, state in (
            (tr("Tout cocher"), Qt.CheckState.Checked),
            (tr("Tout décocher"), Qt.CheckState.Unchecked),
        ):
            button = QPushButton(caption)

            def set_all(_checked: bool = False, value: Qt.CheckState = state) -> None:
                for index in range(listing.count()):
                    listing.item(index).setCheckState(value)

            button.clicked.connect(set_all)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Valider"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Annuler"))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return [
            str(listing.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(listing.count())
            if listing.item(i).checkState() == Qt.CheckState.Checked
        ]


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
    "sources_mq.isoler": "primary",
    "sources_mq.isoler_tout": "primary",
}


@dataclass
class ActionSpec:
    action_id: str
    label: str
    handler: Callable[[], None] | None
    reason_unavailable: str | None = None
    calls: int = 0
    tooltip: str = ""


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
            raise ValueError(tr("Action en double : {action_id}", action_id=action_id))
        from mtlm.ui.bulles import ACTION_TIPS

        tip = (
            tr(ACTION_TIPS.get(action_id) or tooltip)
            if (ACTION_TIPS.get(action_id) or tooltip)
            else ""
        )
        spec = ActionSpec(action_id, label, handler, tooltip=tip)
        self.specs[action_id] = spec
        button = QPushButton(label)
        button.setObjectName(action_id)
        button.setAccessibleName(label)
        button.setToolTip(tip or label)
        if tip:
            button.setAccessibleDescription(tip)
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
        button = QPushButton(tr("{label} (non disponible)", label=label))
        button.setObjectName(action_id)
        button.setEnabled(False)
        button.setToolTip(tr("Non disponible : {reason}", reason=reason))
        button.setAccessibleName(tr("{label} (non disponible)", label=label))
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
            self.failed.emit(tr("Erreur inattendue : {exc}", exc=exc))
        else:
            self.succeeded.emit(result)


# ---- tableaux -----------------------------------------------------------------------------------
#: Mots-clés de statut → ton du badge (le premier ton qui correspond l'emporte).
BADGE_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "danger",
        (
            "échec",
            "failed",
            "erreur",
            "error",
            "rejetée",
            "corrompue",
            "non admissible",
            "refus",
            # anglais, espagnol (1.9.0)
            "failure",
            "rejected",
            "corrupt",
            "not eligible",
            "refused",
            "fallo",
            "rechaz",
            "corrupt",
            "no admisible",
        ),
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
            "avec un autre outil",
            "corbeille",
            "to check",
            "to review",
            "interrupted",
            "paused",
            "canceled",
            "medium",
            "eligible",
            "with another robot",
            "with another tool",
            "trash",
            "por verificar",
            "a revisar",
            "interrumpid",
            "pausa",
            "cancelad",
            "media",
            "conflicto",
            "admisible",
            "con otro robot",
            "con otra herramienta",
            "papelera",
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
            "avec son outil",
            "dossier metatrader prévu",
            "remis en place",
            "done",
            "finished",
            "strong",
            "accepted",
            "healthy",
            "reference",
            "yes",
            "with its robot",
            "with its tool",
            "metatrader folder",
            "put back",
            "terminad",
            "completad",
            "fuerte",
            "aceptad",
            "verificad",
            "referencia",
            "restaurad",
            "cierto",
            "sí",
            "con su robot",
            "con su herramienta",
            "carpeta de metatrader",
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
            "in progress",
            "copy",
            "loose",
            "en curso",
            "copia",
            "suelto",
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


def _plural(count: int, noun: str) -> str:
    if count < 2 or noun.endswith(("s", "x")):
        return noun
    return noun + "s"


def update_count(table: QTableWidget) -> None:
    """« 1 234 fichiers — 3 sélectionnés » sous la liste (1.6.0)."""
    label = getattr(table, "count_label", None)
    if label is None:
        return
    noun = str(getattr(table, "count_noun", "élément"))
    total = table.rowCount()
    text = f"{total:,} {tr(_plural(total, noun))}".replace(",", " ")
    model = table.selectionModel()
    chosen = len(model.selectedRows()) if model is not None else 0
    if chosen:
        text += f" — {chosen:,} {tr(_plural(chosen, 'sélectionné'))}".replace(",", " ")
    label.setText(text)


def make_table(
    headers: Sequence[str],
    badge_columns: Sequence[int] = (),
    *,
    multi: bool = False,
    noun: str = "élément",
) -> QTableWidget:
    """``multi`` : sélection de plusieurs lignes **au simple clic** (chaque clic ajoute ou
    retire la ligne, sans clavier) ; Cmd+A ou Ctrl+A sélectionne tout. ``noun`` : ce que compte la
    liste (« fichier », « groupe »…), affiché sous elle avec le nombre sélectionné."""
    table = QTableWidget(0, len(headers))
    count = QLabel(f"0 {noun}")
    count.setObjectName("cardHint")
    count.setAccessibleName(tr("Nombre d'éléments de la liste"))
    table.count_label = count  # type: ignore[attr-defined]
    table.count_noun = noun  # type: ignore[attr-defined]
    table.itemSelectionChanged.connect(lambda: update_count(table))
    table.setHorizontalHeaderLabels([h.upper() for h in headers])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.MultiSelection
        if multi
        else QAbstractItemView.SelectionMode.SingleSelection
    )
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
    update_count(table)


def selected_value(table: QTableWidget, column: int = 0) -> str | None:
    rows = table.selectionModel().selectedRows()
    if not rows:
        return None
    item = table.item(rows[0].row(), column)
    return item.text() if item is not None else None


def selected_values(table: QTableWidget, column: int = 0) -> list[str]:
    """Valeurs de la colonne pour toutes les lignes sélectionnées, dans l'ordre affiché."""
    rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
    values = []
    for row in rows:
        item = table.item(row, column)
        if item is not None and item.text():
            values.append(item.text())
    return values
