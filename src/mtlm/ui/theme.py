"""Thème visuel « Sombre Pro » (direction artistique FinTech) de l'application.

* fond nuit profond ``#0B0F19``, cartes légèrement surélevées ``#131C31`` aux bordures fines ;
* hiérarchie nette : titres blanc éclatant, textes secondaires gris doux ;
* accents bleu → indigo (dégradé) pour les actions principales ;
* couleurs de statut : succès (vert), alerte (ambre), danger (rouge), information (bleu),
  utilisées pour les cartes KPI (liseré + lueur) et les badges des tableaux.

Rôles de boutons : ``primary`` (action principale), ``big`` (action d'étape), ``danger``,
``ghost`` (action discrète). Tons de cartes : ``success``, ``warning``, ``danger``, ``info``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget


@dataclass(frozen=True)
class Palette:
    background: str = "#0B0F19"
    sidebar: str = "#080C15"
    surface: str = "#131C31"
    surface_raised: str = "#18233D"
    surface_alt: str = "#0F1729"
    border: str = "#1F2A44"
    border_strong: str = "#2B3A5C"
    title: str = "#F8FAFC"
    text: str = "#E2E8F0"
    muted: str = "#8B97B0"
    faint: str = "#5B6784"
    accent: str = "#3B82F6"
    accent_2: str = "#6366F1"
    accent_hover: str = "#60A5FA"
    accent_hover_2: str = "#818CF8"
    accent_soft: str = "#172554"
    success: str = "#22C55E"
    success_soft: str = "#0F2A1E"
    warning: str = "#F59E0B"
    warning_soft: str = "#2D2210"
    danger: str = "#EF4444"
    danger_soft: str = "#2D1416"
    info: str = "#38BDF8"
    info_soft: str = "#0C2437"


PRO = Palette()

#: Couleur de chaque ton (liseré, lueur, badge).
TONES = {
    "success": (PRO.success, PRO.success_soft),
    "warning": (PRO.warning, PRO.warning_soft),
    "danger": (PRO.danger, PRO.danger_soft),
    "info": (PRO.accent, PRO.accent_soft),
    "neutral": (PRO.muted, PRO.surface_alt),
}


def current_palette() -> Palette:
    return PRO


def stylesheet(p: Palette) -> str:
    grad = f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent}, stop:1 {p.accent_2})"
    grad_hover = (
        f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent_hover}, "
        f"stop:1 {p.accent_hover_2})"
    )
    return f"""
* {{ outline: none; }}
QMainWindow, QWidget#central, QWidget#content, QStackedWidget {{ background: {p.background}; }}
QWidget {{ color: {p.text}; font-size: 13px; background: transparent; }}
QToolTip {{ background: {p.surface_raised}; color: {p.text}; border: 1px solid {p.border_strong};
           border-radius: 6px; padding: 6px 8px; }}
QLabel#pageTitle {{ color: {p.title}; font-size: 26px; font-weight: 700;
                    letter-spacing: -0.3px; }}
QLabel#pageSubtitle {{ color: {p.muted}; font-size: 13px; }}
QLabel#muted {{ color: {p.muted}; }}
QLabel#sectionTitle {{ color: {p.title}; font-size: 15px; font-weight: 600; }}

/* ---------- Barre latérale ---------- */
QWidget#sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
QLabel#brand {{ color: {p.title}; font-size: 15px; font-weight: 700; }}
QLabel#brandSub {{ color: {p.faint}; font-size: 11px; }}
QListWidget#navigation {{ background: transparent; border: none; color: {p.muted};
                          font-size: 13px; }}
QListWidget#navigation::item {{ padding: 9px 12px; margin: 2px 6px; border-radius: 9px;
                                border-left: 3px solid transparent; }}
QListWidget#navigation::item:selected {{ background: rgba(59,130,246,0.14); color: {p.title};
                                         border-left: 3px solid {p.accent}; }}
QListWidget#navigation::item:hover:!selected {{ background: rgba(255,255,255,0.04);
                                                color: {p.text}; }}
QListWidget#navigation::item:disabled {{ color: {p.faint}; font-size: 10px; font-weight: 700;
                                         padding: 18px 12px 6px 12px; letter-spacing: 1px;
                                         background: transparent; border: none; }}

/* ---------- Cartes ---------- */
QFrame#card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 16px; }}
QFrame#card:hover {{ border: 1px solid {p.border_strong}; }}
QFrame#card[tone="success"] {{ border: 1px solid rgba(34,197,94,0.45);
                               border-top: 3px solid {p.success}; }}
QFrame#card[tone="warning"] {{ border: 1px solid rgba(245,158,11,0.45);
                               border-top: 3px solid {p.warning}; }}
QFrame#card[tone="danger"] {{ border: 1px solid rgba(239,68,68,0.45);
                              border-top: 3px solid {p.danger}; }}
QFrame#card[tone="info"] {{ border: 1px solid rgba(59,130,246,0.35);
                            border-top: 3px solid {p.accent}; }}
QFrame#card[state="done"] {{ border: 1px solid rgba(34,197,94,0.55); }}
QFrame#card[state="current"] {{ border: 1px solid {p.accent}; }}
QLabel#cardTitle {{ color: {p.muted}; font-size: 12px; font-weight: 600; letter-spacing: 0.2px; }}
QLabel#cardValue {{ color: {p.title}; font-size: 30px; font-weight: 700;
                    letter-spacing: -0.5px; }}
QLabel#cardText {{ color: {p.muted}; }}
QLabel#cardHint {{ color: {p.faint}; font-size: 11px; }}
QLabel#stepNumber {{ background: {p.accent_soft}; color: {p.accent_hover}; border-radius: 17px;
                     font-weight: 700; font-size: 15px; min-width: 34px; max-width: 34px;
                     min-height: 34px; max-height: 34px; }}
QLabel#stepNumber[state="done"] {{ background: {p.success_soft}; color: {p.success}; }}
QLabel#badgeOk {{ color: {p.success}; font-weight: 600; }}
QLabel#badgeTodo {{ color: {p.muted}; font-weight: 600; }}
QFrame#banner {{ background: {p.accent_soft}; border: 1px solid rgba(59,130,246,0.30);
                 border-radius: 12px; }}
QFrame#bannerSafe {{ background: {p.success_soft}; border: 1px solid rgba(34,197,94,0.30);
                     border-radius: 12px; }}
QFrame#bannerWarn {{ background: {p.warning_soft}; border: 1px solid rgba(245,158,11,0.30);
                     border-radius: 12px; }}

/* ---------- Boutons ---------- */
QPushButton {{ background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
               border-radius: 10px; padding: 9px 16px; font-weight: 600; }}
QPushButton:hover {{ background: {p.surface_raised}; border-color: {p.accent};
                     color: {p.title}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:focus {{ border-color: {p.accent}; }}
QPushButton:disabled {{ color: {p.faint}; background: {p.surface_alt};
                        border-color: {p.border}; }}
QPushButton[role="primary"], QPushButton[role="big"] {{ background: {grad}; color: #FFFFFF;
                                                         border: none; }}
QPushButton[role="primary"]:hover, QPushButton[role="big"]:hover {{ background: {grad_hover};
                                                                     color: #FFFFFF; }}
QPushButton[role="primary"]:pressed, QPushButton[role="big"]:pressed {{ background: {p.accent_2}; }}
QPushButton[role="big"] {{ font-size: 14px; padding: 12px 20px; border-radius: 12px; }}
QPushButton[role="danger"] {{ background: transparent; color: {p.danger};
                              border: 1px solid rgba(239,68,68,0.55); }}
QPushButton[role="danger"]:hover {{ background: {p.danger_soft}; color: #FCA5A5;
                                    border-color: {p.danger}; }}
QPushButton[role="ghost"] {{ background: transparent; border: none; color: {p.accent_hover};
                             padding: 6px 8px; }}
QPushButton[role="ghost"]:hover {{ color: {p.title}; background: rgba(59,130,246,0.12); }}

/* ---------- Champs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {p.surface_alt};
    border: 1px solid {p.border_strong}; border-radius: 10px; padding: 8px 12px;
    color: {p.text}; selection-background-color: {p.accent}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {p.accent}; background: {p.surface}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {p.surface_raised}; border: 1px solid {p.border_strong};
    selection-background-color: {p.accent_soft}; color: {p.text}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button,
QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox {{ spacing: 9px; color: {p.text}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px;
                        border: 1px solid {p.border_strong}; background: {p.surface_alt}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
QPlainTextEdit, QTextBrowser {{ background: {p.surface}; border: 1px solid {p.border};
    border-radius: 14px; padding: 12px; color: {p.text};
    selection-background-color: {p.accent}; }}
QGroupBox {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 16px;
             margin-top: 22px; padding: 16px; color: {p.text}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 16px; padding: 0 6px; color: {p.muted};
                    font-weight: 600; }}

/* ---------- Tableaux ---------- */
QTableWidget {{ background: {p.surface}; alternate-background-color: rgba(255,255,255,0.018);
    border: 1px solid {p.border}; border-radius: 14px; gridline-color: transparent;
    selection-background-color: rgba(59,130,246,0.18); selection-color: {p.title};
    color: {p.text}; }}
QTableWidget::item {{ padding: 6px 12px; border: none;
                      border-bottom: 1px solid rgba(255,255,255,0.03); }}
QTableWidget::item:hover {{ background: rgba(255,255,255,0.03); }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: {p.surface_alt}; color: {p.faint}; border: none;
    border-bottom: 1px solid {p.border}; padding: 10px 12px; font-weight: 700;
    font-size: 11px; letter-spacing: 0.6px; }}
QHeaderView::section:first {{ border-top-left-radius: 14px; }}
QTableCornerButton::section {{ background: {p.surface_alt}; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 9px 18px; margin-right: 6px; color: {p.muted};
                border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {p.title}; border-bottom: 2px solid {p.accent}; }}
QTabBar::tab:hover:!selected {{ color: {p.text}; }}

QProgressBar {{ background: {p.surface_alt}; border: none; border-radius: 5px; height: 8px;
                max-height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {grad}; border-radius: 5px; }}
QStatusBar {{ background: {p.sidebar}; color: {p.faint}; border-top: 1px solid {p.border}; }}
QStatusBar QLabel {{ color: {p.faint}; }}
QMenuBar {{ background: {p.sidebar}; color: {p.muted}; }}
QMenuBar::item:selected {{ background: {p.surface}; }}
QMenu {{ background: {p.surface_raised}; border: 1px solid {p.border_strong}; padding: 6px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.accent_soft}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 4px;
                               min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px;
                                 min-width: 32px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent; height: 0; width: 0; }}
QMessageBox, QFileDialog, QDialog {{ background: {p.surface}; }}
"""


def glow(widget: QWidget, tone: str | None, strength: int = 70) -> None:
    """Lueur douce autour d'une carte selon son ton (aucune si ``tone`` est vide)."""
    if not tone or tone == "neutral":
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(24)
        effect.setOffset(0, 6)
        effect.setColor(QColor(0, 0, 0, 90))
        widget.setGraphicsEffect(effect)
        return
    color = QColor(TONES.get(tone, TONES["info"])[0])
    color.setAlpha(strength)
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(32)
    effect.setOffset(0, 0)
    effect.setColor(color)
    widget.setGraphicsEffect(effect)


def app_icon(size: int = 256) -> QIcon:
    """Icône de l'application dessinée (aucun fichier externe) : chandeliers + coche."""
    return QIcon(icon_pixmap(size))


def icon_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    gradient = QLinearGradient(0, 0, s, s)
    gradient.setColorAt(0.0, QColor("#3B7BFF"))
    gradient.setColorAt(1.0, QColor("#1A2C6B"))
    painter.setBrush(gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    margin = s * 0.06
    painter.drawRoundedRect(
        QRectF(margin, margin, s - 2 * margin, s - 2 * margin), s * 0.22, s * 0.22
    )
    candles = [
        (0.27, 0.36, 0.62, 0.30, 0.72, "#FFFFFF"),
        (0.45, 0.30, 0.52, 0.22, 0.66, "#9CC1FF"),
        (0.63, 0.24, 0.44, 0.16, 0.56, "#FFFFFF"),
    ]
    for x, top, bottom, wick_top, wick_bottom, color in candles:
        painter.setPen(QColor(color))
        pen = painter.pen()
        pen.setWidthF(s * 0.018)
        painter.setPen(pen)
        painter.drawLine(
            int(s * (x + 0.045)), int(s * wick_top), int(s * (x + 0.045)), int(s * wick_bottom)
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(
            QRectF(s * x, s * top, s * 0.09, s * (bottom - top)), s * 0.015, s * 0.015
        )
    painter.setBrush(QColor("#2BC47A"))
    painter.drawEllipse(QRectF(s * 0.58, s * 0.58, s * 0.30, s * 0.30))
    pen = painter.pen()
    painter.setPen(QColor("#FFFFFF"))
    pen = painter.pen()
    pen.setWidthF(s * 0.035)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(int(s * 0.655), int(s * 0.73), int(s * 0.715), int(s * 0.79))
    painter.drawLine(int(s * 0.715), int(s * 0.79), int(s * 0.815), int(s * 0.67))
    painter.end()
    return pixmap


def apply_theme(app: QApplication) -> Palette:
    """Applique le thème « Sombre Pro » (police moderne, feuille de style, icône)."""
    palette = current_palette()
    font = QFont()
    font.setFamilies(
        ["Inter", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue", "Segoe UI", "Arial"]
    )
    font.setPointSizeF(max(app.font().pointSizeF(), 12.5))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    qt_palette = app.palette()
    for role, value in (
        (QPalette.ColorRole.Window, palette.background),
        (QPalette.ColorRole.Base, palette.surface_alt),
        (QPalette.ColorRole.Text, palette.text),
        (QPalette.ColorRole.WindowText, palette.text),
        (QPalette.ColorRole.PlaceholderText, palette.faint),
        (QPalette.ColorRole.Highlight, palette.accent),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF"),
        (QPalette.ColorRole.Button, palette.surface),
        (QPalette.ColorRole.ButtonText, palette.text),
    ):
        qt_palette.setColor(role, QColor(value))
    app.setPalette(qt_palette)
    app.setStyleSheet(stylesheet(palette))
    app.setWindowIcon(app_icon())
    return palette
