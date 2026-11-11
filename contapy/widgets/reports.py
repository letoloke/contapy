"""Functional reports window: table, pie and bar views over the ledger."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import QDate, QRectF, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
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
    QVBoxLayout,
    QWidget,
)

from ..db import DataStore
from ..models import MonthFlow, ReportRow, Slice
from ..money import friendly_date, money
from ..theme import C, DONUT_COLORS, font
from .charts import DonutChart, SpendingRevenueChart
from .icons import IconButton, draw_bars, draw_pie, draw_table

VIEWS = ("table", "pie", "bar")
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

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.bars: list[tuple[str, float, str]] = []
        self.empty_text = "No activity in this period"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(260)

    def set_data(self, bars: list[tuple[str, float, str]], empty_text: str = "") -> None:
        self.bars = [(label, amount, color) for label, amount, color in bars if amount > 0]
        if empty_text:
            self.empty_text = empty_text
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
            if index % 2 == 0:
                p.fillRect(
                    QRectF(0, top + row_h * index, width, row_h),
                    QColor(C.ALT_ROW),
                )
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(left, cy - 4.5, 9, 9))
            p.setPen(QColor(C.TEXT_SOFT))
            text = metrics.elidedText(label, Qt.TextElideMode.ElideRight, int(label_w))
            p.drawText(
                QRectF(left + 16, cy - row_h / 2, label_w - 16, row_h),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                text,
            )
            bar_len = max(2.0, (amount / max_value) * max(10.0, bar_right - bar_left))
            rect = QRectF(bar_left, cy - bar_h / 2, bar_len, bar_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
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


class ReportPieView(QWidget):
    """Donut with a readable amount/percentage legend beside it."""

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
        names = {"table": "Table view", "pie": "Pie chart", "bar": "Bar chart"}
        self.view_hint.setText(names.get(self._view, ""))

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
        self.pie_view.set_data(slices, total, empty_text)

    def _populate_group_bars(
        self, display_rows: list[tuple[str, str, float, float, float, float]], kind: str
    ) -> None:
        bars = [
            (label, amount, color)
            for label, color, amount, _expense, _income, _net in display_rows
        ]
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
        self.bar_time.set_data(flows)
        self.bar_stack.setCurrentWidget(self.bar_time)
