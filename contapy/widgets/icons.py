"""Small painter-drawn icons used throughout the chrome."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QWidget

from ..fontawesome import draw_glyph
from ..theme import C, font


def draw_gear(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "gear"):
        return
    p.save()
    p.translate(rect.center())
    radius = min(rect.width(), rect.height()) / 2
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i in range(8):
        angle = i * 45
        p.save()
        p.rotate(angle)
        p.drawLine(QPointF(0, -radius * 0.58), QPointF(0, -radius * 0.97))
        p.restore()
    p.drawEllipse(QPointF(0, 0), radius * 0.55, radius * 0.55)
    p.drawEllipse(QPointF(0, 0), radius * 0.16, radius * 0.16)
    p.restore()


def draw_pencil(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "pencil"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(2, 1, -1, -2)
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(r.left() + 2, r.bottom() - 7), QPointF(r.right() - 7, r.top() + 2))
    p.drawLine(QPointF(r.left() + 2, r.bottom() - 7), QPointF(r.left() + 7, r.bottom() - 8))
    p.drawLine(QPointF(r.left() + 7, r.bottom() - 8), QPointF(r.left() + 9, r.bottom() - 3))
    p.drawLine(QPointF(r.left() + 9, r.bottom() - 3), QPointF(r.left() + 2, r.bottom() - 7))
    p.drawLine(QPointF(r.left() + 2, r.bottom() - 7), QPointF(r.left() + 1, r.bottom() - 1))
    p.restore()


def draw_download(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "download"):
        return
    p.save()
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(2, 1, -2, -2)
    cx = r.center().x()
    p.drawLine(QPointF(cx, r.top() + 1), QPointF(cx, r.bottom() - 5))
    p.drawPolyline(QPolygonF([
        QPointF(cx - 4, r.bottom() - 9),
        QPointF(cx, r.bottom() - 5),
        QPointF(cx + 4, r.bottom() - 9),
    ]))
    p.drawLine(QPointF(r.left(), r.bottom() - 2), QPointF(r.right(), r.bottom() - 2))
    p.restore()


def draw_chevron(
    p: QPainter,
    rect: QRectF,
    color: QColor,
    direction: str = "down",
    width: float = 1.6,
) -> None:
    glyph = {
        "down": "chevron-down",
        "up": "chevron-up",
        "left": "chevron-left",
        "right": "chevron-right",
    }.get(direction)
    if glyph and draw_glyph(p, rect, color, glyph):
        return
    p.save()
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    cx, cy = rect.center().x(), rect.center().y()
    w = rect.width() * 0.32
    h = rect.height() * 0.18
    if direction == "down":
        pts = [QPointF(cx - w, cy - h), QPointF(cx, cy + h), QPointF(cx + w, cy - h)]
    elif direction == "up":
        pts = [QPointF(cx - w, cy + h), QPointF(cx, cy - h), QPointF(cx + w, cy + h)]
    elif direction == "left":
        pts = [QPointF(cx + h, cy - w), QPointF(cx - h, cy), QPointF(cx + h, cy + w)]
    else:
        pts = [QPointF(cx - h, cy - w), QPointF(cx + h, cy), QPointF(cx - h, cy + w)]
    p.drawPolyline(QPolygonF(pts))
    p.restore()


def draw_filter(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "filter"):
        return
    p.save()
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    r = rect.adjusted(3, 4, -3, -4)
    steps = 3
    for i in range(steps):
        y = r.top() + i * r.height() / (steps - 1)
        inset = i * r.width() * 0.14
        p.drawLine(QPointF(r.left() + inset, y), QPointF(r.right() - inset, y))
    p.restore()


def draw_info(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "circle-info"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(1.5, 1.5, -1.5, -1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.INFO))
    p.drawEllipse(r)
    p.setPen(QColor(C.ON_ACCENT))
    p.setFont(font(int(r.height() * 0.68), 700))
    p.drawText(r, Qt.AlignmentFlag.AlignCenter, "i")
    p.restore()


def draw_check_circle(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "circle-check"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(1.5, 1.5, -1.5, -1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.GREEN))
    p.drawEllipse(r)
    pen = QPen(QColor(C.ON_GREEN), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([
        QPointF(r.left() + r.width() * 0.28, r.top() + r.height() * 0.53),
        QPointF(r.left() + r.width() * 0.45, r.top() + r.height() * 0.70),
        QPointF(r.left() + r.width() * 0.74, r.top() + r.height() * 0.32),
    ]))
    p.restore()


def draw_calendar(p: QPainter, rect: QRectF, color: QColor, width: float = 1.2) -> None:
    if draw_glyph(p, rect, color, "calendar-days"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(1, 2, -1, -1)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.GREEN_BAR))
    p.drawRoundedRect(r, 2, 2)
    p.setPen(QPen(QColor(C.CALENDAR_FG), 1.0))
    p.drawLine(QPointF(r.left() + 2, r.top() + r.height() * 0.34),
               QPointF(r.right() - 2, r.top() + r.height() * 0.34))
    p.drawLine(QPointF(r.center().x(), r.top() + 1.5),
               QPointF(r.center().x(), r.top() + 3.5))
    p.restore()


def draw_warning(p: QPainter, rect: QRectF, color: QColor, width: float = 1.2) -> None:
    if draw_glyph(p, rect, color, "triangle-exclamation"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(1.5, 1, -1.5, -1)
    path = QPainterPath()
    path.moveTo(r.center().x(), r.top())
    path.lineTo(r.right(), r.bottom())
    path.lineTo(r.left(), r.bottom())
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.WARNING))
    p.drawPath(path)
    p.setPen(QColor(C.WARNING_TEXT))
    p.setFont(font(max(9, int(r.height() * 0.62)), 700))
    p.drawText(r.adjusted(0, r.height() * 0.18, 0, 0), Qt.AlignmentFlag.AlignCenter, "!")
    p.restore()


def draw_check(p: QPainter, rect: QRectF, color: QColor, width: float = 1.6) -> None:
    if draw_glyph(p, rect, color, "check"):
        return
    p.save()
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    r = rect.adjusted(2, 3, -2, -3)
    p.drawPolyline(QPolygonF([
        QPointF(r.left(), r.center().y()),
        QPointF(r.left() + r.width() * 0.32, r.bottom()),
        QPointF(r.right(), r.top()),
    ]))
    p.restore()


def draw_plus(p: QPainter, rect: QRectF, color: QColor, width: float = 1.7) -> None:
    if draw_glyph(p, rect, color, "plus"):
        return
    p.save()
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    r = rect.adjusted(3, 3, -3, -3)
    p.drawLine(QPointF(r.center().x(), r.top()), QPointF(r.center().x(), r.bottom()))
    p.drawLine(QPointF(r.left(), r.center().y()), QPointF(r.right(), r.center().y()))
    p.restore()


def draw_clock(p: QPainter, rect: QRectF, color: QColor, width: float = 1.4) -> None:
    if draw_glyph(p, rect, color, "clock"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(2, 2, -2, -2)
    p.setPen(QPen(color, width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r)
    p.drawLine(QPointF(r.center().x(), r.center().y()),
               QPointF(r.center().x(), r.top() + r.height() * 0.25))
    p.drawLine(QPointF(r.center().x(), r.center().y()),
               QPointF(r.right() - r.width() * 0.25, r.center().y() + r.height() * 0.12))
    p.restore()


def draw_bell(p: QPainter, rect: QRectF, color: QColor, width: float = 1.4) -> None:
    if draw_glyph(p, rect, color, "bell"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(2, 2, -2, -2)
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(r.left() + r.width() * 0.18, r.bottom() - r.height() * 0.22)
    path.cubicTo(
        r.left() + r.width() * 0.26,
        r.top() + r.height() * 0.48,
        r.left() + r.width() * 0.3,
        r.top() + r.height() * 0.12,
        r.center().x(),
        r.top() + r.height() * 0.12,
    )
    path.cubicTo(
        r.right() - r.width() * 0.3,
        r.top() + r.height() * 0.12,
        r.right() - r.width() * 0.26,
        r.top() + r.height() * 0.48,
        r.right() - r.width() * 0.18,
        r.bottom() - r.height() * 0.22,
    )
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(
        QPointF(r.left() + r.width() * 0.12, r.bottom() - r.height() * 0.22),
        QPointF(r.right() - r.width() * 0.12, r.bottom() - r.height() * 0.22),
    )
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawEllipse(QPointF(r.center().x(), r.bottom() - r.height() * 0.06), 1.6, 1.6)
    p.restore()


def draw_void(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "ban"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(2, 2, -2, -2)
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(r)
    p.drawLine(QPointF(r.left() + 1, r.bottom() - 1),
               QPointF(r.right() - 1, r.top() + 1))
    p.restore()


def draw_flag(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "flag"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(3, 2, -3, -2)
    pen = QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(r.left() + 1, r.top()), QPointF(r.left() + 1, r.bottom()))
    path = QPainterPath()
    path.moveTo(r.left() + 1, r.top() + 1)
    path.lineTo(r.right() - 1, r.top() + r.height() * 0.22)
    path.lineTo(r.left() + 1, r.top() + r.height() * 0.43)
    path.closeSubpath()
    p.setBrush(QColor(color.red(), color.green(), color.blue(), 60))
    p.drawPath(path)
    p.restore()


def draw_reconciled(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "circle-dot"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    r = rect.adjusted(1.5, 1.5, -1.5, -1.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.RECONCILED))
    p.drawEllipse(r)
    p.setPen(QPen(QColor(C.ON_RECONCILED), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                  Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolyline(QPolygonF([
        QPointF(r.left() + r.width() * 0.18, r.top() + r.height() * 0.52),
        QPointF(r.left() + r.width() * 0.38, r.top() + r.height() * 0.72),
        QPointF(r.left() + r.width() * 0.72, r.top() + r.height() * 0.28),
    ]))
    p.drawPolyline(QPolygonF([
        QPointF(r.left() + r.width() * 0.48, r.top() + r.height() * 0.52),
        QPointF(r.left() + r.width() * 0.64, r.top() + r.height() * 0.68),
        QPointF(r.left() + r.width() * 0.86, r.top() + r.height() * 0.40),
    ]))
    p.restore()


def draw_search(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "magnifying-glass"):
        return
    p.save()
    p.setPen(QPen(color, width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(2, 2, -5, -5)
    p.drawEllipse(r)
    p.drawLine(QPointF(r.right() - 1, r.bottom() - 1),
               QPointF(rect.right() - 2, rect.bottom() - 2))
    p.restore()


def draw_table(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "table"):
        return
    p.save()
    p.setPen(QPen(color, width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(1, 2, -1, -2)
    p.drawRoundedRect(r, 1.5, 1.5)
    for factor in (0.34, 0.67):
        y = r.top() + r.height() * factor
        p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
    for factor in (0.42, 0.72):
        x = r.left() + r.width() * factor
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
    p.restore()


def draw_pie(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "chart-pie"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(color, width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    r = rect.adjusted(1, 1, -1, -1)
    p.drawEllipse(r)
    center = r.center()
    p.drawLine(center, QPointF(center.x(), r.top()))
    p.drawLine(center, QPointF(r.right(), center.y() - r.height() * 0.22))
    p.restore()


def draw_bars(p: QPainter, rect: QRectF, color: QColor, width: float = 1.5) -> None:
    if draw_glyph(p, rect, color, "chart-column"):
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    r = rect.adjusted(2, 2, -2, -1)
    bar_w = r.width() / 5.0
    heights = (0.42, 0.72, 1.0)
    for index, factor in enumerate(heights):
        x = r.left() + index * (bar_w + bar_w * 0.55)
        top = r.bottom() - r.height() * factor
        p.drawRoundedRect(QRectF(x, top, bar_w, r.height() * factor), 1, 1)
    p.restore()


DrawFn = Callable[[QPainter, QRectF, QColor, float], None]


class IconButton(QAbstractButton):
    """A flat, hover-highlighted icon button."""

    def __init__(
        self,
        draw_fn: DrawFn,
        size: int = 26,
        tooltip: str = "",
        color: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._draw = draw_fn
        self._color = color
        self.setFixedSize(QSize(size, size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hover = False

    def enterEvent(self, event):  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover and self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C.ROW_HOVER))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        if not self.isEnabled():
            color = QColor(C.DISABLED)
        elif self.isCheckable() and self.isChecked():
            color = QColor(C.ACCENT)
        else:
            color = QColor(self._color or C.TEXT_SOFT)
        inner = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        self._draw(p, inner, color, 1.5)
        p.end()
