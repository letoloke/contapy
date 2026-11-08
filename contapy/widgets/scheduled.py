"""Scheduled transactions strip: tabs, table, and action bar."""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..models import Account, ScheduledItem
from ..money import money
from ..theme import C, font
from .icons import (
    IconButton,
    draw_bell,
    draw_calendar,
    draw_check_circle,
    draw_clock,
    draw_filter,
    draw_gear,
    draw_info,
)

TABS = ("Scheduled", "Future", "Remind")
TAB_W = 100
TAB_H = 37
HEADER_H = 35
ROW_H = 27
TOTAL_H = 27
ACTION_H = 45

# Content-relative x positions, tuned to the reference table.
X_CHECK = 12
X_DATE = 184
X_PAYEE = 365
X_CATEGORY = 495
X_STATUS = 575
X_EXPENSE_RIGHT = 675
X_INCOME_RIGHT = 745
X_MEMO = 784
X_ACCOUNT = 830
X_TOTAL_LABEL = 765

HEADER_LABELS = [
    (37, "Late"),
    (75, "Still"),
    (115, "Flag"),
    (150, "Next date"),
    (245, "Pay./Num."),
    (320, "Payee"),
    (448, "Category"),
    (530, "St."),
    (575, "Expense"),
    (660, "Income"),
    (740, "Memo"),
    (830, "Account"),
]


class _Tabs(QWidget):
    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(TAB_W)
        self.active = "Scheduled"
        self._hover = ""
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(TAB_W - 1, 0, TAB_W - 1, self.height())
        for index, name in enumerate(TABS):
            rect = QRectF(0, index * TAB_H, TAB_W - 1, TAB_H)
            if name == self.active:
                p.fillRect(rect, QColor(C.ACCENT))
            elif name == self._hover:
                p.fillRect(rect, QColor(C.ROW_HOVER))
            p.setFont(font(14, 400))
            p.setPen(QColor(C.ON_ACCENT if name == self.active else C.TEXT_SOFT))
            p.drawText(
                rect.adjusted(13, 0, 0, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                name,
            )
        p.end()

    def mousePressEvent(self, event):  # noqa: N802
        index = int(event.position().y()) // TAB_H
        if 0 <= index < len(TABS):
            name = TABS[index]
            if name != self.active:
                self.active = name
                self.update()
                self.changed.emit(name)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        index = int(event.position().y()) // TAB_H
        name = TABS[index] if 0 <= index < len(TABS) else ""
        if name != self._hover:
            self._hover = name
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = ""
        self.update()
        super().leaveEvent(event)


class _Header(QWidget):
    settingsClicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self.gear = IconButton(draw_gear, 22, "Preferences", parent=self)
        self.gear.move(4, 6)
        self.gear.clicked.connect(self.settingsClicked.emit)

    def resizeEvent(self, event):  # noqa: N802
        self.gear.move(4, 6)
        super().resizeEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setFont(font(14, 400))
        p.setPen(QColor(C.MUTED))
        for x, label in HEADER_LABELS:
            p.drawText(
                QRectF(x, 0, 130, HEADER_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, HEADER_H - 1, self.width(), HEADER_H - 1)
        p.end()


class _Canvas(QWidget):
    def __init__(self, panel: "ScheduledPanel"):
        super().__init__()
        self.panel = panel
        self._hover = -1
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("↑/↓ move · Enter open")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _row_at(self, y: int) -> int:
        index = int(y) // ROW_H
        return index if 0 <= index < len(self.panel.visible) else -1

    def minimumSizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        return QSize(700, max(1, len(self.panel.visible) * ROW_H + TOTAL_H + 8))

    def mouseMoveEvent(self, event):  # noqa: N802
        index = self._row_at(event.position().y())
        if index != self._hover:
            self._hover = index
            self.update()
            if index >= 0:
                item = self.panel.visible[index]
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{item.payee} · {money(item.amount)}\n"
                    f"{item.next_date} · {item.account_name}\n"
                    "Double-click to edit and post",
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

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._row_at(event.position().y())
            if index >= 0:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                item = self.panel.visible[index]
                self.panel.select_item(item.id, item.source)
                self.update()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        items = self.panel.visible
        if not items:
            super().keyPressEvent(event)
            return
        current = next(
            (
                i for i, item in enumerate(items)
                if item.id == self.panel.selected_id
                and item.source == self.panel.selected_source
            ),
            -1,
        )
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = -1 if event.key() == Qt.Key.Key_Up else 1
            target = 0 if current < 0 else max(0, min(len(items) - 1, current + step))
            if target == current:
                return
            item = items[target]
            self.panel.select_item(item.id, item.source)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if event.key() in (Qt.Key.Key_Home, Qt.Key.Key_End):
            item = items[0] if event.key() == Qt.Key.Key_Home else items[-1]
            self.panel.select_item(item.id, item.source)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if event.key() in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            step = -5 if event.key() == Qt.Key.Key_PageUp else 5
            target = 0 if current < 0 else max(0, min(len(items) - 1, current + step))
            item = items[target]
            self.panel.select_item(item.id, item.source)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if current < 0:
                item = items[0]
                self.panel.select_item(item.id, item.source)
            else:
                item = items[current]
            if item.source == "scheduled":
                self.panel.editPostRequested.emit(item.id)
            else:
                self.panel.openLedgerRequested.emit(item.account_id)
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        index = self._row_at(event.position().y())
        if index >= 0:
            item = self.panel.visible[index]
            self.panel.select_item(item.id, item.source)
            if item.source == "scheduled":
                self.panel.editPostRequested.emit(item.id)
            else:
                self.panel.openLedgerRequested.emit(item.account_id)
            return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))
        width = self.width()

        if not self.panel.visible:
            p.setPen(QColor(C.MUTED))
            p.setFont(font(14, 400))
            p.drawText(
                QRectF(0, 70, width, 30),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                "No transactions in this view",
            )
            p.end()
            return

        for index, item in enumerate(self.panel.visible):
            y = index * ROW_H
            rect = QRectF(0, y, width, ROW_H)
            selected = (
                item.id == self.panel.selected_id
                and item.source == self.panel.selected_source
                and self.hasFocus()
            )
            if selected:
                p.fillRect(rect, QColor(C.ROW_SELECTED))
            elif index == self._hover:
                p.fillRect(rect, QColor(C.ROW_HOVER))

            p.setPen(QPen(QColor(C.SEPARATOR), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(X_CHECK, y + 8, 11, 11), 2, 2)

            p.setFont(font(14, 400))
            p.setPen(QColor(C.TEXT if not selected else C.ROW_SELECTED_TEXT))
            p.drawText(
                QRectF(X_DATE, y, 120, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.next_date,
            )
            metrics = QFontMetrics(font(14, 400))
            date_w = metrics.horizontalAdvance(item.next_date)
            draw_calendar(p, QRectF(X_DATE + date_w + 8, y + 8, 12, 12), QColor(C.GREEN_BAR), 1.0)

            p.setPen(QColor(C.TEXT if not selected else C.ROW_SELECTED_TEXT))
            p.drawText(
                QRectF(X_PAYEE, y, 120, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.payee,
            )

            p.setPen(QColor(C.TEXT_SOFT if not selected else C.ROW_SELECTED_TEXT))
            p.drawText(
                QRectF(X_CATEGORY, y, 80, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.category_name,
            )

            if item.status == "remind":
                draw_bell(p, QRectF(X_STATUS, y + 7, 13, 13), QColor(C.WARNING), 1.4)
            elif item.status == "future":
                draw_clock(p, QRectF(X_STATUS, y + 7, 13, 13), QColor(C.FUTURE), 1.4)
            else:
                draw_check_circle(p, QRectF(X_STATUS, y + 7, 13, 13), QColor(C.GREEN), 1.5)

            if item.amount < 0:
                p.setPen(QColor(C.ORANGE))
                p.setFont(font(14, 400))
                p.drawText(
                    QRectF(X_EXPENSE_RIGHT - 150, y, 150, ROW_H),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    money(item.amount),
                )
            elif item.amount > 0:
                p.setPen(QColor(C.GREEN))
                p.setFont(font(14, 400))
                p.drawText(
                    QRectF(X_INCOME_RIGHT - 150, y, 150, ROW_H),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    money(item.amount),
                )

            p.setPen(QColor(C.MUTED))
            p.setFont(font(13, 400))
            p.drawText(
                QRectF(X_MEMO, y, 80, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.memo,
            )
            p.setPen(QColor(C.MUTED))
            p.drawText(
                QRectF(X_ACCOUNT, y, 180, ROW_H),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                item.account_name,
            )

        total_y = len(self.panel.visible) * ROW_H
        p.fillRect(QRectF(0, total_y, width, TOTAL_H), QColor(C.TOTAL_ROW))
        total_expense = sum(-i.amount for i in self.panel.visible if i.amount < 0)
        total_income = sum(i.amount for i in self.panel.visible if i.amount > 0)
        p.setFont(font(14, 600))
        if total_expense:
            p.setPen(QColor(C.ORANGE))
            p.drawText(
                QRectF(X_EXPENSE_RIGHT - 150, total_y, 150, TOTAL_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                money(-total_expense),
            )
        if total_income:
            p.setPen(QColor(C.GREEN))
            p.drawText(
                QRectF(X_INCOME_RIGHT - 150, total_y, 150, TOTAL_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                money(total_income),
            )
        p.setPen(QColor(C.TEXT))
        p.drawText(
            QRectF(X_TOTAL_LABEL, total_y, 100, TOTAL_H),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Total",
        )
        p.end()


class ScheduledPanel(QWidget):
    selectionChanged = Signal(int)
    postRequested = Signal(int)
    skipRequested = Signal(int)
    editPostRequested = Signal(int)
    openLedgerRequested = Signal(int)
    settingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.items: list[ScheduledItem] = []
        self.future: list[ScheduledItem] = []
        self.remind: list[ScheduledItem] = []
        self.visible: list[ScheduledItem] = []
        self.accounts: list[Account] = []
        self.selected_id: int | None = None
        self.selected_source: str | None = None
        self._date_filter: int | None = None
        self._account_id: int | None = None

        outer = QHBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self.tabs = _Tabs(self)
        self.tabs.changed.connect(self._on_tab_changed)
        outer.addWidget(self.tabs)

        right = QWidget(self)
        right.setStyleSheet(f"background:{C.PANEL};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.header = _Header(right)
        self.header.settingsClicked.connect(self.settingsRequested.emit)
        right_layout.addWidget(self.header)

        self.scroll = QScrollArea(right)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.canvas = _Canvas(self)
        self.scroll.setWidget(self.canvas)
        right_layout.addWidget(self.scroll, 1)

        self.action_bar = QWidget(right)
        self.action_bar.setFixedHeight(ACTION_H)
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(10, 6, 24, 6)
        action_layout.setSpacing(8)

        self.skip_btn = QPushButton("Skip")
        self.edit_btn = QPushButton("Edit && Post")
        self.post_btn = QPushButton("Post")
        for button in (self.skip_btn, self.edit_btn, self.post_btn):
            button.setProperty("role", "action")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(13, 400))
            action_layout.addWidget(button)
        self.skip_btn.setFixedWidth(52)
        self.edit_btn.setFixedWidth(96)
        self.post_btn.setFixedWidth(48)
        self.skip_btn.clicked.connect(self._request_skip)
        self.edit_btn.clicked.connect(self._request_edit)
        self.post_btn.clicked.connect(self._request_post)

        self.info_btn = IconButton(draw_info, 22, "About scheduled transactions", parent=self)
        self.info_btn.clicked.connect(self._show_info)
        action_layout.addWidget(self.info_btn)
        action_layout.addStretch(1)

        self.account_combo = QComboBox()
        self.account_combo.setFixedSize(175, 29)
        self.account_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.account_combo.currentIndexChanged.connect(self._account_changed)
        action_layout.addWidget(self.account_combo)

        self.filter_btn = IconButton(draw_filter, 28, "Filter by due date", parent=self)
        self.filter_btn.clicked.connect(self._open_filter_menu)
        action_layout.addWidget(self.filter_btn)

        right_layout.addWidget(self.action_bar)
        outer.addWidget(right, 1)

        self.action_bar.setStyleSheet(f"background:{C.BG};")
        self._sync_buttons()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.BORDER_SOFT), 1))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()

    # ------------------------------------------------------------- data flow
    def set_data(
        self,
        items: list[ScheduledItem],
        accounts: list[Account],
        future: list[ScheduledItem] | None = None,
        remind: list[ScheduledItem] | None = None,
    ) -> None:
        self.items = items
        self.accounts = accounts
        self.future = future or []
        self.remind = remind or []
        current_account = self._account_id
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItem("All", None)
        for account in accounts:
            self.account_combo.addItem(account.name, account.id)
        if current_account is not None:
            index = self.account_combo.findData(current_account)
            self.account_combo.setCurrentIndex(index if index >= 0 else 0)
            self._account_id = self.account_combo.currentData()
        else:
            self.account_combo.setCurrentIndex(0)
            self._account_id = None
        self.account_combo.blockSignals(False)
        self._rebuild()

    def select_item(self, item_id: int, source: str = "scheduled") -> None:
        self.selected_id = item_id
        self.selected_source = source
        self._sync_buttons()
        self.canvas.update()
        self.selectionChanged.emit(item_id)

    def show_tab(self, name: str) -> None:
        if name not in TABS:
            return
        self.tabs.active = name
        self.tabs.update()
        self._rebuild()

    def _chosen(self) -> ScheduledItem | None:
        for item in self.visible:
            if item.id == self.selected_id and item.source == self.selected_source:
                return item
        return None

    def _sync_buttons(self) -> None:
        item = self._chosen()
        if item is None:
            self.skip_btn.setVisible(True)
            self.post_btn.setVisible(True)
            self.edit_btn.setText("Edit && Post")
            self.skip_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            self.post_btn.setEnabled(False)
            return
        scheduled = item.source == "scheduled"
        self.skip_btn.setVisible(scheduled)
        self.post_btn.setVisible(scheduled)
        self.edit_btn.setText("Edit && Post" if scheduled else "Open Ledger")
        self.edit_btn.setToolTip(
            "Review and post this scheduled transaction"
            if scheduled
            else "Open the account ledger to edit this transaction"
        )
        self.skip_btn.setEnabled(scheduled)
        self.post_btn.setEnabled(scheduled)
        self.edit_btn.setEnabled(True)

    def _on_tab_changed(self, _name: str) -> None:
        self._rebuild()

    def _account_changed(self, _index: int) -> None:
        self._account_id = self.account_combo.currentData()
        self._rebuild()

    def _rebuild(self) -> None:
        today = date.today()
        tab = self.tabs.active
        pool = {
            "Scheduled": [i for i in self.items if i.status == "scheduled"],
            "Future": self.future,
            "Remind": self.remind,
        }.get(tab, [])
        items: list[ScheduledItem] = []
        for item in pool:
            when = date.fromisoformat(item.next_date)
            if self._account_id is not None and item.account_id != self._account_id:
                continue
            if self._date_filter is not None:
                if self._date_filter == -1:
                    if when >= today:
                        continue
                elif when > today + timedelta(days=self._date_filter):
                    continue
            items.append(item)
        items.sort(key=lambda i: (i.next_date, i.id))
        self.visible = items
        if self.selected_id is not None and not any(
            i.id == self.selected_id and i.source == self.selected_source for i in items
        ):
            self.selected_id = None
            self.selected_source = None
        if self.selected_id is None and items:
            self.selected_id = items[0].id
            self.selected_source = items[0].source
        self.canvas.setMinimumHeight(max(1, len(items) * ROW_H + TOTAL_H + 8))
        self.canvas.updateGeometry()
        self.canvas.update()
        self._sync_buttons()
        self.selectionChanged.emit(self.selected_id if self.selected_id is not None else -1)

    # --------------------------------------------------------------- actions
    def _request_skip(self) -> None:
        item = self._chosen()
        if item is not None and item.source == "scheduled":
            self.skipRequested.emit(item.id)

    def _request_edit(self) -> None:
        item = self._chosen()
        if item is None:
            return
        if item.source == "scheduled":
            self.editPostRequested.emit(item.id)
        else:
            self.openLedgerRequested.emit(item.account_id)

    def _request_post(self) -> None:
        item = self._chosen()
        if item is not None and item.source == "scheduled":
            self.postRequested.emit(item.id)

    def _show_info(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Scheduled transactions")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText(
            "Scheduled lists upcoming bills; Future lists posted transactions dated after today; "
            "Remind lists posted transactions marked Remind.\n\n"
            "• Select a scheduled row, then Post to add it to the ledger.\n"
            "• Edit & Post lets you review the amount and date first.\n"
            "• Skip removes it without touching your balances.\n"
            "• Double-click a future or remind row to open its ledger, where you can edit it."
        )
        box.exec()

    def _open_filter_menu(self) -> None:
        menu = QMenu(self)
        options = [
            ("All dates", None),
            ("Due within 7 days", 7),
            ("Due within 30 days", 30),
            ("Overdue", -1),
        ]
        for label, value in options:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._date_filter == value)
            action.triggered.connect(lambda _checked=False, v=value: self._set_date_filter(v))
        menu.exec(self.filter_btn.mapToGlobal(self.filter_btn.rect().bottomLeft()))

    def _set_date_filter(self, value: int | None) -> None:
        self._date_filter = value
        labels = {
            None: "All dates",
            7: "Due within 7 days",
            30: "Due within 30 days",
            -1: "Overdue",
        }
        self.filter_btn.setToolTip(f"Due-date filter: {labels.get(value, 'All dates')}")
        self._rebuild()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.end()
