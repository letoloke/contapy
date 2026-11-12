"""HomeBank-style account ledger window."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QFontMetrics, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..config import ledger_status_choice
from ..dates import format_date
from ..db import DataStore
from ..models import Account, Balance, TransactionRow
from ..money import money
from ..theme import C, CLEARED, font
from .dialogs import DateRangeDialog, TransactionDialog
from .import_dialog import CsvImportDialog
from .icons import (
    IconButton,
    draw_bell,
    draw_check_circle,
    draw_flag,
    draw_reconciled,
    draw_void,
)

ROWS = 10
FLAG, DATE, PAYEE, CATEGORY, TAGS, STATUS, EXPENSE, INCOME, BALANCE, MEMO = range(ROWS)
HEADERS = (
    "Flag",
    "Date",
    "Payee",
    "Category",
    "Tags",
    "Status",
    "Expense",
    "Income",
    "Balance",
    "Memo",
)
FILTER_DAY = 24
CUSTOM_RANGE = "Custom range…"


def ledger_date(iso: str) -> str:
    return format_date(iso)


def closest_amount_ids(
    rows: list[TransactionRow],
    selected_ids: set[int],
    total: float,
    tolerance: float = 0.005,
) -> list[int]:
    """Ids of unselected, non-voided rows whose amount is closest to ``total``."""
    candidates = [
        row for row in rows if row.id not in selected_ids and not row.voided
    ]
    if not candidates:
        return []
    best = min(abs(row.amount - total) for row in candidates)
    return [
        row.id
        for row in candidates
        if abs(abs(row.amount - total) - best) <= tolerance
    ]


def date_bounds(
    period: str, custom: tuple[date, date] | None = None
) -> tuple[date | None, date | None]:
    if period == CUSTOM_RANGE:
        return custom if custom else (None, None)
    today = date.today()
    if period == "This month":
        start = today.replace(day=1)
        last_day = calendar.monthrange(today.year, today.month)[1]
        return start, today.replace(day=last_day)
    if period == "Last month":
        last = today.replace(day=1) - timedelta(days=1)
        return last.replace(day=1), last
    if period == "This year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if period == "Last year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    return None, None


class LedgerModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[TransactionRow] = []

    def set_rows(self, rows: list[TransactionRow]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def row_at(self, row: int) -> TransactionRow:
        return self.rows[row]

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else ROWS

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        row = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == DATE:
                return ledger_date(row.date)
            if col == PAYEE:
                return row.payee
            if col == CATEGORY:
                return row.category_name
            if col == TAGS:
                return row.tags
            if col == EXPENSE:
                return money(row.amount) if row.amount < 0 else ""
            if col == INCOME:
                return money(row.amount) if row.amount > 0 else ""
            if col == BALANCE:
                return money(row.balance)
            if col == MEMO:
                return row.memo
            return ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (EXPENSE, INCOME, BALANCE):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ToolTipRole:
            detail = (
                f"{row.date} · {row.payee}\n"
                f"{row.category_name} · {money(row.amount)}\n"
                f"Balance after: {money(row.balance)}"
            )
            if row.tags:
                detail += f"\nTags: {row.tags}"
            return detail
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if section in (EXPENSE, INCOME, BALANCE):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return None


class LedgerDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value_font = font(13, 400)
        self._payee_font = font(14, 400)
        self._small_font = font(12, 400)
        self.highlight_ids: set[int] = set()

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(option.rect.width(), 27)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        if not index.isValid():
            return
        model = index.model()
        row: TransactionRow = model.row_at(index.row())
        col = index.column()
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        highlighted = not selected and row.id in self.highlight_ids

        bg = QColor(C.ROW_SELECTED) if selected else QColor(
            C.PANEL if index.row() % 2 == 0 else C.ALT_ROW
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(rect, bg)
        if highlighted:
            tint = QColor(C.ACCENT)
            tint.setAlpha(52)
            painter.fillRect(rect, tint)
            painter.fillRect(
                QRectF(rect.left(), rect.top(), 3, rect.height()),
                QColor(C.ACCENT),
            )
        painter.setClipRect(rect)

        pad = 8
        text_color = QColor(C.ROW_SELECTED_TEXT) if selected else QColor("#ffffff")
        muted = QColor(C.ROW_SELECTED_TEXT) if selected else QColor("#ffffff")
        if row.voided and not selected:
            text_color = QColor(C.MUTED_DARK)
            muted = QColor(C.MUTED_DARK)
        category_color = text_color

        if col == FLAG:
            if row.flagged:
                draw_flag(
                    painter,
                    QRectF(rect.left() + rect.width() / 2 - 7, rect.top() + 7, 14, 13),
                    QColor(C.WARNING),
                    1.4,
                )
        elif col == DATE:
            self._text(painter, rect, pad, ledger_date(row.date), self._small_font, muted)
        elif col == PAYEE:
            self._text(painter, rect, pad, row.payee, self._payee_font, text_color)
        elif col == CATEGORY:
            self._text(painter, rect, pad, row.category_name, self._value_font, category_color)
        elif col == TAGS:
            self._text(painter, rect, pad, row.tags, self._small_font, muted)
        elif col == STATUS:
            x = rect.left() + 7
            if row.voided:
                draw_void(
                    painter,
                    QRectF(x, rect.top() + 7, 14, 14),
                    QColor(C.MUTED_DARK),
                )
                x += 18
            elif row.reconciled:
                draw_reconciled(painter, QRectF(x, rect.top() + 7, 14, 14), QColor(C.RECONCILED))
                x += 18
            elif row.cleared:
                draw_check_circle(painter, QRectF(x, rect.top() + 7, 14, 14), QColor(CLEARED))
                x += 18
            if row.remind and not row.voided:
                draw_bell(painter, QRectF(x, rect.top() + 7, 14, 14), QColor(C.WARNING))
        elif col == EXPENSE:
            if row.amount < 0:
                if row.voided and not selected:
                    color = QColor(C.MUTED_DARK)
                else:
                    color = QColor(C.ROW_SELECTED_TEXT) if selected else QColor(C.RED_BAR)
                self._text(
                    painter,
                    rect,
                    pad,
                    money(row.amount),
                    self._value_font,
                    color,
                    Qt.AlignmentFlag.AlignRight,
                )
        elif col == INCOME:
            if row.amount > 0:
                if row.voided and not selected:
                    color = QColor(C.MUTED_DARK)
                else:
                    color = QColor(C.ROW_SELECTED_TEXT) if selected else QColor(C.GREEN)
                self._text(
                    painter,
                    rect,
                    pad,
                    money(row.amount),
                    self._value_font,
                    color,
                    Qt.AlignmentFlag.AlignRight,
                )
        elif col == BALANCE:
            if row.voided and not selected:
                color = QColor(C.MUTED_DARK)
            elif selected:
                color = QColor(C.ROW_SELECTED_TEXT)
            else:
                color = QColor(C.GREEN) if row.balance > 0 else QColor(C.RED_BAR)
            self._text(
                painter,
                rect,
                pad,
                money(row.balance),
                self._value_font,
                color,
                Qt.AlignmentFlag.AlignRight,
            )
        elif col == MEMO:
            self._text(painter, rect, pad, row.memo, self._small_font, muted)

        painter.restore()

    @staticmethod
    def _text(
        painter: QPainter,
        rect,
        pad: int,
        text: str,
        text_font,
        color: QColor,
        align=Qt.AlignmentFlag.AlignLeft,
    ) -> None:
        if not text:
            return
        inner = QRectF(rect.left() + pad, rect.top(), rect.width() - pad * 2, rect.height())
        metrics = QFontMetrics(text_font)
        text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(inner.width()))
        painter.setFont(text_font)
        painter.setPen(color)
        painter.drawText(
            inner,
            align | Qt.AlignmentFlag.AlignVCenter,
            text,
        )


class LedgerTable(QTableView):
    emptyMessage = "No transactions match these filters"
    editRequested = Signal()
    deleteRequested = Signal()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.editRequested.emit()
            return
        if event.key() == Qt.Key.Key_Delete:
            self.deleteRequested.emit()
            return
        if event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End) and self.model().rowCount():
            row = 0 if event.key() == Qt.Key.Key_Home else self.model().rowCount() - 1
            self.selectRow(row)
            self.setCurrentIndex(self.model().index(row, 0))
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        model = self.model()
        if model is not None and model.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(
                self.viewport().rect(),
                Qt.AlignmentFlag.AlignCenter,
                self.emptyMessage,
            )
            p.end()


class LedgerSummary(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 3, 12, 3)
        layout.setSpacing(6)

        self.left = QLabel("")
        self.left.setTextFormat(Qt.TextFormat.RichText)
        self.left.setFont(font(12, 400))
        layout.addWidget(self.left)
        layout.addStretch(1)

        self.balance_labels: dict[str, QLabel] = {}
        for key, text in (
            ("reconciled", "Reconciled"),
            ("cleared", "Cleared"),
            ("today", "Today"),
            ("future", "Future"),
        ):
            label = QLabel(text)
            label.setFont(font(11, 400))
            label.setStyleSheet(f"color:{C.MUTED};")
            self.balance_labels[key + "_label"] = label
            layout.addWidget(label)
            value = QLabel("")
            value.setFont(font(12, 400))
            self.balance_labels[key] = value
            layout.addWidget(value)
            if key != "future":
                layout.addSpacing(12)

    def set_data(
        self,
        count: int,
        selected_count: int,
        selected_sum: float,
        balances: Balance | None,
        total_sum: float,
    ) -> None:
        parts = [f"<span style='color:{C.MUTED}'>{count} transactions</span>"]
        if selected_count:
            parts.append(f"<span style='color:{C.MUTED}'>{selected_count} selected</span>")
        amount = selected_sum if selected_count else total_sum
        color = C.GREEN if amount > 0 else (C.RED_BAR if amount < 0 else C.TEXT_SOFT)
        parts.append(f"<span style='color:{C.MUTED}'>sum:</span> <span style='color:{color}'>{money(amount)}</span>")
        self.left.setText(" &nbsp;·&nbsp; ".join(parts))

        values = {
            "reconciled": balances.reconciled if balances else 0.0,
            "cleared": balances.cleared if balances else 0.0,
            "today": balances.today if balances else 0.0,
            "future": balances.future if balances else 0.0,
        }
        for key, value in values.items():
            label = self.balance_labels[key]
            color = C.GREEN if value > 0.004 else (C.RED_BAR if value < -0.004 else C.TEXT_SOFT)
            label.setText(money(value))
            label.setStyleSheet(f"color:{color};")

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class LedgerWindow(QMainWindow):
    changed = Signal()

    def __init__(
        self,
        store: DataStore,
        account_id: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self.store = store
        self.account_id = account_id
        self.account: Account | None = store.account(account_id)
        self.all_rows: list[TransactionRow] = []
        self.balance_snapshot: Balance | None = None
        self._custom_range: tuple[date, date] | None = None
        self._previous_period = "All date"
        self._highlight_ids: set[int] = set()
        self._suspend_highlight = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(1180, 540)
        self.resize(1260, 680)
        self.setWindowTitle(
            f"{self.account.name} — Account" if self.account else "Account"
        )
        self.setStyleSheet(f"QMainWindow {{ background: {C.BG}; }}")

        self._build_menus()
        self._build_ui()
        self.reload()

    # ------------------------------------------------------------------ menus
    def _action(self, text: str, slot, shortcut: str | None = None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: slot())
        self.addAction(action)
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()
        bar.setNativeMenuBar(False)
        bar.setFont(font(14, 400))

        self.act_new = self._action("New Transaction…", self.add_transaction, "Ctrl+N")
        self.act_edit = self._action("Edit Transaction…", self.edit_transaction)
        self.act_inherit = self._action("Inherit Transaction…", self.inherit_transaction, "Ctrl+D")
        self.act_delete = self._action("Delete Transaction", self.delete_transaction)
        self.act_select_all = self._action("Select All", self._select_all)
        self.act_import = self._action("Import CSV…", self.import_csv)
        self.act_export = self._action("Export CSV…", self.export_csv)
        self.act_close = self._action("Close", self.close)
        self.act_close.setShortcuts([QKeySequence("Ctrl+W"), QKeySequence("Escape")])

        account_menu = bar.addMenu("Account")
        account_menu.addAction(self.act_new)
        account_menu.addSeparator()
        account_menu.addAction(self.act_import)
        account_menu.addAction(self.act_export)
        account_menu.addSeparator()
        account_menu.addAction(self.act_close)

        edit_menu = bar.addMenu("Edit")
        edit_menu.addAction(self.act_edit)
        edit_menu.addAction(self.act_inherit)
        edit_menu.addAction(self.act_delete)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_select_all)

        tools_menu = bar.addMenu("Tools")
        tools_menu.addAction(self._action("Mark Cleared", lambda: self._set_cleared(True)))
        tools_menu.addAction(self._action("Mark Reconciled", lambda: self._set_reconciled(True)))
        tools_menu.addAction(self._action("Mark Uncleared", lambda: self._set_cleared(False)))
        tools_menu.addSeparator()
        tools_menu.addAction(self._action("Toggle Remind", self._toggle_remind))
        tools_menu.addAction(self._action("Toggle Flag", self._toggle_flag))
        tools_menu.addAction(self._action("Toggle Void", self._toggle_void))
        tools_menu.addSeparator()
        self.act_void_highlighted = self._action(
            "Void Highlighted", self._void_highlighted, "Alt+V"
        )
        self.act_void_highlighted.setEnabled(False)
        tools_menu.addAction(self.act_void_highlighted)

    # --------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        central = QWidget()
        central.setStyleSheet(f"background:{C.BG};")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Filter bar
        filter_bar = QWidget()
        filter_bar.setFixedHeight(48)
        filter_bar.setStyleSheet(
            f"background:{C.BG}; border-bottom:1px solid {C.BORDER};"
        )
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(8)

        self.account_label = QLabel(self.account.name if self.account else "Account")
        self.account_label.setFont(font(15, 600))
        self.account_label.setStyleSheet(f"color:{C.TEXT};")
        self.account_label.setMinimumWidth(90)
        self.account_label.setMaximumWidth(170)
        filter_layout.addWidget(self.account_label)

        self.date_combo = QComboBox()
        self.date_combo.addItems(
            [
                "All date",
                "This month",
                "Last month",
                "This year",
                "Last year",
                CUSTOM_RANGE,
            ]
        )
        self.date_combo.setFixedWidth(132)
        filter_layout.addWidget(self.date_combo)

        self.payee_combo = QComboBox()
        self.payee_combo.setFixedWidth(150)
        filter_layout.addWidget(self.payee_combo)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Any type", None)
        self.type_combo.addItem("Expense", "expense")
        self.type_combo.addItem("Income", "income")
        self.type_combo.setFixedWidth(112)
        filter_layout.addWidget(self.type_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItem("Any status", None)
        self.status_combo.addItem("Unreconciled", "unreconciled")
        self.status_combo.addItem("Cleared", "cleared")
        self.status_combo.addItem("Reconciled", "reconciled")
        self.status_combo.addItem("Remind", "remind")
        self.status_combo.addItem("Flagged", "flagged")
        self.status_combo.addItem("Voided", "voided")
        default_status = ledger_status_choice()
        status_index = self.status_combo.findData(
            None if default_status == "any" else default_status
        )
        if status_index >= 0:
            self.status_combo.setCurrentIndex(status_index)
        self.status_combo.setFixedWidth(134)
        filter_layout.addWidget(self.status_combo)

        filter_layout.addStretch(1)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(230)
        filter_layout.addWidget(self.search_edit)

        root.addWidget(filter_bar)

        self.summary = LedgerSummary()
        root.addWidget(self.summary)

        self.model = LedgerModel(self)
        self.table = LedgerTable()
        self.table.setModel(self.model)
        self.delegate = LedgerDelegate(self.table)
        self.table.setItemDelegate(self.delegate)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(27)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setFixedHeight(31)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(FLAG, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(FLAG, 30)
        header.setSectionResizeMode(DATE, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(DATE, 112)
        header.setSectionResizeMode(PAYEE, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(PAYEE, 195)
        header.setSectionResizeMode(CATEGORY, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(CATEGORY, 170)
        header.setSectionResizeMode(TAGS, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(TAGS, 140)
        header.setSectionResizeMode(STATUS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(STATUS, 64)
        header.setSectionResizeMode(EXPENSE, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(EXPENSE, 104)
        header.setSectionResizeMode(INCOME, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(INCOME, 104)
        header.setSectionResizeMode(BALANCE, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(BALANCE, 112)
        header.setSectionResizeMode(MEMO, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet(
            f"QTableView {{ background:{C.PANEL}; border:none; "
            f"selection-background-color: transparent; }}"
        )
        root.addWidget(self.table, 1)

        # Action bar
        action_bar = QWidget()
        action_bar.setFixedHeight(50)
        action_bar.setStyleSheet(
            f"background:{C.BG}; border-top:1px solid {C.BORDER};"
        )
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(10, 8, 12, 8)
        action_layout.setSpacing(8)

        self.add_btn = QPushButton("Add")
        self.inherit_btn = QPushButton("Inherit")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        for button in (self.add_btn, self.inherit_btn, self.edit_btn, self.delete_btn):
            button.setProperty("role", "action")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(13, 400))
            action_layout.addWidget(button)
        self.add_btn.setFixedWidth(58)
        self.inherit_btn.setFixedWidth(72)
        self.edit_btn.setFixedWidth(58)
        self.delete_btn.setFixedWidth(66)

        action_layout.addWidget(self._separator())

        self.clear_btn = IconButton(
            draw_check_circle, 30, "Mark selected cleared", color=CLEARED, parent=self
        )
        self.reconcile_btn = IconButton(
            draw_reconciled, 30, "Mark selected reconciled", parent=self
        )
        self.remind_btn = IconButton(
            draw_bell, 30, "Toggle remind for selected", color=C.WARNING, parent=self
        )
        self.flag_btn = IconButton(
            draw_flag, 30, "Toggle flag for selected", color=C.WARNING, parent=self
        )
        self.void_btn = IconButton(
            draw_void, 30, "Toggle void for selected", color=C.MUTED_DARK, parent=self
        )
        for button in (
            self.clear_btn,
            self.reconcile_btn,
            self.remind_btn,
            self.flag_btn,
            self.void_btn,
        ):
            action_layout.addWidget(button)

        action_layout.addStretch(1)
        self.keyboard_hint = QLabel("↑↓ move · Enter open · Del delete")
        self.keyboard_hint.setFont(font(11, 400))
        self.keyboard_hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        action_layout.addWidget(self.keyboard_hint)
        action_layout.addSpacing(14)
        self.selected_label = QLabel("0 selected")
        self.selected_label.setFont(font(12, 400))
        self.selected_label.setStyleSheet(f"color:{C.MUTED};")
        action_layout.addWidget(self.selected_label)

        root.addWidget(action_bar)
        self.setCentralWidget(central)

        # wiring
        self.add_btn.clicked.connect(self.add_transaction)
        self.inherit_btn.clicked.connect(self.inherit_transaction)
        self.edit_btn.clicked.connect(self.edit_transaction)
        self.delete_btn.clicked.connect(self.delete_transaction)
        self.clear_btn.clicked.connect(lambda: self._set_cleared(True))
        self.reconcile_btn.clicked.connect(lambda: self._set_reconciled(True))
        self.remind_btn.clicked.connect(self._toggle_remind)
        self.flag_btn.clicked.connect(self._toggle_flag)
        self.void_btn.clicked.connect(self._toggle_void)

        self.date_combo.activated.connect(self._date_filter_changed)
        self.payee_combo.currentTextChanged.connect(lambda _v: self._apply_filters())
        self.type_combo.currentIndexChanged.connect(lambda _v: self._apply_filters())
        self.status_combo.currentIndexChanged.connect(lambda _v: self._apply_filters())
        self.search_edit.textChanged.connect(lambda _v: self._apply_filters())
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._selection_changed())
        self.table.doubleClicked.connect(lambda _index: self.edit_transaction())
        self.table.editRequested.connect(self._edit_selected_from_keyboard)
        self.table.deleteRequested.connect(self.delete_transaction)
        self.search_edit.returnPressed.connect(self._focus_table)
        self.table.setToolTip("Use ↑/↓ to move through transactions; press Enter to open.")

        self._update_buttons()

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedHeight(24)
        line.setStyleSheet(f"color:{C.SEPARATOR}; background:{C.SEPARATOR}; max-width:1px;")
        return line

    # --------------------------------------------------------------- keyboard
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._focus_table)

    def focus_table(self) -> None:
        self._focus_table()

    def _focus_table(self) -> None:
        if self.model.rowCount() and not self._selected_rows():
            self.table.selectRow(0)
            self.table.setCurrentIndex(self.model.index(0, PAYEE))
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)

    def _edit_selected_from_keyboard(self) -> None:
        if not self._selected_rows():
            if not self.model.rowCount():
                return
            self.table.selectRow(0)
            self.table.setCurrentIndex(self.model.index(0, PAYEE))
        self.edit_transaction()

    # ------------------------------------------------------------------- data
    def reload(self, preserve_selection: bool = True) -> None:
        selected = self._selected_ids() if preserve_selection else []
        self.account = self.store.account(self.account_id)
        if self.account is None:
            self.close()
            return
        self.setWindowTitle(f"{self.account.name} — Account")
        self.account_label.setText(self.account.name)
        self.all_rows = self.store.ledger_rows(self.account_id)
        self.balance_snapshot = self.store.balances().get(self.account_id)

        current_payee = self.payee_combo.currentText()
        self.payee_combo.blockSignals(True)
        self.payee_combo.clear()
        self.payee_combo.addItem("All payee", None)
        for payee in sorted({row.payee for row in self.all_rows if row.payee}):
            self.payee_combo.addItem(payee, payee)
        if current_payee and current_payee != "All payee":
            index = self.payee_combo.findText(current_payee)
            if index >= 0:
                self.payee_combo.setCurrentIndex(index)
        else:
            self.payee_combo.setCurrentIndex(0)
        self.payee_combo.blockSignals(False)

        self._apply_filters(selected)

    def _date_filter_changed(self, _index: int) -> None:
        period = self.date_combo.currentText()
        if period == CUSTOM_RANGE:
            start, end = self._ask_custom_range()
            if start is None or end is None:
                self.date_combo.blockSignals(True)
                self.date_combo.setCurrentText(self._previous_period)
                self.date_combo.blockSignals(False)
                return
            self._custom_range = (start, end)
        else:
            self._custom_range = None
        self._previous_period = period
        self._apply_filters()

    def _ask_custom_range(self) -> tuple[date | None, date | None]:
        if self._custom_range:
            start, end = self._custom_range
        else:
            start, end = date_bounds(self._previous_period)
            if start is None or end is None:
                days = [date.fromisoformat(row.date) for row in self.all_rows]
                if days:
                    start, end = min(days), max(days)
                else:
                    today = date.today()
                    start = today.replace(day=1)
                    end = today
        dialog = DateRangeDialog(start, end, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None, None
        return dialog.values()

    def _apply_filters(self, selected_ids: list[int] | None = None) -> None:
        if selected_ids is None:
            selected_ids = self._selected_ids()
        start, end = date_bounds(self.date_combo.currentText(), self._custom_range)
        payee = self.payee_combo.currentText()
        if payee == "All payee":
            payee = ""
        type_filter = self.type_combo.currentData()
        status_filter = self.status_combo.currentData()
        search = self.search_edit.text().strip().lower()

        visible: list[TransactionRow] = []
        for row in self.all_rows:
            day = date.fromisoformat(row.date)
            if start and day < start:
                continue
            if end and day > end:
                continue
            if payee and row.payee != payee:
                continue
            if type_filter == "expense" and row.amount >= 0:
                continue
            if type_filter == "income" and row.amount <= 0:
                continue
            if status_filter == "voided":
                if not row.voided:
                    continue
            elif status_filter and row.voided:
                continue
            if status_filter == "unreconciled" and (row.cleared or row.reconciled):
                continue
            if status_filter == "cleared" and (not row.cleared or row.reconciled):
                continue
            if status_filter == "reconciled" and not row.reconciled:
                continue
            if status_filter == "remind" and not row.remind:
                continue
            if status_filter == "flagged" and not row.flagged:
                continue
            if search and search not in (
                " ".join(
                    (
                        row.payee,
                        row.category_name,
                        row.memo,
                        row.payment,
                        row.number,
                        row.tags,
                    )
                )
            ).lower():
                continue
            visible.append(row)

        # HomeBank shows the newest activity first while the balance column
        # still reflects the running balance at each transaction.
        visible.sort(key=lambda r: (r.date, r.id), reverse=True)
        self.model.set_rows(visible)
        self._restore_selection(selected_ids)
        self._update_summary()
        self._update_buttons()
        self._refresh_highlight()

    def _restore_selection(self, ids: list[int]) -> None:
        if not ids:
            return
        selection = QItemSelection()
        for row_index, row in enumerate(self.model.rows):
            if row.id in ids:
                selection.select(
                    self.model.index(row_index, 0),
                    self.model.index(row_index, ROWS - 1),
                )
        if not selection.isEmpty():
            self.table.selectionModel().select(
                selection,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )

    def _selected_rows(self) -> list[TransactionRow]:
        rows = []
        selection = self.table.selectionModel()
        if selection is None:
            return rows
        for index in selection.selectedRows(0):
            if 0 <= index.row() < len(self.model.rows):
                rows.append(self.model.rows[index.row()])
        return rows

    def _selected_ids(self) -> list[int]:
        return [row.id for row in self._selected_rows()]

    def _selection_changed(self) -> None:
        self._update_summary()
        self._update_buttons()
        self._refresh_highlight()

    def _refresh_highlight(self) -> None:
        """Highlight unselected amounts closest to the selected total."""
        selected = self._selected_rows()
        if self._suspend_highlight or len(selected) < 2:
            ids: set[int] = set()
        else:
            selected_ids = {row.id for row in selected}
            selected_sum = sum(row.amount for row in selected if not row.voided)
            ids = set(
                closest_amount_ids(self.model.rows, selected_ids, selected_sum)
            )
        self._highlight_ids = ids
        self.delegate.highlight_ids = ids
        self.table.viewport().update()
        self.act_void_highlighted.setEnabled(bool(ids))
        if ids:
            count = len(ids)
            rows = "row" if count == 1 else "rows"
            self.keyboard_hint.setText(
                f"Alt+V voids {count} highlighted {rows}"
            )
            self.keyboard_hint.setStyleSheet(
                f"color:{C.WARNING}; font-weight:600;"
            )
        else:
            self.keyboard_hint.setText("↑↓ move · Enter open · Del delete")
            self.keyboard_hint.setStyleSheet(f"color:{C.MUTED_DARK};")

    def _update_summary(self) -> None:
        selected = self._selected_rows()
        selected_sum = sum(row.amount for row in selected if not row.voided)
        total_sum = sum(row.amount for row in self.model.rows if not row.voided)
        self.summary.set_data(
            len(self.model.rows),
            len(selected),
            selected_sum,
            self.balance_snapshot,
            total_sum,
        )
        self.selected_label.setText(f"{len(selected)} selected")

    def _update_buttons(self) -> None:
        has_selection = bool(self._selected_rows())
        for button in (
            self.inherit_btn,
            self.edit_btn,
            self.delete_btn,
            self.clear_btn,
            self.reconcile_btn,
            self.remind_btn,
            self.flag_btn,
            self.void_btn,
        ):
            button.setEnabled(has_selection)
        for action in (self.act_edit, self.act_inherit, self.act_delete):
            action.setEnabled(has_selection)
        self.act_select_all.setEnabled(bool(self.model.rows))

    # ---------------------------------------------------------------- actions
    def _select_all(self) -> None:
        self.table.selectAll()

    def _dialog_for(self, draft, title: str) -> TransactionDialog:
        return TransactionDialog(
            self.store,
            self.store.accounts(),
            self.store.categories(),
            draft=draft,
            title=title,
            parent=self,
        )

    def add_transaction(self) -> None:
        dialog = self._dialog_for(None, "New Transaction")
        index = dialog.account_combo.findData(self.account_id)
        if index >= 0:
            dialog.account_combo.setCurrentIndex(index)
        if dialog.exec() != TransactionDialog.DialogCode.Accepted:
            return
        draft = dialog.draft()
        if draft is None:
            return
        if draft.transfer_account_id is not None:
            group = self.store.add_transfer(draft, draft.transfer_account_id)
            self.reload(preserve_selection=False)
            ids = [
                row.id for row in self.store.transfer_legs(group)
                if row.account_id == self.account_id
            ]
            self._select_ids(ids)
        else:
            new_id = self.store.add_transaction(draft)
            self.reload(preserve_selection=False)
            self._select_ids([new_id])
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def inherit_transaction(self) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        source = selected[0]
        from ..models import TransactionDraft

        draft = TransactionDraft(
            date=date.today().isoformat(),
            account_id=source.account_id,
            payee=source.payee,
            category_id=source.category_id,
            amount=source.amount,
            memo=source.memo,
            cleared=True,
            reconciled=False,
            payment=source.payment,
            number=source.number,
            tags=source.tags,
        )
        dialog = self._dialog_for(draft, "Inherit Transaction")
        if dialog.exec() != TransactionDialog.DialogCode.Accepted:
            return
        new_draft = dialog.draft()
        if new_draft is None:
            return
        if new_draft.transfer_account_id is not None:
            group = self.store.add_transfer(new_draft, new_draft.transfer_account_id)
            self.reload(preserve_selection=False)
            ids = [
                row.id for row in self.store.transfer_legs(group)
                if row.account_id == self.account_id
            ]
            self._select_ids(ids)
        else:
            new_id = self.store.add_transaction(new_draft)
            self.reload(preserve_selection=False)
            self._select_ids([new_id])
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def edit_transaction(self) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        source = selected[0]
        from ..models import TransactionDraft

        transfer_id = source.transfer_id
        transfer_account_id = None
        edit_source = source
        if transfer_id:
            legs = self.store.transfer_legs(transfer_id)
            outgoing = next((r for r in legs if r.amount < 0), None)
            incoming = next((r for r in legs if r.amount > 0), None)
            if outgoing is not None and incoming is not None:
                edit_source = outgoing
                transfer_account_id = incoming.account_id

        draft = TransactionDraft(
            date=edit_source.date,
            account_id=edit_source.account_id,
            payee=edit_source.payee,
            category_id=edit_source.category_id,
            amount=edit_source.amount,
            memo=edit_source.memo,
            cleared=source.cleared,
            reconciled=source.reconciled,
            remind=source.remind,
            flagged=source.flagged,
            voided=source.voided,
            payment=edit_source.payment,
            number=edit_source.number,
            tags=edit_source.tags,
            transfer_account_id=transfer_account_id,
            transfer_id=transfer_id,
        )
        dialog = self._dialog_for(draft, "Edit Transaction")
        if dialog.exec() != TransactionDialog.DialogCode.Accepted:
            return
        new_draft = dialog.draft()
        if new_draft is None:
            return
        if transfer_id:
            if new_draft.transfer_account_id is not None:
                self.store.update_transfer(
                    transfer_id, new_draft, new_draft.transfer_account_id
                )
            else:
                self.store.delete_transaction(source.id)
                self.store.add_transaction(new_draft)
        elif new_draft.transfer_account_id is not None:
            self.store.delete_transaction(source.id)
            self.store.add_transfer(new_draft, new_draft.transfer_account_id)
        else:
            self.store.update_transaction(source.id, new_draft)
        self.reload()
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def delete_transaction(self) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        label = "this transaction" if len(selected) == 1 else f"{len(selected)} transactions"
        answer = QMessageBox.question(
            self,
            "Delete transaction?",
            f"Delete {label}? This cannot be undone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for row in selected:
            self.store.delete_transaction(row.id)
        self.reload(preserve_selection=False)
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def _set_cleared(self, cleared: bool) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        self.store.update_transaction_flags(
            ids, cleared=cleared, reconciled=False
        )
        self.reload()
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def _set_reconciled(self, reconciled: bool) -> None:
        ids = self._selected_ids()
        if not ids:
            return
        if reconciled:
            self.store.update_transaction_flags(ids, cleared=True, reconciled=True)
        else:
            self.store.update_transaction_flags(ids, cleared=True, reconciled=False)
        self.reload()
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def _toggle_remind(self) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        target = not all(row.remind for row in selected)
        self.store.update_transaction_flags([row.id for row in selected], remind=target)
        self.reload()
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def _toggle_flag(self) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        target = not all(row.flagged for row in selected)
        self.store.update_transaction_flags([row.id for row in selected], flagged=target)
        self.reload()
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def _toggle_void(self) -> None:
        selected = self._selected_rows()
        if not selected:
            return
        target = not all(row.voided for row in selected)
        self.store.update_transaction_flags([row.id for row in selected], voided=target)
        self.reload()
        self.changed.emit()
        QTimer.singleShot(0, self._focus_table)

    def _void_highlighted(self) -> None:
        ids = sorted(self._highlight_ids)
        if not ids:
            return
        self._suspend_highlight = True
        try:
            self.store.update_transaction_flags(ids, voided=True)
            self.reload()
            self.changed.emit()
        finally:
            self._suspend_highlight = False
        self._highlight_ids = set()
        self.delegate.highlight_ids = set()
        self.table.viewport().update()
        self.act_void_highlighted.setEnabled(False)
        QTimer.singleShot(0, self._focus_table)

    def _select_ids(self, ids: list[int]) -> None:
        self._restore_selection(ids)
        self._selection_changed()

    def import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import transactions", "", "CSV files (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            dialog = CsvImportDialog(
                self.store,
                self.store.accounts(),
                path,
                self.account_id,
                self,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            added, skipped, duplicates = self.store.import_csv(
                path,
                account_id=dialog.account_id(),
                memo_as_payee=dialog.memo_as_payee(),
                mapping=dialog.current_mapping(),
                skip_rows=dialog.skip_row_indexes(),
                apply_rules=dialog.apply_rules(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        self.reload()
        self.changed.emit()
        self._show_message(
            "Import finished",
            f"Imported {added} transactions."
            + (f"\nSkipped {duplicates} duplicate(s)." if duplicates else "")
            + (
                f"\nSkipped {skipped} rows that could not be parsed."
                if skipped
                else ""
            ),
        )

    def export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export transactions", "contapy-export.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        count = self.store.export_csv(path)
        self._show_message("Export finished", f"Exported {count} transactions.")

    @staticmethod
    def _show_message(title: str, text: str) -> None:
        box = QMessageBox()
        box.setWindowTitle(title)
        box.setText(text)
        box.exec()
