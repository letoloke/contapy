"""Visual language for the ContaPy app.

The palette follows the active Omarchy theme when one is available and falls
back to the original graphite dashboard palette otherwise.  Colours are
resolved once at startup into the semantic tokens on :class:`C`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from .omarchy import load_palette, set_theme_choice

ASSETS = Path(__file__).resolve().parent / "assets"

_PALETTE = load_palette()


class C:
    """Colour tokens resolved from the active Omarchy palette."""


for _token, _value in _PALETTE.tokens.items():
    setattr(C, _token, _value)
del _token, _value

CATEGORY_COLORS = dict(_PALETTE.category_colors)
DONUT_COLORS = list(_PALETTE.donut_colors)

# Cleared transactions keep a fixed colour regardless of the selected theme.
CLEARED = "#171b18"


def _install_palette(palette) -> None:
    """Refresh the shared colour tokens after a theme change."""
    global _PALETTE
    _PALETTE = palette
    for token, value in palette.tokens.items():
        setattr(C, token, value)
    CATEGORY_COLORS.clear()
    CATEGORY_COLORS.update(palette.category_colors)
    # Mutate in place: widgets imported this list by reference at import time.
    DONUT_COLORS[:] = list(palette.donut_colors)


def select_theme(choice: str) -> None:
    """Select and immediately install a theme palette."""
    set_theme_choice(choice)
    _install_palette(load_palette())


def selected_theme() -> str:
    from .omarchy import selected_theme as _selected_theme

    return _selected_theme()


def theme_options():
    from .omarchy import available_themes

    return available_themes()


def palette_source() -> str:
    """Human-readable description of where the colours came from."""
    return _PALETTE.source


def palette_mode() -> str:
    return _PALETTE.mode

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
    painter.setPen(QColor(C.TEXT))
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
        background: {C.TOOLTIP_BG};
        color: {C.TOOLTIP_TEXT};
        border: 1px solid {C.TOOLTIP_BORDER};
        padding: 6px 9px;
        border-radius: 4px;
        font-size: 13px;
    }}
    QMenuBar {{
        background: {C.BG};
        color: {C.TEXT};
        padding: 0px 2px;
        border: none;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 3px 7px;
        border-radius: 3px;
    }}
    QMenuBar::item:selected {{
        background: {C.MENUBAR_HOVER};
    }}
    QMenuBar::item:pressed {{
        background: {C.ACCENT};
    }}
    QMenu {{
        background: {C.MENU_BG};
        border: 1px solid {C.MENU_BORDER};
        padding: 6px;
    }}
    QMenu::item {{
        background: transparent;
        padding: 6px 28px 6px 14px;
        border-radius: 4px;
        color: {C.MENU_TEXT};
    }}
    QMenu::item:selected {{
        background: {C.MENU_SELECTED};
        color: {C.MENU_SELECTED_TEXT};
    }}
    QMenu::item:disabled {{
        color: {C.DISABLED};
    }}
    QMenu::separator {{
        height: 1px;
        background: {C.MENU_SEPARATOR};
        margin: 5px 8px;
    }}
    QToolButton {{
        background: transparent;
        border: none;
        border-radius: 5px;
        padding: 2px;
    }}
    QToolButton:hover {{
        background: {C.MENUBAR_HOVER};
    }}
    QToolButton:pressed {{
        background: {C.BUTTON_BG_PRESSED};
    }}
    QPushButton {{
        background: {C.BUTTON_BG};
        color: {C.BUTTON_TEXT};
        border: 1px solid {C.BUTTON_BORDER};
        border-radius: 4px;
        padding: 5px 14px;
        font-size: 13px;
    }}
    QPushButton:hover {{
        background: {C.BUTTON_BG_HOVER};
    }}
    QPushButton:pressed {{
        background: {C.BUTTON_BG_PRESSED};
    }}
    QPushButton[role="primary"] {{
        background: {C.ACCENT};
        border-color: {C.BUTTON_PRIMARY_BORDER};
        color: {C.ON_ACCENT};
    }}
    QPushButton[role="primary"]:hover {{
        background: {C.ACCENT_LIGHT};
    }}
    QPushButton:disabled {{
        color: {C.DISABLED};
        background: {C.DISABLED_BG};
        border-color: {C.DISABLED_BORDER};
    }}
    QPushButton[role="action"] {{
        background: {C.ACTION_BG};
        color: {C.ACTION_TEXT};
        border: 1px solid {C.ACTION_BORDER};
        border-radius: 4px;
        padding: 4px 7px;
        font-size: 13px;
    }}
    QPushButton[role="action"]:hover {{
        background: {C.ACTION_BG_HOVER};
        border-color: {C.BORDER_SOFT};
    }}
    QPushButton[role="action"]:disabled {{
        color: {C.DISABLED};
        background: {C.DISABLED_BG};
        border-color: {C.DISABLED_BORDER};
    }}
    QLineEdit, QDateEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
        background: {C.INPUT_BG};
        color: {C.INPUT_TEXT};
        border: 1px solid {C.INPUT_BORDER};
        border-radius: 4px;
        padding: 5px 8px;
        selection-background-color: {C.SELECTION};
        selection-color: {C.SELECTION_TEXT};
        font-size: 13px;
    }}
    QLineEdit:focus, QDateEdit:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {C.FOCUS_BORDER};
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
        background: {C.POPUP_BG};
        color: {C.POPUP_TEXT};
        border: 1px solid {C.POPUP_BORDER};
        selection-background-color: {C.SELECTION};
        selection-color: {C.SELECTION_TEXT};
        outline: 0;
        padding: 4px;
    }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 0px;
        border: none;
    }}
    QCheckBox {{
        color: {C.TEXT};
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
        background: {C.SCROLL_HANDLE};
        min-height: 26px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {C.SCROLL_HANDLE_HOVER};
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
        background: {C.SCROLL_HANDLE};
        min-width: 26px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {C.CHECK_BORDER};
        border-radius: 3px;
        background: {C.CHECK_BG};
    }}
    QCheckBox::indicator:hover {{
        border-color: {C.CHECK_HOVER};
    }}
    QCheckBox::indicator:checked {{
        background: {C.ACCENT};
        border-color: {C.FOCUS_BORDER};
        image: url("{check}");
    }}
    QTableView {{
        background: {C.PANEL};
        color: {C.TEXT};
        border: none;
        selection-background-color: transparent;
        gridline-color: {C.GRID};
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
        background: {C.LIST_BG};
        border: 1px solid {C.LIST_BORDER};
        border-radius: 4px;
        color: {C.TEXT};
        outline: 0;
    }}
    QListWidget::item {{
        padding: 6px 8px;
    }}
    QListWidget::item:selected {{
        background: {C.SELECTION};
        color: {C.SELECTION_TEXT};
    }}
    QMessageBox {{
        background: {C.PANEL};
    }}
    QMessageBox QLabel {{
        color: {C.TEXT};
    }}
    """


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setFont(font(14))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C.BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C.INPUT_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C.PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(C.TOOLTIP_BG))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(C.TOOLTIP_TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C.BUTTON_BG))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C.BUTTON_TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(C.TITLE))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C.SELECTION))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C.SELECTION_TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(C.MUTED_DARK))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(C.DISABLED))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(C.DISABLED))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())
