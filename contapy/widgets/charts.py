"""Custom-painted donut and cash-flow charts, plus their card chrome."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..models import MonthFlow, Slice
from ..money import money, money_short
from ..theme import C, font, terminal_style
from .icons import IconButton, draw_gear

HEADER_SPACE = 62
FOOTER_H = 42


class ChartFooter(QWidget):
    periodChanged = Signal(str)
    refreshRequested = Signal()
    saveRequested = Signal()

    def __init__(
        self,
        periods: list[str],
        current: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setFixedHeight(FOOTER_H)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 6, 10, 6)
        layout.setSpacing(8)

        self.label = QLabel("")
        self.label.setFont(font(14, 400))
        self.label.setStyleSheet(f"color:{C.TEXT_SOFT};")
        layout.addWidget(self.label)
        layout.addStretch(1)

        self.combo = QComboBox(self)
        self.combo.addItems(periods)
        self.combo.setCurrentText(current)
        self.combo.setFixedSize(150, 29)
        self.combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo.setFont(font(13, 400))
        self.combo.currentTextChanged.connect(self.periodChanged.emit)
        layout.addWidget(self.combo)

        self.gear = IconButton(draw_gear, 28, "Chart options", parent=self)
        self.gear.clicked.connect(self._open_menu)
        layout.addWidget(self.gear)

    def _open_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Refresh chart", self.refreshRequested.emit)
        menu.addAction("Save chart image…", self.saveRequested.emit)
        menu.exec(self.gear.mapToGlobal(self.gear.rect().bottomLeft()))

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()


class ChartCard(QWidget):
    """Card with a painted title block, a chart body and a footer toolbar."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        footer_label: str,
        periods: list[str],
        current_period: str,
        content: QWidget,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.title = title
        self.subtitle = subtitle
        self.content = content
        self._flash = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addSpacing(HEADER_SPACE)
        layout.addWidget(content, 1)
        self.footer = ChartFooter(periods, current_period, self)
        self.footer.label.setText(footer_label)
        layout.addWidget(self.footer)

        self.footer.saveRequested.connect(self._save_image)

    def set_subtitle(self, text: str) -> None:
        self.subtitle = text
        self.update()

    def period(self) -> str:
        return self.footer.combo.currentText()

    def flash(self) -> None:
        self._flash = True
        self.update()
        QTimer.singleShot(900, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash = False
        self.update()

    def _save_image(self) -> None:
        suggested = self.title.lower().replace(" / ", "-").replace(" ", "-").replace("&", "and")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save chart image", f"{suggested}.png", "PNG image (*.png)"
        )
        if path:
            pixmap = self.content.grab()
            pixmap.save(path, "PNG")

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.ACCENT if self._flash else C.BORDER), 2 if self._flash else 1))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))

        p.setPen(QColor(C.TITLE))
        p.setFont(font(20, 400))
        title = f"[ {self.title.upper()} ]" if terminal_style() else self.title
        p.drawText(
            QRectF(15, 12, self.width() - 30, 28),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        if self.subtitle:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(13, 400))
            p.drawText(
                QRectF(15, 39, self.width() - 30, 18),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self.subtitle,
            )
        p.end()


class DonutChart(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.slices: list[Slice] = []
        self.total = 0.0
        self.empty_text = "No spending in this period"
        self.show_legend = True
        self._hover = -1
        self._center = QPointF(0, 0)
        self._radius = 0.0
        self._inner = 0.0
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)

    def set_data(self, slices: list[Slice], total: float) -> None:
        self.slices = slices
        self.total = total
        self._hover = -1
        self.update()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))

        width, height = self.width(), self.height()
        if not self.slices or self.total <= 0:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            p.end()
            return

        if not self.show_legend:
            radius = min(150.0, height * 0.47, width * 0.42)
            cx = width * 0.5
            legend_x = width
        elif width >= 540:
            radius = min(150.0, height * 0.47, width * 0.252)
            cx = width * 0.382
            legend_x = width * (0.69 if terminal_style() else 0.732)
        else:
            legend_font = font(13 if terminal_style() else 14, 400)
            metrics = QFontMetrics(legend_font)
            max_label = max(metrics.horizontalAdvance(item.name) for item in self.slices)
            legend_x = max(width * 0.60, width - max_label - 30)
            cx = width * 0.33
            radius = min(150.0, height * 0.47, legend_x - cx - 18)
            radius = max(70.0, radius)
        cy = height * 0.545
        self._center = QPointF(cx, cy)
        self._radius = radius
        self._inner = radius * 0.55

        outer = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        angle = 90.0
        for index, item in enumerate(self.slices):
            span = item.percent * 360.0
            if span <= 0:
                continue
            if index == self._hover:
                color = QColor(item.color).lighter(112)
                draw_radius = radius + 2
                rect = QRectF(
                    cx - draw_radius,
                    cy - draw_radius,
                    draw_radius * 2,
                    draw_radius * 2,
                )
            else:
                color = QColor(item.color)
                rect = outer
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawPie(rect, int(round(angle * 16)), int(round(-span * 16)))
            angle -= span

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.PANEL))
        p.drawEllipse(QPointF(cx, cy), self._inner, self._inner)

        # Legend
        if not self.show_legend:
            p.end()
            return
        row_h = 22.5
        top = 4.0
        legend_size = 13 if terminal_style() else 14
        p.setFont(font(legend_size, 400))
        for index, item in enumerate(self.slices):
            y = top + index * row_h
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(item.color))
            p.drawEllipse(QPointF(legend_x + 6, y + row_h / 2), 6.2, 6.2)
            p.setPen(QColor(C.TEXT if index == self._hover else C.TEXT_SOFT))
            p.setFont(font(legend_size, 400))
            label_rect = QRectF(
                legend_x + 19, y, max(40, width - legend_x - 24), row_h
            )
            label = QFontMetrics(p.font()).elidedText(
                item.name, Qt.TextElideMode.ElideRight, int(label_rect.width())
            )
            p.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
        p.end()

    # ------------------------------------------------------------- interaction
    def _slice_at(self, pos: QPointF) -> int:
        if not self.slices:
            return -1
        dx = pos.x() - self._center.x()
        dy = pos.y() - self._center.y()
        dist = math.hypot(dx, dy)
        if dist < self._inner - 3 or dist > self._radius + 5:
            return -1
        math_angle = math.degrees(math.atan2(-dy, dx)) % 360
        clockwise = (90 - math_angle) % 360
        cursor = 0.0
        for index, item in enumerate(self.slices):
            span = item.percent * 360
            if cursor <= clockwise < cursor + span:
                return index
            cursor += span
        return -1

    def mouseMoveEvent(self, event):  # noqa: N802
        index = self._slice_at(event.position())
        if index != self._hover:
            self._hover = index
            self.update()
            if index >= 0:
                item = self.slices[index]
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{item.name}\n{money(item.amount)} · {item.percent * 100:.1f}%",
                    self,
                )
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QToolTip.hideText()
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = -1
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)


class SpendingRevenueChart(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.flows: list[MonthFlow] = []
        self._hover = -1
        self._plot = QRectF()
        self._slot = 0.0
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(180)

    def set_data(self, flows: list[MonthFlow]) -> None:
        self.flows = flows
        self._hover = -1
        self.update()

    def _range(self) -> tuple[float, float, float]:
        max_income = max((f.income for f in self.flows), default=0.0)
        max_expense = max((f.expense for f in self.flows), default=0.0)
        step = 100_000.0
        top = max(300_000.0, math.ceil(max_income / step) * step)
        bottom = min(-400_000.0, -math.ceil(max_expense / step) * step)
        return top, bottom, step

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))

        if not self.flows:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No activity in this period")
            p.end()
            return

        width, height = self.width(), self.height()
        left = 108.0
        right = width - 38.0
        top_m = 12.0
        bottom_m = 30.0
        plot = QRectF(left, top_m, max(10.0, right - left), max(10.0, height - top_m - bottom_m))
        self._plot = plot
        top, bottom, step = self._range()
        span = top - bottom
        zero_y = plot.top() + (top / span) * plot.height()

        axis_font = font(13, 400)
        p.setFont(axis_font)
        metrics = QFontMetrics(axis_font)
        value = top
        while value >= bottom - 0.1:
            y = plot.top() + ((top - value) / span) * plot.height()
            if abs(value) < 0.1:
                p.setPen(QPen(QColor(C.GRID_ZERO), 1))
            else:
                p.setPen(QPen(QColor(C.GRID), 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(C.MUTED))
            label = money_short(0) if abs(value) < 0.1 else money_short(value)
            p.drawText(
                QRectF(plot.left() - metrics.horizontalAdvance(label) - 18, y - 9,
                       metrics.horizontalAdvance(label) + 6, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            value -= step

        n = len(self.flows)
        slot = plot.width() / n
        self._slot = slot
        bar_w = min(35.0, slot * 0.90)
        terminal = terminal_style()
        if terminal:
            label_size = 12 if slot >= 32 else (11 if slot >= 26 else 10)
        else:
            label_size = 13 if slot >= 30 else (12 if slot >= 24 else 11)
        p.setPen(QPen(QColor(C.GRID_ZERO), 1))
        p.drawLine(QPointF(plot.left(), zero_y), QPointF(plot.right(), zero_y))
        p.setPen(QPen(QColor(C.GRID), 1))
        p.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))

        for index, flow in enumerate(self.flows):
            cx = plot.left() + slot * (index + 0.5)
            income_h = (flow.income / span) * plot.height()
            expense_h = (flow.expense / span) * plot.height()
            income_rect = QRectF(cx - bar_w / 2, zero_y - income_h, bar_w, income_h)
            expense_rect = QRectF(cx - bar_w / 2, zero_y, bar_w, expense_h)
            green = QColor(C.GREEN_BAR).lighter(114) if index == self._hover else QColor(C.GREEN_BAR)
            red = QColor(C.RED_BAR).lighter(114) if index == self._hover else QColor(C.RED_BAR)
            if income_h > 0.4:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(green)
                if terminal:
                    p.drawRect(income_rect)
                else:
                    p.drawRoundedRect(income_rect, 2, 2)
            if expense_h > 0.4:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(red)
                if terminal:
                    p.drawRect(expense_rect)
                else:
                    p.drawRoundedRect(expense_rect, 2, 2)

            show_label = slot >= (26 if terminal else 22)
            if (
                show_label
                or index == n - 1
                or (index % 2 == 0 and index != n - 2)
            ):
                p.setPen(QColor(C.MUTED))
                p.setFont(font(label_size, 400))
                p.drawText(
                    QRectF(cx - slot / 2, plot.bottom() + 10, slot, 18),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    flow.label,
                )

        if all(flow.income <= 0 and flow.expense <= 0 for flow in self.flows):
            p.setFont(font(14, 400))
            p.setPen(QColor(C.MUTED))
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No activity in this period")

        # Year tag in the upper-left corner of the plot.
        p.setFont(font(12, 400))
        p.setPen(QColor(C.MUTED_DARK))
        p.drawText(
            QRectF(plot.left() + slot * 0.95, plot.top() - 15, 60, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(self.flows[-1].year),
        )
        p.end()

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self.flows or self._slot <= 0:
            return
        plot = self._plot
        pos = event.position()
        if plot.left() <= pos.x() <= plot.right() and plot.top() - 6 <= pos.y() <= plot.bottom() + 24:
            index = int((pos.x() - plot.left()) // self._slot)
            index = max(0, min(len(self.flows) - 1, index))
        else:
            index = -1
        if index != self._hover:
            self._hover = index
            self.update()
            if index >= 0:
                flow = self.flows[index]
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{flow.label} {flow.year}\n"
                    f"Income {money(flow.income)}\n"
                    f"Spending {money(flow.expense)}\n"
                    f"Net {money(flow.net)}",
                    self,
                )
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QToolTip.hideText()
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = -1
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)
