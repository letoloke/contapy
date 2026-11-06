"""Visual language for the ContaPy app.

The palette mirrors the dark, low-chrome dashboard in the design reference:
warm graphite panels, hairline borders, a single blue selection accent and
green/orange figures for positive/negative money.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent / "assets"


class C:
    """Colour tokens."""

    BG = "#333333"
    PANEL = "#2b2b2b"
    PANEL_RAISED = "#303030"
    HEADER = "#2b2b2b"
    BORDER = "#1b1b1b"
    BORDER_SOFT = "#3b3b3b"
    GRID = "#3a3a3a"
    GRID_ZERO = "#4d4d4d"

    TEXT = "#efefef"
    TEXT_SOFT = "#d8d8d8"
    MUTED = "#9c9c9c"
    MUTED_DARK = "#7c7c7c"

    ACCENT = "#24518d"
    ACCENT_LIGHT = "#2e5f9e"
    ACCENT_HOVER = "#2c5f9f"

    GREEN = "#4e9f3f"
    GREEN_BAR = "#5c9736"
    ORANGE = "#d9822b"
    RED_BAR = "#b0292b"
    WARNING = "#e5a93f"
    INFO = "#3f7fbf"

    ROW_HOVER = "#363636"
    ROW_SELECTED = "#24518d"
    TOTAL_ROW = "#2e2e2e"


# Category colours sampled from the reference donut.
CATEGORY_COLORS = {
    "renta": "#4571a6",
    "nomina": "#acbdce",
    "Retiro de efectivo": "#d87921",
    "Impuestos": "#e4b276",
    "suscripciones": "#5c9736",
    "alimentos": "#aecf96",
    "manto": "#b0292b",
    "comision": "#dc9193",
    "servicios": "#7d64ac",
    "bebes": "#b5a6cb",
    "Other": "#77544d",
    "Ingresos": "#5c9736",
}

DONUT_COLORS = [
    "#4571a6",
    "#acbdce",
    "#d87921",
    "#e4b276",
    "#5c9736",
    "#aecf96",
    "#b0292b",
    "#dc9193",
    "#7d64ac",
    "#b5a6cb",
    "#77544d",
]

_FONT_FAMILY: str | None = None
_EMOJI_FAMILY: str | None = None


def font_family() -> str:
    global _FONT_FAMILY
    if _FONT_FAMILY is None:
        available = set(QFontDatabase.families())
        for candidate in (
            "Inter",
            "SF Pro Text",
            "Noto Sans",
            "Cantarell",
            "IBM Plex Sans",
            "DejaVu Sans",
        ):
            if candidate in available:
                _FONT_FAMILY = candidate
                break
        else:
            _FONT_FAMILY = QApplication.font().family()
    return _FONT_FAMILY


def emoji_family() -> str:
    global _EMOJI_FAMILY
    if _EMOJI_FAMILY is None:
        available = set(QFontDatabase.families())
        for candidate in (
            "Noto Color Emoji",
            "Apple Color Emoji",
            "Segoe UI Emoji",
            "Twemoji",
        ):
            if candidate in available:
                _EMOJI_FAMILY = candidate
                break
        else:
            _EMOJI_FAMILY = ""
    return _EMOJI_FAMILY


def font(size: int = 14, weight: int = 400, family: str | None = None) -> QFont:
    f = QFont(family or font_family())
    f.setPixelSize(size)
    weights = {
        400: QFont.Weight.Normal,
        500: QFont.Weight.Medium,
        600: QFont.Weight.DemiBold,
        700: QFont.Weight.Bold,
    }
    f.setWeight(weights.get(weight, QFont.Weight.Normal))
    # Line up digits in tables where the platform font supports it.
    try:
        f.setFeature(QFont.Tag("tnum"), 1)
    except Exception:
        pass
    return f


def qcolor(token: str, alpha: int | None = None) -> QColor:
    color = QColor(token)
    if alpha is not None:
        color.setAlpha(alpha)
    return color


def emoji_pixmap(char: str, logical: int = 22, dpr: float = 2.0) -> QPixmap:
    """Render a colour emoji to a transparent, HiDPI-friendly pixmap."""
    px = int(round(logical * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = _make_painter(pm)
    f = QFont(emoji_family() or "Noto Color Emoji")
    f.setPixelSize(int(px * 0.9))
    painter.setFont(f)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRectF(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, char)
    painter.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _make_painter(pixmap: QPixmap):
    from PySide6.QtGui import QPainter

    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    return p


def stylesheet() -> str:
    chevron = (ASSETS / "chevron-down.svg").as_posix()
    check = (ASSETS / "check.svg").as_posix()
    return f"""
    QWidget {{
        color: {C.TEXT};
    }}
    QMainWindow {{
        background: {C.BG};
    }}
    QToolTip {{
        background: #1f1f1f;
        color: #f0f0f0;
        border: 1px solid #454545;
        padding: 6px 9px;
        border-radius: 4px;
        font-size: 13px;
    }}
    QMenuBar {{
        background: {C.BG};
        color: #ededed;
        padding: 0px 2px;
        border: none;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 3px 7px;
        border-radius: 3px;
    }}
    QMenuBar::item:selected {{
        background: #414141;
    }}
    QMenuBar::item:pressed {{
        background: {C.ACCENT};
    }}
    QMenu {{
        background: #2b2b2b;
        border: 1px solid #474747;
        padding: 6px;
    }}
    QMenu::item {{
        background: transparent;
        padding: 6px 28px 6px 14px;
        border-radius: 4px;
        color: #e6e6e6;
    }}
    QMenu::item:selected {{
        background: {C.ACCENT};
        color: #ffffff;
    }}
    QMenu::item:disabled {{
        color: #6f6f6f;
    }}
    QMenu::separator {{
        height: 1px;
        background: #3d3d3d;
        margin: 5px 8px;
    }}
    QToolButton {{
        background: transparent;
        border: none;
        border-radius: 5px;
        padding: 2px;
    }}
    QToolButton:hover {{
        background: #414141;
    }}
    QToolButton:pressed {{
        background: #4a4a4a;
    }}
    QPushButton {{
        background: #363636;
        color: #e7e7e7;
        border: 1px solid #4b4b4b;
        border-radius: 4px;
        padding: 5px 14px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: #3f3f3f;
    }}
    QPushButton:pressed {{
        background: #474747;
    }}
    QPushButton[role="primary"] {{
        background: {C.ACCENT};
        border-color: #3a6cae;
        color: #ffffff;
    }}
    QPushButton[role="primary"]:hover {{
        background: {C.ACCENT_LIGHT};
    }}
    QPushButton:disabled {{
        color: #6d6d6d;
        background: #303030;
        border-color: #3e3e3e;
    }}
    QPushButton[role="action"] {{
        background: #343434;
        color: #d6d6d6;
        border: 1px solid #505050;
        border-radius: 4px;
        padding: 4px 7px;
        font-size: 13px;
    }}
    QPushButton[role="action"]:hover {{
        background: #3e3e3e;
        border-color: #5c5c5c;
    }}
    QPushButton[role="action"]:disabled {{
        color: #6f6f6f;
        background: #303030;
        border-color: #3f3f3f;
    }}
    QLineEdit, QDateEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
        background: #242424;
        color: #ededed;
        border: 1px solid #4a4a4a;
        border-radius: 4px;
        padding: 5px 8px;
        selection-background-color: {C.ACCENT};
        font-size: 13px;
    }}
    QLineEdit:focus, QDateEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: #4a7fc4;
    }}
    QComboBox {{
        padding-right: 24px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox::down-arrow {{
        image: url("{chevron}");
        width: 10px;
        height: 6px;
    }}
    QComboBox QAbstractItemView {{
        background: #2b2b2b;
        color: #e8e8e8;
        border: 1px solid #4a4a4a;
        selection-background-color: {C.ACCENT};
        selection-color: #ffffff;
        outline: 0;
        padding: 4px;
    }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0px;
        border: none;
    }}
    QCheckBox {{
        color: #dcdcdc;
        spacing: 7px;
        font-size: 13px;
    }}
    QDialog {{
        background: {C.PANEL};
    }}
    QLabel {{
        background: transparent;
    }}
    QScrollArea {{
        background: {C.PANEL};
        border: none;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px 1px;
    }}
    QScrollBar::handle:vertical {{
        background: #4a4a4a;
        min-height: 26px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #575757;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        height: 10px;
        background: transparent;
    }}
    QScrollBar::handle:horizontal {{
        background: #4a4a4a;
        min-width: 26px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid #555555;
        border-radius: 3px;
        background: #242424;
    }}
    QCheckBox::indicator:hover {{
        border-color: #6d6d6d;
    }}
    QCheckBox::indicator:checked {{
        background: {C.ACCENT};
        border-color: #4a7fc4;
        image: url("{check}");
    }}
    QTableView {{
        background: {C.PANEL};
        color: {C.TEXT};
        border: none;
        selection-background-color: transparent;
        gridline-color: #363636;
    }}
    QHeaderView::section {{
        background: {C.PANEL};
        color: {C.MUTED};
        border: none;
        border-bottom: 1px solid {C.BORDER};
        padding: 0px 8px;
        font-size: 12px;
    }}
    QTableCornerButton::section {{
        background: {C.PANEL};
        border: none;
    }}
    QListWidget {{
        background: #242424;
        border: 1px solid #444444;
        border-radius: 4px;
        color: #e6e6e6;
        outline: 0;
    }}
    QListWidget::item {{
        padding: 6px 8px;
    }}
    QListWidget::item:selected {{
        background: {C.ACCENT};
        color: white;
    }}
    QMessageBox {{
        background: {C.PANEL};
    }}
    QMessageBox QLabel {{
        color: #e9e9e9;
    }}
    """


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(font(14))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C.BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor("#242424"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C.PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1f1f1f"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor("#343434"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C.ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(C.MUTED_DARK))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6f6f6f"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6f6f6f"))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())
