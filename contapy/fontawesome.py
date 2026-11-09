"""Font Awesome glyph helpers for the app's icons.

The bundled Free Solid font is loaded once at startup. Callers can paint a
glyph into an existing :class:`QPainter` or ask for a ready-made ``QPixmap`` /
``QIcon``. If the font cannot be loaded the helpers report ``False`` so the
painted fallbacks can still run.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

from .theme import C

ASSETS = Path(__file__).resolve().parent / "assets"
BUNDLED_FONT = ASSETS / "fa-solid-900.woff2"
SYSTEM_FONTS = (
    Path("/usr/share/fonts/WOFF2/fa-solid-900.woff2"),
    Path("/usr/share/fonts/TTF/fa-solid-900.ttf"),
    Path("/usr/share/fonts/opentype/fa-solid-900.otf"),
)

# Font Awesome Free 6 codepoints (the bundled font is pinned to that release).
GLYPHS: dict[str, int] = {
    "gear": 0xF013,
    "gears": 0xF085,
    "pencil": 0xF303,
    "download": 0xF019,
    "chevron-down": 0xF078,
    "chevron-up": 0xF077,
    "chevron-left": 0xF053,
    "chevron-right": 0xF054,
    "filter": 0xF0B0,
    "circle-info": 0xF05A,
    "circle-check": 0xF058,
    "circle-dot": 0xF192,
    "check": 0xF00C,
    "calendar-days": 0xF073,
    "triangle-exclamation": 0xF071,
    "plus": 0x002B,
    "clock": 0xF017,
    "bell": 0xF0F3,
    "flag": 0xF024,
    "magnifying-glass": 0xF002,
    "table": 0xF0CE,
    "chart-pie": 0xF200,
    "chart-column": 0xE0E3,
    "file-circle-plus": 0xE494,
    "folder-open": 0xF07C,
    "wallet": 0xF555,
    "tags": 0xF02C,
    "users": 0xF0C0,
    "money-bill-transfer": 0xE528,
    "keyboard": 0xF11C,
    "user-group": 0xF500,
    "building-columns": 0xF19C,
    "arrows-rotate": 0xF021,
    "bullseye": 0xF140,
    "heart": 0xF004,
    "sliders": 0xF1DE,
    "circle-plus": 0xF055,
    "list-check": 0xF0AE,
    "coins": 0xF51E,
    "money-bill-wave": 0xF53A,
    "arrow-right-arrow-left": 0xF0EC,
    "circle-question": 0xF059,
    "life-ring": 0xF1CD,
    "circle-half-stroke": 0xF042,
    "arrow-up": 0xF062,
    "arrow-down": 0xF063,
    "xmark": 0xF00D,
    "ban": 0xF05E,
    "file-lines": 0xF15C,
    "receipt": 0xF543,
    "piggy-bank": 0xF4D3,
    "landmark": 0xF66F,
    "tag": 0xF02B,
    "chart-line": 0xF201,
    "chart-simple": 0xE473,
    "table-list": 0xF00B,
}

_FAMILY: str | None = None
_LOADED = False


def _load_font() -> str | None:
    global _FAMILY, _LOADED
    if _LOADED:
        return _FAMILY
    _LOADED = True
    candidates = (BUNDLED_FONT, *SYSTEM_FONTS)
    for path in candidates:
        if not path.exists():
            continue
        index = QFontDatabase.addApplicationFont(str(path))
        if index < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(index)
        if families:
            _FAMILY = families[0]
            break
    return _FAMILY


def family() -> str | None:
    """Family name of the loaded Font Awesome face, or ``None``."""
    return _load_font()


def available() -> bool:
    return family() is not None


def glyph_font(pixel_size: int) -> QFont:
    face = QFont(family() or "sans-serif")
    face.setPixelSize(max(6, int(pixel_size)))
    return face


def draw_glyph(
    painter: QPainter,
    rect: QRectF,
    color: QColor | str | None,
    name: str,
    scale: float = 0.94,
) -> bool:
    """Paint ``name`` centred in ``rect``. Returns ``False`` when unavailable."""
    if family() is None:
        return False
    codepoint = GLYPHS.get(name)
    if codepoint is None:
        return False
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.setFont(glyph_font(round(rect.height() * scale)))
    painter.setPen(QColor(color) if color is not None else QColor(C.TEXT_SOFT))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, chr(codepoint))
    painter.restore()
    return True


def glyph_pixmap(
    name: str,
    logical: int = 22,
    color: str | None = None,
    dpr: float = 2.0,
) -> QPixmap | None:
    """A transparent HiDPI pixmap with one glyph, or ``None``."""
    if family() is None or name not in GLYPHS:
        return None
    pixels = max(1, int(round(logical * dpr)))
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    draw_glyph(
        painter,
        QRectF(0, 0, pixels, pixels),
        color or C.TEXT_SOFT,
        name,
        scale=0.88,
    )
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def glyph_icon(
    name: str, color: str | None = None, logical: int = 22
) -> QIcon | None:
    pixmap = glyph_pixmap(name, logical=logical, color=color)
    return QIcon(pixmap) if pixmap is not None else None
