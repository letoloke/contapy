"""Functional reports window: table, pie and bar views over the ledger."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..db import DataStore
from ..models import Category, MonthFlow, ReportRow, Slice
from ..money import friendly_date, money, money_short
from ..theme import C, DONUT_COLORS, chart_color, font
from .charts import DonutChart, SpendingRevenueChart
from .dialogs import CategoryTransactionsDialog
from .icons import IconButton, draw_bars, draw_pie, draw_sankey, draw_table

VIEWS = ("table", "pie", "bar", "sankey")
MODES = (("total", "Total"), ("time", "Time"))
GROUPS = (("category", "Category"), ("payee", "Payee"), ("account", "Account"))
TYPES = (("expense", "Expense"), ("income", "Income"))


def _month_bounds(reference: date) -> tuple[date, date]:
    last_day = calendar.monthrange(reference.year, reference.month)[1]
    return reference.replace(day=1), reference.replace(day=last_day)


def _top_slices(
    items: list[tuple[str, float, str]], limit: int = 10
) -> tuple[list[Slice], float]:
    items = [(name, amount, color) for name, amount, color in items if amount > 0]
    # A real "Other" category and the aggregated remainder must not both show.
    merged_other = sum(amount for name, amount, _ in items if name == "Other")
    items = [(name, amount, color) for name, amount, color in items if name != "Other"]
    items.sort(key=lambda item: -item[1])
    total = sum(amount for _, amount, _ in items) + merged_other
    if (not items and merged_other <= 0) or total <= 0:
        return [], 0.0
    named = items[:limit]
    rest = sum(amount for _, amount, _ in items[limit:]) + merged_other
    slices: list[Slice] = []
    for index, (name, amount, color) in enumerate(named):
        slices.append(
            Slice(
                name=name,
                amount=amount,
                color=color or DONUT_COLORS[index % len(DONUT_COLORS)],
                percent=amount / total,
            )
        )
    if rest > 0:
        slices.append(
            Slice(
                name="Other",
                amount=rest,
                color=DONUT_COLORS[len(named) % len(DONUT_COLORS)],
                percent=rest / total,
            )
        )
    return slices, total


class SummaryBlock(QWidget):
    """One Expense / Income / Total figure in the report header."""

    def __init__(self, label: str, color: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = color
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.label = QLabel(label)
        self.label.setFont(font(12, 400))
        self.label.setStyleSheet(f"color:{C.MUTED};")
        self.value = QLabel("—")
        self.value.setFont(font(19, 600))
        self.value.setStyleSheet(f"color:{color};")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        self.setMinimumWidth(138)

    def set_value(self, text: str) -> None:
        self.value.setText(text)


class CategoryBarChart(QWidget):
    """Horizontal bars for a Total-mode report."""

    barActivated = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.bars: list[tuple[str, float, str]] = []
        self.empty_text = "No activity in this period"
        self._hover = -1
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(260)

    def set_data(self, bars: list[tuple[str, float, str]], empty_text: str = "") -> None:
        self.bars = [
            (label, amount, chart_color(color, index))
            for index, (label, amount, color) in enumerate(bars)
            if amount > 0
        ]
        if empty_text:
            self.empty_text = empty_text
        self._hover = -1
        self.setMinimumHeight(max(260, len(self.bars) * 34 + 30))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))

        if not self.bars:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.empty_text)
            p.end()
            return

        width, height = self.width(), self.height()
        label_w = min(220.0, max(120.0, width * 0.30))
        amount_w = 118.0
        left = 16.0
        bar_left = left + label_w + 14
        bar_right = width - amount_w - 14
        if bar_right < bar_left + 20:
            bar_right = width - 18
        top = 14.0
        bottom = height - 14.0
        row_h = (bottom - top) / len(self.bars)
        bar_h = min(20.0, row_h * 0.56)
        max_value = max(amount for _, amount, _ in self.bars) or 1.0

        p.setFont(font(13, 400))
        metrics = QFontMetrics(font(13, 400))
        for index, (label, amount, color) in enumerate(self.bars):
            cy = top + row_h * (index + 0.5)
            if index == self._hover:
                tint = QColor(C.ACCENT)
                tint.setAlpha(20)
                p.fillRect(
                    QRectF(0, top + row_h * index, width, row_h), tint
                )
            elif index % 2 == 0:
                p.fillRect(
                    QRectF(0, top + row_h * index, width, row_h),
                    QColor(C.ALT_ROW),
                )
            bar_color = QColor(color)
            if index == self._hover:
                bar_color = bar_color.lighter(114)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bar_color)
            p.drawEllipse(QRectF(left, cy - 4.5, 9, 9))
            p.setPen(QColor(C.TEXT if index == self._hover else C.TEXT_SOFT))
            text = metrics.elidedText(label, Qt.TextElideMode.ElideRight, int(label_w))
            p.drawText(
                QRectF(left + 16, cy - row_h / 2, label_w - 16, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            bar_len = max(2.0, (amount / max_value) * max(10.0, bar_right - bar_left))
            rect = QRectF(bar_left, cy - bar_h / 2, bar_len, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bar_color)
            p.drawRoundedRect(rect, 2, 2)
            p.setPen(QColor(C.TEXT))
            p.setFont(font(13, 500))
            p.drawText(
                QRectF(width - amount_w - 8, cy - row_h / 2, amount_w, row_h),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                money(amount),
            )
            p.setFont(font(13, 400))
        p.end()

    def _row_at(self, pos) -> int:
        if not self.bars:
            return -1
        top = 14.0
        bottom = self.height() - 14.0
        if not top <= pos.y() <= bottom:
            return -1
        row_h = (bottom - top) / len(self.bars)
        index = int((pos.y() - top) // row_h)
        return max(0, min(len(self.bars) - 1, index))

    def mouseMoveEvent(self, event):  # noqa: N802
        index = self._row_at(event.position())
        if index != self._hover:
            self._hover = index
            self.update()
            if index >= 0:
                label, amount, _color = self.bars[index]
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{label}\n{money(amount)}",
                    self,
                )
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QToolTip.hideText()
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._row_at(event.position())
            if index >= 0:
                self.barActivated.emit(index)
        super().mousePressEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = -1
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)


class SankeyChart(QWidget):
    """Account-to-group flow diagram for the report."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.flows: list[tuple[str, str, float]] = []
        self.left_totals: dict[str, float] = {}
        self.right_totals: dict[str, float] = {}
        self.empty_text = "No activity in this period"
        self._left_order: list[str] = []
        self._right_order: list[str] = []
        self._left_rects: dict[str, QRectF] = {}
        self._right_rects: dict[str, QRectF] = {}
        self._hover_left: str | None = None
        self._hover_right: str | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )
        self.setMinimumHeight(340)

    def set_data(
        self,
        flows: list[tuple[str, str, float]],
        empty_text: str = "",
    ) -> None:
        clean = [
            (left, right, float(amount))
            for left, right, amount in flows
            if float(amount) > 0.005
        ]
        right_totals: dict[str, float] = {}
        for _left, right, amount in clean:
            right_totals[right] = right_totals.get(right, 0.0) + amount
        if len(right_totals) > 11:
            keep = set(
                sorted(
                    right_totals,
                    key=lambda name: (
                        -right_totals[name],
                        name.casefold(),
                    ),
                )[:10]
            )
            merged: dict[tuple[str, str], float] = {}
            for left, right, amount in clean:
                label = right if right in keep else "Other"
                merged[(left, label)] = merged.get((left, label), 0.0) + amount
            clean = [
                (left, right, amount)
                for (left, right), amount in merged.items()
            ]
        self.flows = clean
        self.left_totals = {}
        self.right_totals = {}
        for left, right, amount in self.flows:
            self.left_totals[left] = self.left_totals.get(left, 0.0) + amount
            self.right_totals[right] = (
                self.right_totals.get(right, 0.0) + amount
            )
        self._left_order = sorted(
            self.left_totals,
            key=lambda name: (-self.left_totals[name], name.casefold()),
        )
        self._right_order = sorted(
            self.right_totals,
            key=lambda name: (-self.right_totals[name], name.casefold()),
        )
        if empty_text:
            self.empty_text = empty_text
        self._hover_left = None
        self._hover_right = None
        self.setMinimumHeight(
            max(340, max(len(self._left_order), len(self._right_order)) * 34 + 40)
        )
        self.update()

    def _layout(
        self,
        order: list[str],
        totals: dict[str, float],
        x: float,
        top: float,
        gap: float,
        node_w: float,
        scale: float,
    ) -> dict[str, QRectF]:
        rects: dict[str, QRectF] = {}
        y = top
        for name in order:
            height = max(18.0, totals[name] * scale)
            rects[name] = QRectF(x, y, node_w, height)
            y += height + gap
        return rects

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))

        if not self.flows or not self.left_totals:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self.empty_text,
            )
            p.end()
            return

        width, height = self.width(), self.height()
        margin = 16.0
        top = 20.0
        bottom = 18.0
        gap = 10.0
        available = max(20.0, height - top - bottom)
        node_w = min(170.0, max(100.0, (width - 2 * margin) * 0.22))
        if width - 2 * margin < node_w * 2 + 80:
            node_w = max(60.0, (width - 2 * margin - 40) / 2)
        left_x = margin
        right_x = width - margin - node_w

        total = sum(self.left_totals.values())
        max_nodes = max(len(self._left_order), len(self._right_order))
        gap_total = gap * max(0, max_nodes - 1)
        scale = (available - gap_total) / total if total else 1.0
        scale = max(1e-9, scale)

        self._left_rects = self._layout(
            self._left_order,
            self.left_totals,
            left_x,
            top,
            gap,
            node_w,
            scale,
        )
        self._right_rects = self._layout(
            self._right_order,
            self.right_totals,
            right_x,
            top,
            gap,
            node_w,
            scale,
        )

        left_colors = {
            name: DONUT_COLORS[index % len(DONUT_COLORS)]
            for index, name in enumerate(self._left_order)
        }
        right_colors = {
            name: DONUT_COLORS[(index + 4) % len(DONUT_COLORS)]
            for index, name in enumerate(self._right_order)
        }
        flow_map = {
            (left, right): amount
            for left, right, amount in self.flows
        }
        right_offsets = {
            name: rect.top() for name, rect in self._right_rects.items()
        }
        hover_active = (
            self._hover_left is not None or self._hover_right is not None
        )

        # Links first, so the node blocks sit on top of them.
        for left in self._left_order:
            left_rect = self._left_rects[left]
            y1 = left_rect.top()
            for right in self._right_order:
                amount = flow_map.get((left, right), 0.0)
                if amount <= 0:
                    continue
                thickness = max(1.0, amount * scale)
                right_rect = self._right_rects[right]
                y2 = right_offsets[right]
                right_offsets[right] += thickness
                x1 = left_rect.right()
                x2 = right_rect.left()
                mid = (x1 + x2) / 2
                path = QPainterPath(QPointF(x1, y1))
                path.cubicTo(
                    QPointF(mid, y1),
                    QPointF(mid, y2),
                    QPointF(x2, y2),
                )
                path.lineTo(QPointF(x2, y2 + thickness))
                path.cubicTo(
                    QPointF(mid, y2 + thickness),
                    QPointF(mid, y1 + thickness),
                    QPointF(x1, y1 + thickness),
                )
                path.closeSubpath()
                color = QColor(left_colors[left])
                if hover_active and not (
                    self._hover_left == left or self._hover_right == right
                ):
                    color.setAlpha(30)
                else:
                    color.setAlpha(125 if hover_active else 85)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(color)
                p.drawPath(path)
                y1 += thickness

        label_font = font(11, 600)
        amount_font = font(10, 400)
        metrics = QFontMetrics(label_font)
        for name in self._left_order:
            self._paint_node(
                p,
                self._left_rects[name],
                name,
                self.left_totals[name],
                left_colors[name],
                label_font,
                amount_font,
                metrics,
                self._hover_left == name,
            )
        for name in self._right_order:
            self._paint_node(
                p,
                self._right_rects[name],
                name,
                self.right_totals[name],
                right_colors[name],
                label_font,
                amount_font,
                metrics,
                self._hover_right == name,
            )
        p.end()

    @staticmethod
    def _paint_node(
        p: QPainter,
        rect: QRectF,
        name: str,
        total: float,
        color: str,
        label_font,
        amount_font,
        metrics: QFontMetrics,
        hovered: bool,
    ) -> None:
        p.setPen(
            QPen(QColor(C.ACCENT if hovered else C.BORDER), 1.4 if hovered else 1)
        )
        p.setBrush(QColor(color))
        p.drawRoundedRect(rect, 3, 3)
        if rect.height() < 18:
            return
        inner = rect.adjusted(7, 1, -7, -1)
        label = metrics.elidedText(
            name, Qt.TextElideMode.ElideRight, int(inner.width())
        )
        p.setFont(label_font)
        p.setPen(QColor("#ffffff"))
        if rect.height() >= 34:
            p.drawText(
                QRectF(inner.left(), inner.top(), inner.width(), 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
            p.setFont(amount_font)
            p.setPen(QColor(255, 255, 255, 190))
            p.drawText(
                QRectF(inner.left(), inner.top() + 15, inner.width(), 13),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                money_short(total),
            )
        else:
            p.drawText(
                inner,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )

    def _node_at(self, pos) -> tuple[str | None, str | None]:
        for name, rect in self._left_rects.items():
            if rect.contains(pos):
                return name, None
        for name, rect in self._right_rects.items():
            if rect.contains(pos):
                return None, name
        return None, None

    def mouseMoveEvent(self, event):  # noqa: N802
        left, right = self._node_at(event.position())
        if (left, right) != (self._hover_left, self._hover_right):
            self._hover_left = left
            self._hover_right = right
            self.update()
            name = left or right
            if name is not None:
                total = (
                    self.left_totals.get(name, 0.0)
                    if left is not None
                    else self.right_totals.get(name, 0.0)
                )
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{name}\n{money(total)}",
                    self,
                )
            else:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover_left = None
        self._hover_right = None
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)


class ReportPieView(QWidget):
    """Donut with a readable amount/percentage legend beside it."""

    sliceActivated = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.donut = DonutChart()
        self.donut.show_legend = False
        layout.addWidget(self.donut, 3)

        self.legend = QTableWidget(0, 3)
        self.legend.setHorizontalHeaderLabels(["Name", "Amount", "%"])
        self.legend.verticalHeader().setVisible(False)
        self.legend.setShowGrid(False)
        self.legend.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.legend.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.legend.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.legend.setAlternatingRowColors(True)
        header = self.legend.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 118)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 58)
        self.legend.verticalHeader().setDefaultSectionSize(28)
        layout.addWidget(self.legend, 2)

        self.donut.sliceActivated.connect(self.sliceActivated.emit)
        self.legend.cellClicked.connect(
            lambda row, _column: self.sliceActivated.emit(row)
        )

    def set_data(
        self, slices: list[Slice], total: float, empty_text: str = "No activity"
    ) -> None:
        self.donut.empty_text = empty_text
        self.donut.set_data(slices, total)
        self.legend.setRowCount(0)
        for item in slices:
            row = self.legend.rowCount()
            self.legend.insertRow(row)
            name = QTableWidgetItem(item.name)
            name.setIcon(self._swatch(item.color))
            amount = QTableWidgetItem(money(item.amount))
            amount.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            percent = QTableWidgetItem(f"{item.percent * 100:.1f}%")
            percent.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            percent.setForeground(QColor(C.MUTED))
            self.legend.setItem(row, 0, name)
            self.legend.setItem(row, 1, amount)
            self.legend.setItem(row, 2, percent)

    @staticmethod
    def _swatch(color: str) -> QIcon:
        pixmap = QPixmap(12, 12)
        pixmap.fill(QColor(color or C.MUTED))
        return QIcon(pixmap)


class ReportsWindow(QMainWindow):
    """A HomeBank-style report window backed by the live database."""

    changed = Signal()

    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.store = store
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(1080, 620)
        self.resize(1320, 780)
        self.setWindowTitle("Reports")
        self.setStyleSheet(f"QMainWindow {{ background: {C.BG}; }}")
        self._view = "table"
        self._syncing_dates = False
        self._tool_buttons: dict[str, IconButton] = {}
        self._pie_labels: list[str] = []
        self._bar_labels: list[str] = []

        self._build_menus()
        self._build_ui()
        self._wire()
        self._apply_preset()
        self.reload()

    # ------------------------------------------------------------------ menus
    def _build_menus(self) -> None:
        bar = self.menuBar()
        bar.setNativeMenuBar(False)
        bar.setFont(font(14, 400))

        def action(text: str, slot, shortcut: str | None = None) -> QAction:
            item = QAction(text, self)
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
            item.triggered.connect(lambda _checked=False: slot())
            self.addAction(item)
            return item

        view_menu = bar.addMenu("View")
        view_menu.addAction(action("Table", lambda: self.set_view("table"), "Ctrl+1"))
        view_menu.addAction(action("Pie Chart", lambda: self.set_view("pie"), "Ctrl+2"))
        view_menu.addAction(action("Bar Chart", lambda: self.set_view("bar"), "Ctrl+3"))
        view_menu.addAction(
            action(
                "Sankey Diagram",
                lambda: self.set_view("sankey"),
                "Ctrl+4",
            )
        )
        view_menu.addSeparator()
        refresh = action("Refresh", self.reload, "F5")
        view_menu.addAction(refresh)
        view_menu.addAction(action("Close", self.close, "Ctrl+W"))
        close_action = action("Close Window", self.close, "Escape")
        close_action.setShortcutVisibleInContextMenu(False)

    # --------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet(f"background:{C.BG};")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_display_panel())

        content = QWidget()
        content.setStyleSheet(f"background:{C.BG};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_view_toolbar())
        content_layout.addWidget(self._build_views(), 1)
        body.addWidget(content, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(94)
        header.setStyleSheet(f"background:{C.PANEL}; border-bottom:1px solid {C.BORDER};")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 20, 10)
        layout.setSpacing(18)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("Reports")
        title.setFont(font(22, 600))
        title.setStyleSheet(f"color:{C.TITLE};")
        self.span_label = QLabel("")
        self.span_label.setFont(font(13, 400))
        self.span_label.setStyleSheet(f"color:{C.MUTED};")
        titles.addWidget(title)
        titles.addWidget(self.span_label)
        layout.addLayout(titles)
        layout.addStretch(1)

        self.expense_block = SummaryBlock("Expense", C.ORANGE)
        self.income_block = SummaryBlock("Income", C.GREEN)
        self.total_block = SummaryBlock("Total", C.TEXT)
        layout.addWidget(self.expense_block)
        layout.addWidget(self.income_block)
        layout.addWidget(self.total_block)
        return header

    def _section_label(self, text: str, first: bool = False) -> QLabel:
        label = QLabel(text.upper())
        label.setFont(font(11, 600))
        label.setStyleSheet(f"color:{C.MUTED}; letter-spacing:1px;")
        if not first:
            label.setContentsMargins(0, 10, 0, 0)
        return label

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(font(12, 400))
        label.setStyleSheet(f"color:{C.TEXT_SOFT};")
        return label

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{C.BORDER}; background:{C.BORDER};")
        line.setFixedHeight(1)
        return line

    def _build_display_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(286)
        panel.setStyleSheet(f"background:{C.PANEL}; border-right:1px solid {C.BORDER};")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background:{C.PANEL}; border:none;")
        outer.addWidget(scroll)

        body = QWidget()
        body.setStyleSheet(f"background:{C.PANEL};")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(6)
        scroll.setWidget(body)

        heading = QLabel("Display")
        heading.setFont(font(18, 600))
        heading.setStyleSheet(f"color:{C.TITLE};")
        layout.addWidget(heading)
        layout.addSpacing(2)
        layout.addWidget(self._separator())
        layout.addSpacing(4)

        layout.addWidget(self._section_label("Mode", first=True))
        self.mode_combo = QComboBox()
        for value, label in MODES:
            self.mode_combo.addItem(label, value)
        layout.addWidget(self.mode_combo)

        layout.addWidget(self._section_label("View by"))
        self.group_combo = QComboBox()
        for value, label in GROUPS:
            self.group_combo.addItem(label, value)
        layout.addWidget(self.group_combo)

        layout.addWidget(self._section_label("Type"))
        self.type_combo = QComboBox()
        for value, label in TYPES:
            self.type_combo.addItem(label, value)
        layout.addWidget(self.type_combo)

        self.sort_check = QCheckBox("Sort by amount")
        self.sort_check.setChecked(True)
        layout.addWidget(self.sort_check)

        layout.addWidget(self._section_label("Filter"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Payee, memo, category…")
        self.search_edit.setClearButtonEnabled(True)
        layout.addWidget(self.search_edit)
        self.account_combo = QComboBox()
        self.account_combo.addItem("All accounts", None)
        layout.addWidget(self.account_combo)

        layout.addWidget(self._section_label("Date range"))
        self.preset_combo = QComboBox()
        for label in (
            "All dates",
            "This month",
            "Last month",
            "This year",
            "Last year",
            "Custom",
        ):
            self.preset_combo.addItem(label, label)
        layout.addWidget(self.preset_combo)
        dates = QHBoxLayout()
        dates.setSpacing(8)
        from_box = QVBoxLayout()
        from_box.setSpacing(3)
        from_box.addWidget(self._field_label("From"))
        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        from_box.addWidget(self.from_edit)
        to_box = QVBoxLayout()
        to_box.setSpacing(3)
        to_box.addWidget(self._field_label("To"))
        self.to_edit = QDateEdit()
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("yyyy-MM-dd")
        to_box.addWidget(self.to_edit)
        dates.addLayout(from_box, 1)
        dates.addLayout(to_box, 1)
        layout.addLayout(dates)

        self.reset_button = QPushButton("Reset filters")
        self.reset_button.setProperty("role", "action")
        layout.addSpacing(12)
        layout.addWidget(self.reset_button)
        layout.addStretch(1)
        return panel

    def _build_view_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet(f"background:{C.BG}; border-bottom:1px solid {C.BORDER};")
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(4)

        for view, icon, tooltip in (
            ("table", draw_table, "Table view"),
            ("pie", draw_pie, "Pie chart"),
            ("bar", draw_bars, "Bar chart"),
            ("sankey", draw_sankey, "Sankey diagram"),
        ):
            button = IconButton(icon, size=32, tooltip=tooltip)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setChecked(view == "table")
            button.clicked.connect(lambda _checked=False, v=view: self.set_view(v))
            self._tool_buttons[view] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.view_hint = QLabel("")
        self.view_hint.setFont(font(12, 400))
        self.view_hint.setStyleSheet(f"color:{C.MUTED};")
        layout.addWidget(self.view_hint)
        return toolbar

    def _build_views(self) -> QWidget:
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{C.BG};")

        table_host = QWidget()
        table_host.setStyleSheet(f"background:{C.BG};")
        table_layout = QVBoxLayout(table_host)
        table_layout.setContentsMargins(16, 14, 16, 16)
        table_layout.setSpacing(0)
        self.table = QTableWidget(0, 4)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(column, 150)
        table_layout.addWidget(self.table)
        self.stack.addWidget(table_host)

        self.pie_view = ReportPieView()
        pie_host = QWidget()
        pie_host.setStyleSheet(f"background:{C.PANEL};")
        pie_layout = QVBoxLayout(pie_host)
        pie_layout.setContentsMargins(16, 14, 16, 16)
        pie_layout.addWidget(self.pie_view)
        self.stack.addWidget(pie_host)

        bar_host = QWidget()
        bar_host.setStyleSheet(f"background:{C.BG};")
        bar_layout = QVBoxLayout(bar_host)
        bar_layout.setContentsMargins(16, 14, 16, 16)
        self.bar_stack = QStackedWidget()
        self.bar_total = CategoryBarChart()
        self.bar_total_scroll = QScrollArea()
        self.bar_total_scroll.setWidgetResizable(True)
        self.bar_total_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.bar_total_scroll.setStyleSheet(
            f"QScrollArea {{ background:{C.PANEL}; border:1px solid {C.BORDER}; }}"
        )
        self.bar_total_scroll.setWidget(self.bar_total)
        self.bar_time = SpendingRevenueChart()
        self.bar_stack.addWidget(self.bar_total_scroll)
        self.bar_stack.addWidget(self.bar_time)
        bar_layout.addWidget(self.bar_stack)
        self.stack.addWidget(bar_host)

        sankey_host = QWidget()
        sankey_host.setStyleSheet(f"background:{C.BG};")
        sankey_layout = QVBoxLayout(sankey_host)
        sankey_layout.setContentsMargins(16, 14, 16, 16)
        self.sankey = SankeyChart()
        self.sankey_scroll = QScrollArea()
        self.sankey_scroll.setWidgetResizable(True)
        self.sankey_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.sankey_scroll.setStyleSheet(
            f"QScrollArea {{ background:{C.PANEL}; border:1px solid {C.BORDER}; }}"
        )
        self.sankey_scroll.setWidget(self.sankey)
        sankey_layout.addWidget(self.sankey_scroll)
        self.stack.addWidget(sankey_host)

        return self.stack

    # -------------------------------------------------------------------- wire
    def _wire(self) -> None:
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.group_combo.currentIndexChanged.connect(self.reload)
        self.type_combo.currentIndexChanged.connect(self.reload)
        self.sort_check.toggled.connect(self.reload)
        self.search_edit.textChanged.connect(self.reload)
        self.account_combo.currentIndexChanged.connect(self.reload)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.from_edit.dateChanged.connect(self._dates_changed)
        self.to_edit.dateChanged.connect(self._dates_changed)
        self.reset_button.clicked.connect(self._reset_filters)
        self.pie_view.sliceActivated.connect(self._pie_slice_clicked)
        self.bar_total.barActivated.connect(self._bar_clicked)
        self.bar_time.monthActivated.connect(self._bar_clicked)

    def _pie_slice_clicked(self, index: int) -> None:
        if 0 <= index < len(self._pie_labels):
            self._chart_label_clicked(self._pie_labels[index])

    def _bar_clicked(self, index: int) -> None:
        if 0 <= index < len(self._bar_labels):
            self._chart_label_clicked(self._bar_labels[index])

    def _chart_label_clicked(self, label: str) -> None:
        if self.group() == "category" and self.mode() != "time":
            if label == "Other":
                self.view_hint.setText(
                    "“Other” combines several categories"
                )
                return
            if label == "(no category)":
                self._show_category_transactions(None)
                return
            category = self._find_category(label)
            if category is not None:
                self._show_category_transactions(category)
                return
        self._reveal_table_label(label)

    def _find_category(self, label: str) -> Category | None:
        kind = self.kind()
        categories = self.store.categories()
        target = label.casefold()
        for category in categories:
            if category.full_name.casefold() == target:
                return category
        for category in categories:
            if (
                category.parent_id is None
                and category.kind == kind
                and category.name.casefold() == target
            ):
                return category
        for category in categories:
            if category.name.casefold() == target:
                return category
        return None

    def _show_category_transactions(
        self, category: Category | None
    ) -> None:
        start, end = self.range()
        dialog = CategoryTransactionsDialog(
            self.store,
            category,
            self,
            start=start,
            end=end,
            account_id=self.account_combo.currentData(),
            initial_search=self.search_edit.text().strip(),
        )
        dialog.exec()
        if dialog.changed:
            self.reload()
            self.changed.emit()

    def _reveal_table_label(self, label: str) -> None:
        self.set_view("table")
        prefix = f"{label} :"
        matches: list[tuple[int, QTableWidgetItem]] = []
        for row in range(max(0, self.table.rowCount() - 1)):
            item = self.table.item(row, 0)
            if item is None:
                continue
            text = item.text()
            if text == label or text.startswith(prefix):
                matches.append((row, item))
        if matches:
            row, item = next(
                (
                    pair
                    for pair in matches
                    if pair[1].text() == label
                ),
                matches[0],
            )
            self.table.selectRow(row)
            self.table.scrollToItem(item)
            if len(matches) > 1:
                self.view_hint.setText(
                    f"{label} selected · {len(matches)} matching rows"
                )
            else:
                self.view_hint.setText(f"{label} selected")
            return
        self.view_hint.setText(f"{label} has no single table row")

    def focus_period(
        self, start: date, end: date, mode: str = "time"
    ) -> None:
        """Show a specific date range and mode, used by dashboard drill-down."""
        index = self.mode_combo.findData(mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        preset = self.preset_combo.findData("Custom")
        if preset >= 0:
            self.preset_combo.setCurrentIndex(preset)
        self._syncing_dates = True
        try:
            self.from_edit.setDate(QDate(start.year, start.month, start.day))
            self.to_edit.setDate(QDate(end.year, end.month, end.day))
        finally:
            self._syncing_dates = False
        self.reload()
        self.set_view("table")

    def _mode_changed(self) -> None:
        is_time = self.mode() == "time"
        self.group_combo.setEnabled(not is_time)
        self.sort_check.setEnabled(not is_time)
        self.reload()

    # ------------------------------------------------------------------ dates
    def _apply_preset(self) -> None:
        preset = self.preset_combo.currentData()
        today = date.today()
        if preset == "All dates":
            start, end = self.store.date_span()
        elif preset == "This month":
            start, end = _month_bounds(today)
        elif preset == "Last month":
            previous = today.replace(day=1) - timedelta(days=1)
            start, end = _month_bounds(previous)
        elif preset == "This year":
            start, end = date(today.year, 1, 1), date(today.year, 12, 31)
        elif preset == "Last year":
            start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
        else:
            return
        self._syncing_dates = True
        try:
            self.from_edit.setDate(QDate(start.year, start.month, start.day))
            self.to_edit.setDate(QDate(end.year, end.month, end.day))
        finally:
            self._syncing_dates = False

    def _preset_changed(self) -> None:
        self._apply_preset()
        self.reload()

    def _dates_changed(self) -> None:
        if self._syncing_dates:
            return
        if self.preset_combo.currentData() != "Custom":
            self._syncing_dates = True
            try:
                self.preset_combo.setCurrentIndex(
                    self.preset_combo.findData("Custom")
                )
            finally:
                self._syncing_dates = False
        self.reload()

    def _reset_filters(self) -> None:
        self.mode_combo.setCurrentIndex(0)
        self.group_combo.setCurrentIndex(0)
        self.type_combo.setCurrentIndex(0)
        self.sort_check.setChecked(True)
        self.search_edit.clear()
        self.account_combo.setCurrentIndex(0)
        self.preset_combo.setCurrentIndex(0)
        self._apply_preset()
        self.reload()

    # ------------------------------------------------------------------ state
    def mode(self) -> str:
        return self.mode_combo.currentData()

    def group(self) -> str:
        return self.group_combo.currentData()

    def kind(self) -> str:
        return self.type_combo.currentData()

    def range(self) -> tuple[date, date]:
        start = self.from_edit.date().toPython()
        end = self.to_edit.date().toPython()
        if end < start:
            start, end = end, start
        return start, end

    def set_view(self, view: str) -> None:
        self._view = view
        self.stack.setCurrentIndex(VIEWS.index(view))
        button = self._tool_buttons.get(view)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._update_hint()

    def _update_hint(self) -> None:
        names = {
            "table": "Table view",
            "pie": "Pie chart",
            "bar": "Bar chart",
            "sankey": "Sankey diagram",
        }
        text = names.get(self._view, "")
        if self._view in ("pie", "bar"):
            text += " · click a slice/bar to select its row"
        elif self._view == "sankey":
            text += " · hover nodes for totals"
        self.view_hint.setText(text)

    # ------------------------------------------------------------------- data
    def reload(self) -> None:
        accounts = self.store.accounts()
        current = self.account_combo.currentData()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("All accounts", None)
        for account in accounts:
            self.account_combo.addItem(account.name, account.id)
        index = self.account_combo.findData(current)
        self.account_combo.setCurrentIndex(index if index >= 0 else 0)
        self.account_combo.blockSignals(False)

        start, end = self.range()
        kind = self.kind()
        account_id = self.account_combo.currentData()
        search = self.search_edit.text()
        mode = self.mode()
        sort_by_amount = self.sort_check.isChecked()

        rows = self.store.report_rows(
            start,
            end,
            kind=kind,
            view_by=self.group(),
            account_id=account_id,
            search=search,
            sort_by_amount=sort_by_amount,
        )
        # Charts fold subcategories into their parent; the table keeps the
        # detail rows so each "Parent : Child" stays visible.
        chart_rows = rows
        if self.group() == "category":
            chart_rows = self.store.report_rows(
                start,
                end,
                kind=kind,
                view_by="category",
                account_id=account_id,
                search=search,
                sort_by_amount=sort_by_amount,
                rollup=True,
            )
        months = self.store.report_months(
            start,
            end,
            kind=kind,
            account_id=account_id,
            search=search,
        )

        if mode == "time":
            expense_total = sum(flow.expense for flow in months)
            income_total = sum(flow.income for flow in months)
        else:
            expense_total = sum(-row.expense for row in rows)
            income_total = sum(row.income for row in rows)
        net_total = income_total - expense_total
        self.expense_block.set_value(money(expense_total))
        self.income_block.set_value(money(income_total))
        self.total_block.set_value(money(net_total))
        self.total_block.value.setStyleSheet(
            f"color:{C.GREEN if net_total >= 0 else C.ORANGE};"
        )
        self.span_label.setText(
            f"{friendly_date(start.isoformat())} – {friendly_date(end.isoformat())}"
        )

        table_rows = self._display_rows(rows, kind, sort_by_amount)
        chart_display = (
            self._display_rows(chart_rows, kind, sort_by_amount)
            if chart_rows is not rows
            else table_rows
        )
        if mode == "time":
            self._populate_time_table(months)
            self._populate_pie(
                [
                    (f"{flow.label} {flow.year}", self._flow_amount(flow, kind), "")
                    for flow in months
                ],
                "No activity in this period",
            )
            self._populate_time_bars(months, kind)
            self.sankey.set_data(
                [
                    (f"{flow.label} {flow.year}", "Total", amount)
                    for flow in months
                    if (amount := self._flow_amount(flow, kind)) > 0
                ],
                f"No {kind} in this period",
            )
        else:
            self._populate_group_table(table_rows)
            self._populate_pie(
                [
                    (label, amount, color)
                    for label, color, amount, _expense, _income, _net in chart_display
                ],
                f"No {kind} in this period",
            )
            self._populate_group_bars(chart_display, kind)
            self.sankey.set_data(
                self.store.report_sankey(
                    start,
                    end,
                    kind=kind,
                    view_by=self.group(),
                    account_id=account_id,
                    search=search,
                ),
                f"No {kind} in this period",
            )
        self._update_hint()

    @staticmethod
    def _flow_amount(flow: MonthFlow, kind: str) -> float:
        return flow.income if kind == "income" else flow.expense

    def _display_rows(
        self, rows: list[ReportRow], kind: str, sort_by_amount: bool
    ) -> list[tuple[str, str, float, float, float, float]]:
        """Rows as (label, color, amount for this report type, expense, income, net)."""
        result = []
        for index, row in enumerate(rows):
            expense = -row.expense
            income = row.income
            amount = income if kind == "income" else expense
            color = row.color or DONUT_COLORS[index % len(DONUT_COLORS)]
            result.append((row.label, color, amount, expense, income, row.total))
        if sort_by_amount:
            result.sort(key=lambda item: (-item[2], item[0].lower()))
        return result

    def _set_headers(self, labels: list[str]) -> None:
        self.table.setColumnCount(len(labels))
        self.table.setHorizontalHeaderLabels(labels)
        for column in range(len(labels)):
            item = self.table.horizontalHeaderItem(column)
            if item is not None:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft
                    if column == 0
                    else Qt.AlignmentFlag.AlignRight
                )

    def _populate_group_table(
        self, display_rows: list[tuple[str, str, float, float, float, float]]
    ) -> None:
        self._set_headers(["Group", "Expense", "Income", "Total"])
        self.table.setRowCount(len(display_rows) + 1)
        for index, (label, color, _amount, expense, income, total) in enumerate(
            display_rows
        ):
            self._set_group_item(index, label, color)
            expense_item = self._amount_item(expense, C.ORANGE)
            income_item = self._amount_item(income, C.GREEN)
            total_item = self._amount_item(total, C.TEXT)
            self.table.setItem(index, 1, expense_item)
            self.table.setItem(index, 2, income_item)
            self.table.setItem(index, 3, total_item)
        total_row = len(display_rows)
        total_amount = sum(item[3] for item in display_rows)
        total_income = sum(item[4] for item in display_rows)
        footer = QTableWidgetItem("Total")
        footer.setFont(font(13, 600))
        footer.setForeground(QColor(C.TEXT))
        self.table.setItem(total_row, 0, footer)
        self.table.setItem(
            total_row, 1, self._amount_item(total_amount, C.ORANGE, strong=True)
        )
        self.table.setItem(
            total_row, 2, self._amount_item(total_income, C.GREEN, strong=True)
        )
        self.table.setItem(
            total_row,
            3,
            self._amount_item(total_income - total_amount, C.TEXT, strong=True),
        )

    def _populate_time_table(self, months: list[MonthFlow]) -> None:
        self._set_headers(["Month", "Expense", "Income", "Total"])
        self.table.setRowCount(len(months) + 1)
        for index, flow in enumerate(months):
            item = QTableWidgetItem(f"{flow.label} {flow.year}")
            item.setFont(font(14, 500))
            item.setForeground(QColor(C.TEXT))
            self.table.setItem(index, 0, item)
            self.table.setItem(index, 1, self._amount_item(flow.expense, C.ORANGE))
            self.table.setItem(index, 2, self._amount_item(flow.income, C.GREEN))
            self.table.setItem(index, 3, self._amount_item(flow.net, C.TEXT))
        total_row = len(months)
        expense = sum(flow.expense for flow in months)
        income = sum(flow.income for flow in months)
        footer = QTableWidgetItem("Total")
        footer.setFont(font(13, 600))
        self.table.setItem(total_row, 0, footer)
        self.table.setItem(total_row, 1, self._amount_item(expense, C.ORANGE, strong=True))
        self.table.setItem(total_row, 2, self._amount_item(income, C.GREEN, strong=True))
        self.table.setItem(total_row, 3, self._amount_item(income - expense, C.TEXT, strong=True))

    def _set_group_item(self, row: int, label: str, color: str) -> None:
        item = QTableWidgetItem(label)
        item.setFont(font(14, 500))
        item.setForeground(QColor(C.TEXT))
        pixmap = QPixmap(12, 12)
        pixmap.fill(QColor(color or C.MUTED))
        item.setIcon(QIcon(pixmap))
        self.table.setItem(row, 0, item)

    @staticmethod
    def _amount_item(value: float, color: str, strong: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(money(value) if abs(value) >= 0.005 else "")
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setForeground(QColor(color))
        item.setFont(font(13, 600 if strong else 400))
        return item

    def _populate_pie(
        self, items: list[tuple[str, float, str]], empty_text: str
    ) -> None:
        slices, total = _top_slices(items)
        self._pie_labels = [item.name for item in slices]
        self.pie_view.set_data(slices, total, empty_text)

    def _populate_group_bars(
        self, display_rows: list[tuple[str, str, float, float, float, float]], kind: str
    ) -> None:
        bars = [
            (label, amount, color)
            for label, color, amount, _expense, _income, _net in display_rows
            if amount > 0
        ]
        self._bar_labels = [label for label, _amount, _color in bars]
        self.bar_total.set_data(bars, f"No {kind} in this period")
        self.bar_stack.setCurrentWidget(self.bar_total_scroll)

    def _populate_time_bars(self, months: list[MonthFlow], kind: str) -> None:
        flows = [
            MonthFlow(
                year=flow.year,
                month=flow.month,
                label=flow.label,
                income=flow.income if kind == "income" else 0.0,
                expense=flow.expense if kind == "expense" else 0.0,
            )
            for flow in months
        ]
        self._bar_labels = [f"{flow.label} {flow.year}" for flow in flows]
        self.bar_time.set_data(flows)
        self.bar_stack.setCurrentWidget(self.bar_time)
