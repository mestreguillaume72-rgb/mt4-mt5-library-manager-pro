"""Thème visuel de l'application : clair ou sombre (suit le réglage de macOS).

Une seule feuille de style, des couleurs nommées, et quelques rôles de boutons :
``primary`` (action principale), ``danger`` (action à risque), ``ghost`` (action discrète).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    dark: bool
    background: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    sidebar: str
    sidebar_text: str
    sidebar_muted: str


LIGHT = Palette(
    dark=False,
    background="#F4F6FA",
    surface="#FFFFFF",
    surface_alt="#F8FAFD",
    border="#E2E7EF",
    text="#18202F",
    muted="#5E6A80",
    accent="#2F6BEB",
    accent_hover="#2459C9",
    accent_soft="#E8F0FE",
    success="#178A50",
    success_soft="#E3F5EB",
    warning="#B7791F",
    warning_soft="#FDF3E1",
    danger="#C93B3B",
    danger_soft="#FCE9E9",
    sidebar="#141B2D",
    sidebar_text="#DCE3F1",
    sidebar_muted="#7F8BA3",
)
DARK = Palette(
    dark=True,
    background="#0F131B",
    surface="#181E2A",
    surface_alt="#1D2432",
    border="#2A3346",
    text="#E7EBF3",
    muted="#9AA5BA",
    accent="#4C84F5",
    accent_hover="#6A99F7",
    accent_soft="#1E2D4D",
    success="#3CC283",
    success_soft="#163626",
    warning="#E5A842",
    warning_soft="#3A2E17",
    danger="#EF6B6B",
    danger_soft="#3D1D1D",
    sidebar="#0B0F17",
    sidebar_text="#D3DAE8",
    sidebar_muted="#6F7A90",
)


def current_palette() -> Palette:
    hints = QGuiApplication.styleHints()
    scheme = getattr(hints, "colorScheme", None)
    if callable(scheme) and scheme() == Qt.ColorScheme.Dark:
        return DARK
    return LIGHT


def stylesheet(p: Palette) -> str:
    return f"""
QMainWindow, QWidget#central {{ background: {p.background}; }}
QWidget {{ color: {p.text}; font-size: 13px; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 700; }}
QLabel#pageSubtitle {{ color: {p.muted}; font-size: 13px; }}
QLabel#muted {{ color: {p.muted}; }}
QLabel#sectionTitle {{ font-size: 15px; font-weight: 600; margin-top: 6px; }}

/* Barre latérale */
QWidget#sidebar {{ background: {p.sidebar}; }}
QLabel#brand {{ color: #FFFFFF; font-size: 15px; font-weight: 700; }}
QLabel#brandSub {{ color: {p.sidebar_muted}; font-size: 11px; }}
QListWidget#navigation {{
    background: {p.sidebar}; border: none; outline: none; color: {p.sidebar_text};
    font-size: 13px;
}}
QListWidget#navigation::item {{ padding: 7px 10px; margin: 1px 8px; border-radius: 8px; }}
QListWidget#navigation::item:selected {{ background: {p.accent}; color: #FFFFFF; }}
QListWidget#navigation::item:hover:!selected {{ background: rgba(255,255,255,0.07); }}
QListWidget#navigation::item:disabled {{
    color: {p.sidebar_muted}; font-size: 11px; font-weight: 700; padding: 14px 10px 4px 10px;
    background: transparent;
}}

/* Cartes */
QFrame#card {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px;
}}
QFrame#card[state="done"] {{ border: 1px solid {p.success}; }}
QFrame#card[state="current"] {{ border: 2px solid {p.accent}; }}
QLabel#cardTitle {{ color: {p.muted}; font-size: 12px; font-weight: 600; }}
QLabel#cardValue {{ font-size: 28px; font-weight: 700; }}
QLabel#cardText {{ color: {p.muted}; }}
QLabel#stepNumber {{
    background: {p.accent_soft}; color: {p.accent}; border-radius: 16px; font-weight: 700;
    font-size: 15px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
}}
QLabel#stepNumber[state="done"] {{ background: {p.success_soft}; color: {p.success}; }}
QLabel#badgeOk {{ color: {p.success}; font-weight: 600; }}
QLabel#badgeTodo {{ color: {p.muted}; font-weight: 600; }}
QFrame#banner {{ background: {p.accent_soft}; border-radius: 12px; }}
QFrame#bannerSafe {{ background: {p.success_soft}; border-radius: 12px; }}
QFrame#bannerWarn {{ background: {p.warning_soft}; border-radius: 12px; }}

/* Boutons */
QPushButton {{
    background: {p.surface}; color: {p.text}; border: 1px solid {p.border};
    border-radius: 8px; padding: 7px 14px; font-weight: 500;
}}
QPushButton:hover {{ border-color: {p.accent}; color: {p.accent}; }}
QPushButton:pressed {{ background: {p.accent_soft}; }}
QPushButton:disabled {{ color: {p.muted}; background: {p.surface_alt}; }}
QPushButton[role="primary"] {{
    background: {p.accent}; color: #FFFFFF; border: 1px solid {p.accent}; font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background: {p.accent_hover}; color: #FFFFFF; }}
QPushButton[role="big"] {{
    background: {p.accent}; color: #FFFFFF; border: none; font-weight: 600; font-size: 14px;
    padding: 11px 18px; border-radius: 10px;
}}
QPushButton[role="big"]:hover {{ background: {p.accent_hover}; color: #FFFFFF; }}
QPushButton[role="danger"] {{ color: {p.danger}; border-color: {p.danger}; }}
QPushButton[role="danger"]:hover {{ background: {p.danger_soft}; }}
QPushButton[role="ghost"] {{ border: none; background: transparent; color: {p.accent}; }}

/* Champs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px;
    padding: 6px 9px; min-height: 18px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {p.accent};
}}
QCheckBox {{ spacing: 8px; }}
QPlainTextEdit, QTextBrowser {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; padding: 8px;
}}
QGroupBox {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px;
    margin-top: 18px; padding: 12px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; font-weight: 600; }}

/* Tableaux */
QTableWidget {{
    background: {p.surface}; alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border}; border-radius: 10px; gridline-color: transparent;
    selection-background-color: {p.accent_soft}; selection-color: {p.text};
}}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{
    background: {p.surface_alt}; color: {p.muted}; border: none;
    border-bottom: 1px solid {p.border}; padding: 7px 8px; font-weight: 600; font-size: 12px;
}}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; padding: 8px 16px; margin-right: 4px; color: {p.muted};
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {p.accent}; border-bottom: 2px solid {p.accent}; }}

QProgressBar {{
    background: {p.surface_alt}; border: 1px solid {p.border}; border-radius: 6px;
    height: 10px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 6px; }}
QStatusBar {{ background: {p.surface}; color: {p.muted}; border-top: 1px solid {p.border}; }}
QMenuBar {{ background: {p.surface}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


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
    palette = current_palette()
    font = app.font()
    if font.pointSizeF() < 12:
        font.setPointSizeF(12.5)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(stylesheet(palette))
    app.setWindowIcon(app_icon())
    return palette
