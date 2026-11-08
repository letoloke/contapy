"""A rounded outline painted on top of a panel's children."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import C

RADIUS = 8
WIDTH = 3


class RoundedFrame(QWidget):
    """Paint a rounded border above the panel so child corners cannot cut it.

    A regular ``paintEvent`` on the panel runs before its children paint, so
    opaque child widgets would square off the inner corners of a rounded
    border. This thin overlay is raised above the children and only paints
    the outline.
    """

    def __init__(
        self,
        parent: QWidget,
        radius: int = RADIUS,
        width: int = WIDTH,
        color: str | None = None,
    ):
        super().__init__(parent)
        self.radius = radius
        self.width = width
        self.color = QColor(color or C.MUTED_DARK)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.raise_()

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self.raise_()
        return False

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.color, self.width))
        inset = self.width / 2
        p.drawRoundedRect(
            QRectF(self.rect()).adjusted(inset, inset, -inset, -inset),
            self.radius,
            self.radius,
        )
        p.end()
