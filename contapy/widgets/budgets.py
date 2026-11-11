"""Monthly category budgets with progress bars and spend trends."""

from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..db import DataStore
from ..models import BudgetStatus, ordered_categories
from ..money import money, money_short
from ..theme import C, font
from .icons import IconButton, draw_chevron


def _shift_month(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, 1)


def _month_label(value: date) -> str:
    return f"{calendar.month_name[value.month]} {value.year}"


class BudgetProgress(QWidget):
    """Rounded spent-versus-budget bar."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.spent = 0.0
        self.budget = 0.0
        self.setFixedHeight(11)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, spent: float, budget: float) -> None:
        self.spent = spent
        self.budget = budget
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(260, 11)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        radius = rect.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.BORDER))
        p.drawRoundedRect(rect, radius, radius)

        if self.budget > 0 and self.spent > 0:
            ratio = min(self.spent / self.budget, 1.0)
            width = max(rect.height(), rect.width() * ratio)
            if self.spent > self.budget + 0.005:
                color = C.RED_BAR
            elif self.spent >= self.budget * 0.8:
                color = C.WARNING
            else:
                color = C.GREEN_BAR
            p.setBrush(QColor(color))
            p.drawRoundedRect(
                QRectF(rect.left(), rect.top(), width, rect.height()),
                radius,
                radius,
            )
        p.end()


class BudgetSparkline(QWidget):
    """Compact six-month spending bars; click to zoom."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.values: list[float] = []
        self.color = C.MUTED
        self.setFixedSize(QSize(184, 46))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to zoom in on this category's spending trend")

    def set_data(self, values: list[float], color: str) -> None:
        self.values = list(values)
        self.color = color
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if not self.values:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width, height = self.width(), self.height()
        base_y = height - 8.0
        gap = 6.0
        bar_w = (width - gap * (len(self.values) - 1)) / len(self.values)
        peak = max(self.values) or 1.0
        bar_color = QColor(self.color)
        for index, value in enumerate(self.values):
            bar_h = (value / peak) * (height - 16.0)
            if value > 0:
                bar_h = max(2.0, bar_h)
            color = QColor(bar_color)
            color.setAlpha(255 if index == len(self.values) - 1 else 135)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            x = index * (bar_w + gap)
            p.drawRoundedRect(
                QRectF(x, base_y - bar_h, bar_w, bar_h), 2.5, 2.5
            )
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(QRectF(0, base_y + 1, width, 0).topLeft(), QRectF(0, base_y + 1, width, 0).topRight())
        p.end()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class BudgetTrendChart(QWidget):
    """Larger monthly spending bars used by the trend dialog."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.trend: list[tuple[str, float]] = []
        self.color = C.ACCENT
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, trend: list[tuple[str, float]], color: str) -> None:
        self.trend = list(trend)
        self.color = color
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))
        if not self.trend:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No spending trend yet")
            p.end()
            return

        width, height = self.width(), self.height()
        left, right = 24.0, 24.0
        top, bottom = 38.0, 48.0
        baseline = height - bottom
        peak = max(value for _, value in self.trend) or 1.0
        slots = width - left - right
        slot_w = slots / len(self.trend)
        bar_w = min(74.0, slot_w * 0.54)
        bar_color = QColor(self.color)
        amount_font = font(12, 500)
        label_font = font(12, 400)

        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(QRectF(left, baseline, slots, 0).topLeft(),
                   QRectF(left, baseline, slots, 0).topRight())

        for index, (label, value) in enumerate(self.trend):
            center = left + slot_w * (index + 0.5)
            bar_h = (value / peak) * (baseline - top)
            if value > 0:
                bar_h = max(3.0, bar_h)
            color = QColor(bar_color)
            color.setAlpha(255 if index == len(self.trend) - 1 else 160)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(
                QRectF(center - bar_w / 2, baseline - bar_h, bar_w, bar_h),
                4,
                4,
            )
            p.setFont(amount_font)
            p.setPen(QColor(C.TEXT_SOFT))
            metrics = QFontMetrics(amount_font)
            text = money_short(value)
            p.drawText(
                QRectF(center - 70, baseline - bar_h - 24, 140, 20),
                Qt.AlignmentFlag.AlignCenter,
                metrics.elidedText(text, Qt.TextElideMode.ElideRight, 136),
            )
            p.setFont(label_font)
            p.setPen(QColor(C.MUTED))
            p.drawText(
                QRectF(center - 34, baseline + 10, 68, 20),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )
        p.end()


class BudgetTrendDialog(QDialog):
    def __init__(
        self,
        status: BudgetStatus,
        month: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"{status.category_name} — spending trend")
        self.setModal(True)
        self.setMinimumSize(660, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        heading = QLabel(status.category_name)
        heading.setFont(font(20, 600))
        heading.setStyleSheet(f"color:{C.TITLE};")
        root.addWidget(heading)

        detail = QLabel(
            f"{month} · {money(status.spent)} spent of {money(status.budget)} budget"
        )
        detail.setFont(font(13, 400))
        detail.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(detail)

        chart = BudgetTrendChart()
        chart.set_data(status.trend, status.color)
        root.addWidget(chart, 1)

        buttons = QDialogButtonBox()
        close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.AcceptRole)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setProperty("role", "primary")
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)


class BudgetSummary(QWidget):
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

    def set_value(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        if color:
            self.value.setStyleSheet(f"color:{color};")


class BudgetRow(QFrame):
    trendClicked = Signal(object)

    def __init__(self, status: BudgetStatus, parent: QWidget | None = None):
        super().__init__(parent)
        self.status = status
        self.setObjectName("budgetRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#budgetRow {{ background:{C.PANEL};"
            f" border:1px solid {C.BORDER}; border-radius:6px; }}"
        )
        self.setMinimumHeight(94)

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 11, 14, 11)
        root.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"background:{status.color}; border-radius:5px;"
        )
        top.addWidget(dot)
        name = QLabel(status.category_name)
        name.setFont(font(15, 600))
        name.setStyleSheet(f"color:{C.TITLE};")
        top.addWidget(name)
        top.addStretch(1)
        self.percent = QLabel("")
        self.percent.setFont(font(12, 600))
        top.addWidget(self.percent)
        left.addLayout(top)

        self.amounts = QLabel("")
        self.amounts.setFont(font(12, 400))
        self.amounts.setStyleSheet(f"color:{C.MUTED};")
        left.addWidget(self.amounts)

        self.progress = BudgetProgress()
        self.progress.set_values(status.spent, status.budget)
        left.addWidget(self.progress)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.remaining = QLabel("")
        self.remaining.setFont(font(12, 400))
        bottom.addWidget(self.remaining)
        bottom.addStretch(1)
        left.addLayout(bottom)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(2)
        trend_label = QLabel("6-MONTH TREND")
        trend_label.setFont(font(10, 600))
        trend_label.setStyleSheet(f"color:{C.MUTED_DARK}; letter-spacing:1px;")
        trend_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(trend_label)
        self.spark = BudgetSparkline()
        self.spark.set_data([value for _, value in status.trend], status.color)
        self.spark.clicked.connect(lambda: self.trendClicked.emit(self.status))
        right.addWidget(self.spark)
        root.addLayout(right, 0)

        self._update_labels()

    def _update_labels(self) -> None:
        status = self.status
        self.amounts.setText(
            f"{money(status.spent)} spent of {money(status.budget)}"
        )
        if status.over:
            percent_color = C.RED_BAR
        elif status.ratio >= 0.8:
            percent_color = C.WARNING
        else:
            percent_color = C.GREEN
        self.percent.setText(f"{status.ratio * 100:.0f}%")
        self.percent.setStyleSheet(f"color:{percent_color};")
        if status.over:
            self.remaining.setText(f"Over by {money(-status.remaining)}")
            self.remaining.setStyleSheet(f"color:{C.RED_BAR};")
        else:
            self.remaining.setText(f"Remaining {money(status.remaining)}")
            self.remaining.setStyleSheet(f"color:{C.TEXT_SOFT};")


class BudgetSettingsDialog(QDialog):
    """Set or clear the monthly amount for every expense category."""

    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.changed = False
        self.setWindowTitle("Set budgets")
        self.setModal(True)
        self.setMinimumSize(540, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        heading = QLabel("Monthly budgets")
        heading.setFont(font(19, 600))
        heading.setStyleSheet(f"color:{C.TITLE};")
        root.addWidget(heading)

        intro = QLabel(
            "Set a monthly amount for each expense category. Zero removes the "
            "budget. Amounts repeat every month, and a budget on a category "
            "also counts its subcategories' spending."
        )
        intro.setWordWrap(True)
        intro.setFont(font(13, 400))
        intro.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"background:{C.PANEL}; border:1px solid {C.BORDER};")
        body = QWidget()
        body.setStyleSheet(f"background:{C.PANEL};")
        grid = QGridLayout(body)
        grid.setContentsMargins(14, 12, 14, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._header("Category"), 0, 0, 1, 2)
        grid.addWidget(self._header("Monthly budget"), 0, 2)
        self.spins: dict[int, QDoubleSpinBox] = {}
        row = 1
        for category in ordered_categories(self.store.categories()):
            if category.kind != "expense":
                continue
            dot = QLabel()
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(f"background:{category.color}; border-radius:5px;")
            name = QLabel(category.full_name)
            name.setFont(font(13, 400))
            name.setStyleSheet(f"color:{C.TEXT};")
            wrap = QWidget()
            wrap_layout = QHBoxLayout(wrap)
            wrap_layout.setContentsMargins(0, 0, 0, 0)
            wrap_layout.setSpacing(8)
            wrap_layout.addWidget(dot)
            wrap_layout.addWidget(name, 1)
            grid.addWidget(wrap, row, 0, 1, 2)
            spin = QDoubleSpinBox()
            spin.setPrefix("$ ")
            spin.setRange(0.0, 999_999_999.0)
            spin.setDecimals(2)
            spin.setSingleStep(50.0)
            spin.setGroupSeparatorShown(True)
            spin.setValue(self.store.budget_amount(category.id))
            spin.setFixedWidth(178)
            self.spins[category.id] = spin
            grid.addWidget(spin, row, 2)
            row += 1
        grid.setRowStretch(row, 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        hint = QLabel("Budgets are stored locally with the rest of the ledger.")
        hint.setFont(font(12, 400))
        hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        root.addWidget(hint)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save budgets", QDialogButtonBox.ButtonRole.AcceptRole)
        for button in (cancel, save):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        save.setProperty("role", "primary")
        save.setAutoDefault(True)
        save.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save)
        root.addWidget(buttons)

    @staticmethod
    def _header(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setFont(font(10, 600))
        label.setStyleSheet(f"color:{C.MUTED}; letter-spacing:1px;")
        return label

    def _save(self) -> None:
        for category_id, spin in self.spins.items():
            spin.interpretText()
            amount = round(spin.value(), 2)
            if abs(amount - self.store.budget_amount(category_id)) > 0.005:
                self.store.set_budget(category_id, amount)
                self.changed = True
        super().accept()


class BudgetWindow(QMainWindow):
    changed = Signal()

    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        self.store = store
        self.month = date.today().replace(day=1)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Budgets — ContaPy")
        self.setMinimumSize(980, 620)
        self.resize(1120, 720)
        self.setStyleSheet(f"QMainWindow {{ background:{C.BG}; }}")

        self._build_ui()
        self.reload()

    # --------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet(f"background:{C.BG};")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        root.addWidget(self._build_toolbar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(f"QScrollArea {{ background:{C.BG}; border:none; }}")
        self.content = QWidget()
        self.content.setStyleSheet(f"background:{C.BG};")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 14, 16, 16)
        self.content_layout.setSpacing(10)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, 1)
        self.setCentralWidget(central)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(94)
        header.setStyleSheet(
            f"background:{C.PANEL}; border-bottom:1px solid {C.BORDER};"
        )
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 12, 20, 10)
        layout.setSpacing(18)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("Budgets")
        title.setFont(font(22, 600))
        title.setStyleSheet(f"color:{C.TITLE};")
        self.span_label = QLabel("")
        self.span_label.setFont(font(13, 400))
        self.span_label.setStyleSheet(f"color:{C.MUTED};")
        titles.addWidget(title)
        titles.addWidget(self.span_label)
        layout.addLayout(titles)
        layout.addStretch(1)

        self.budgeted_block = BudgetSummary("Budgeted", C.TEXT)
        self.spent_block = BudgetSummary("Spent", C.ORANGE)
        self.remaining_block = BudgetSummary("Remaining", C.GREEN)
        layout.addWidget(self.budgeted_block)
        layout.addWidget(self.spent_block)
        layout.addWidget(self.remaining_block)
        return header

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget()
        toolbar.setFixedHeight(48)
        toolbar.setStyleSheet(
            f"background:{C.BG}; border-bottom:1px solid {C.BORDER};"
        )
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 7, 14, 7)
        layout.setSpacing(6)

        self.prev_button = IconButton(
            lambda p, r, c, w: draw_chevron(p, r, c, "left"),
            30,
            "Previous month",
            parent=toolbar,
        )
        self.prev_button.clicked.connect(lambda: self._shift_month(-1))
        layout.addWidget(self.prev_button)

        self.next_button = IconButton(
            lambda p, r, c, w: draw_chevron(p, r, c, "right"),
            30,
            "Next month",
            parent=toolbar,
        )
        self.next_button.clicked.connect(lambda: self._shift_month(1))
        layout.addWidget(self.next_button)

        self.this_month = QPushButton("This month")
        self.this_month.setProperty("role", "action")
        self.this_month.setCursor(Qt.CursorShape.PointingHandCursor)
        self.this_month.setFont(font(13, 400))
        self.this_month.clicked.connect(self._show_this_month)
        layout.addWidget(self.this_month)

        layout.addSpacing(8)
        self.month_title = QLabel("")
        self.month_title.setFont(font(14, 600))
        self.month_title.setStyleSheet(f"color:{C.TEXT};")
        layout.addWidget(self.month_title)
        layout.addStretch(1)

        self.settings_button = QPushButton("Set budgets…")
        self.settings_button.setProperty("role", "primary")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setFont(font(13, 400))
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)
        return toolbar

    # ------------------------------------------------------------------ data
    def reload(self) -> None:
        statuses = self.store.budget_report(self.month)
        budgeted = sum(status.budget for status in statuses)
        spent = sum(status.spent for status in statuses)
        remaining = budgeted - spent

        self.span_label.setText(
            f"{_month_label(self.month)} · monthly budgets"
            if statuses
            else f"{_month_label(self.month)} · no budgets yet"
        )
        self.month_title.setText(_month_label(self.month))
        self.budgeted_block.set_value(money(budgeted))
        self.spent_block.set_value(money(spent))
        self.remaining_block.set_value(
            money(remaining), C.GREEN if remaining >= 0 else C.RED_BAR
        )

        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not statuses:
            empty = QLabel(
                "No budgets set for this month.\n"
                "Use “Set budgets…” to give your expense categories a monthly limit."
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            empty.setFont(font(14, 400))
            empty.setStyleSheet(f"color:{C.MUTED};")
            empty.setMinimumHeight(220)
            self.content_layout.addWidget(empty)
            self.content_layout.addStretch(1)
            return

        for status in statuses:
            row = BudgetRow(status)
            row.trendClicked.connect(self.open_trend)
            self.content_layout.addWidget(row)
        self.content_layout.addStretch(1)

    # --------------------------------------------------------------- actions
    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Left:
            self._shift_month(-1)
            return
        if event.key() == Qt.Key.Key_Right:
            self._shift_month(1)
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def _shift_month(self, delta: int) -> None:
        self.month = _shift_month(self.month, delta)
        self.reload()

    def _show_this_month(self) -> None:
        self.month = date.today().replace(day=1)
        self.reload()

    def open_settings(self) -> None:
        dialog = BudgetSettingsDialog(self.store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.changed:
            self.reload()
            self.changed.emit()

    def open_trend(self, status: BudgetStatus) -> None:
        BudgetTrendDialog(status, _month_label(self.month), self).exec()
