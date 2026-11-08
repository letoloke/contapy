"""The account sidebar: collapsible account groups with four balance columns."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..db import KIND_LABELS
from ..models import Account, Balance
from ..money import money
from ..theme import C, font
from .icons import (
    IconButton,
    draw_chevron,
    draw_download,
    draw_gear,
    draw_pencil,
    draw_warning,
)

HEADER_H = 26
FOOTER_H = 36
ROW_H = 25
COLUMNS = (0.442, 0.613, 0.776, 0.940)
COLUMN_LABELS = ("Reconciled", "Cleared", "Today", "Future")


@dataclass(slots=True)
class AccountRow:
    kind: str  # group | account | total | grand
    name: str
    values: tuple[float, float, float, float] | None = None
    account_id: int | None = None
    warning: bool = False
    collapsed: bool = False
    group: str | None = None


class AccountsHeader(QWidget):
    settingsClicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(HEADER_H)
        self._flash = False
        self.gear = IconButton(draw_gear, 22, "Preferences", parent=self)
        self.gear.move(6, 2)
        self.gear.clicked.connect(self.settingsClicked.emit)

    def resizeEvent(self, event):  # noqa: N802
        self.gear.move(6, 2)
        super().resizeEvent(event)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setFont(font(14, 400))
        p.setPen(QColor(C.MUTED))
        p.drawText(QRectF(40, 0, 120, HEADER_H),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Accounts")
        for edge, label in zip(COLUMNS, COLUMN_LABELS):
            right = self.width() * edge
            p.drawText(
                QRectF(right - 150, 0, 150, HEADER_H),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, HEADER_H - 1, self.width(), HEADER_H - 1)
        if self._flash:
            p.setPen(QPen(QColor(C.ACCENT), 2))
            p.drawLine(0, HEADER_H - 1, self.width(), HEADER_H - 1)
        p.end()

    def flash(self) -> None:
        self._flash = True
        self.update()
        QTimer.singleShot(800, self._clear_flash)

    def _clear_flash(self) -> None:
        self._flash = False
        self.update()


class AccountsFooter(QWidget):
    importClicked = Signal()
    editClicked = Signal()
    upClicked = Signal()
    downClicked = Signal()
    settingsClicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(FOOTER_H)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 20, 4)
        layout.setSpacing(10)
        layout.addStretch(1)

        self.import_btn = IconButton(draw_download, 28, "Import transactions", parent=self)
        self.edit_btn = IconButton(draw_pencil, 28, "Edit account", parent=self)
        self.up_btn = IconButton(
            lambda p, r, c, w: draw_chevron(p, r, c, "up"), 28, "Move account up", parent=self
        )
        self.down_btn = IconButton(
            lambda p, r, c, w: draw_chevron(p, r, c, "down"), 28, "Move account down", parent=self
        )
        self.settings_btn = IconButton(draw_gear, 28, "Preferences", parent=self)
        for button in (
            self.import_btn,
            self.edit_btn,
            self.up_btn,
            self.down_btn,
            self.settings_btn,
        ):
            layout.addWidget(button)

        self.import_btn.clicked.connect(self.importClicked.emit)
        self.edit_btn.clicked.connect(self.editClicked.emit)
        self.up_btn.clicked.connect(self.upClicked.emit)
        self.down_btn.clicked.connect(self.downClicked.emit)
        self.settings_btn.clicked.connect(self.settingsClicked.emit)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.PANEL))
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, 0, self.width(), 0)
        p.setFont(font(14, 400))
        p.setPen(QColor(C.TEXT_SOFT))
        p.drawText(
            QRectF(8, 0, 100, self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Your accounts",
        )
        p.setFont(font(11, 400))
        p.setPen(QColor(C.MUTED))
        p.drawText(
            QRectF(108, 0, 190, self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "↑↓ move · Enter open",
        )
        p.end()


class _AccountCanvas(QWidget):
    def __init__(self, panel: "AccountsPanel"):
        super().__init__()
        self.panel = panel
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("↑/↓ move through accounts · Enter opens the ledger")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hover = -1

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, max(1, len(self.panel.rows)) * ROW_H)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(300, len(self.panel.rows) * ROW_H)

    def row_at(self, y: int) -> int:
        index = y // ROW_H
        return index if 0 <= index < len(self.panel.rows) else -1

    def mouseMoveEvent(self, event):  # noqa: N802
        index = self.row_at(int(event.position().y()))
        if index != self._hover:
            self._hover = index
            self.update()
            if index >= 0:
                row = self.panel.rows[index]
                if row.kind == "account":
                    tip = ""
                    if row.warning:
                        tip = (
                            "This account has unreconciled transactions.\n"
                            "Open the ledger to review them."
                        )
                    elif row.values:
                        tip = (
                            f"{row.name}\n"
                            f"Reconciled {money(row.values[0])}  ·  Today {money(row.values[2])}\n"
                            f"Future {money(row.values[3])}\nDouble-click to open the ledger"
                        )
                    self.setToolTip(tip)
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                elif row.kind == "group":
                    self.setToolTip("Click to expand or collapse")
                    self.setCursor(Qt.CursorShape.PointingHandCursor)
                else:
                    self.setToolTip("")
                    self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        accounts = [row for row in self.panel.rows if row.kind == "account"]
        if not accounts:
            super().keyPressEvent(event)
            return
        current = next(
            (
                i for i, row in enumerate(accounts)
                if row.account_id == self.panel.selected_id
            ),
            -1,
        )
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            if current < 0:
                target = 0
            else:
                target = max(0, min(len(accounts) - 1, current + (-1 if key == Qt.Key.Key_Up else 1)))
            if target != current:
                self.panel.select_account(accounts[target].account_id)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            target = 0 if key == Qt.Key.Key_Home else len(accounts) - 1
            self.panel.select_account(accounts[target].account_id)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            step = -5 if key == Qt.Key.Key_PageUp else 5
            target = 0 if current < 0 else max(0, min(len(accounts) - 1, current + step))
            self.panel.select_account(accounts[target].account_id)
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if current < 0:
                account_id = accounts[0].account_id
                self.panel.select_account(account_id)
            else:
                account_id = accounts[current].account_id
            self.panel.openRequested.emit(account_id)
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):  # noqa: N802
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        self.update()
        super().focusOutEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            index = self.row_at(int(event.position().y()))
            if index >= 0:
                row = self.panel.rows[index]
                if row.kind == "group":
                    self.panel.toggle_group(row.group)
                    return
                if row.kind == "account":
                    self.panel.select_account(row.account_id)
                    return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        index = self.row_at(int(event.position().y()))
        if index >= 0:
            row = self.panel.rows[index]
            if row.kind == "account" and row.account_id is not None:
                self.panel.openRequested.emit(row.account_id)
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):  # noqa: N802
        index = self.row_at(int(event.pos().y()))
        account_id = None
        if index >= 0 and self.panel.rows[index].kind == "account":
            account_id = self.panel.rows[index].account_id
            self.panel.select_account(account_id)
        menu = QMenu(self)
        if account_id is not None:
            menu.addAction("Open ledger", lambda: self.panel.openRequested.emit(account_id))
            menu.addAction("Add transaction…", lambda: self.panel.addTransactionRequested.emit(account_id))
            menu.addAction("Edit account…", lambda: self.panel.editRequested.emit(account_id))
            menu.addSeparator()
            menu.addAction("Delete account…", lambda: self.panel.deleteRequested.emit(account_id))
            menu.addSeparator()
        menu.addAction("Add account…", self.panel.addRequested.emit)
        menu.exec(event.globalPos())

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(self.rect(), QColor(C.PANEL))

        width = self.width()
        name_x = max(50, int(width * 0.125))
        group_x = max(46, int(width * 0.114))
        warn_x = max(8, int(width * 0.022))
        value_font = font(14, 400)
        bold_value_font = font(14, 600)
        name_font = font(14, 400)
        bold_name_font = font(14, 600)
        grand_font = font(14, 700)

        if not self.panel.accounts:
            p.setPen(QColor(C.TEXT_SOFT))
            p.setFont(font(15, 600))
            p.drawText(
                QRectF(0, 66, width, 28),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                "No accounts yet",
            )
            p.setPen(QColor(C.MUTED))
            p.setFont(font(13, 400))
            p.drawText(
                QRectF(0, 94, width, 24),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                "Use Manage → New Account to get started",
            )

        for index, row in enumerate(self.panel.rows):
            y = index * ROW_H
            rect = QRectF(0, y, width, ROW_H)
            if rect.top() > self.height():
                break
            selected = (
                row.kind == "account"
                and self.panel.selected_id is not None
                and row.account_id == self.panel.selected_id
            )
            if selected:
                p.fillRect(rect, QColor(C.ROW_SELECTED))
            elif index == self._hover and row.kind in ("account", "group"):
                p.fillRect(rect, QColor(C.ROW_HOVER))

            if row.kind == "group":
                color = QColor(C.TEXT_SOFT)
                p.setFont(bold_name_font)
                p.setPen(color)
                chevron_rect = QRectF(warn_x + 6, y + 6, 13, 13)
                draw_chevron(
                    p,
                    chevron_rect,
                    QColor(C.TEXT_SOFT),
                    "right" if row.collapsed else "down",
                    1.5,
                )
                p.setPen(color)
                p.drawText(
                    QRectF(group_x, y, width * 0.35, ROW_H),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    row.name,
                )
            else:
                if row.warning:
                    draw_warning(
                        p,
                        QRectF(warn_x, y + 5.5, 14, 14),
                        QColor(C.WARNING),
                        1.2,
                    )
                if row.kind == "account":
                    base_font = name_font
                    name_color = QColor(C.ROW_SELECTED_TEXT if selected else C.TEXT)
                elif row.kind == "grand":
                    base_font = grand_font
                    name_color = QColor(C.ROW_SELECTED_TEXT if selected else C.TEXT)
                else:
                    base_font = bold_name_font
                    name_color = QColor(C.ROW_SELECTED_TEXT if selected else C.TEXT_SOFT)
                p.setFont(base_font)
                p.setPen(name_color)
                if row.kind == "grand":
                    text_x = max(8, int(width * 0.012))
                else:
                    text_x = max(50, int(width * 0.125))
                max_name_width = max(
                    40,
                    int(width * COLUMNS[0]) - text_x - 98,
                )
                metrics = QFontMetrics(base_font)
                label = metrics.elidedText(row.name, Qt.TextElideMode.ElideRight, max_name_width)
                p.drawText(
                    QRectF(text_x, y, max_name_width + 4, ROW_H),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )

            if row.values:
                p.setFont(bold_value_font if row.kind in ("group", "total", "grand") else value_font)
                for position, value in zip(COLUMNS, row.values):
                    edge = width * position
                    if selected:
                        color = QColor(C.ROW_SELECTED_TEXT)
                    elif value > 0.004:
                        color = QColor(C.GREEN)
                    elif value < -0.004:
                        color = QColor(C.ORANGE)
                    else:
                        color = QColor(C.TEXT_SOFT)
                    p.setPen(color)
                    p.drawText(
                        QRectF(edge - 150, y, 150, ROW_H),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        money(value),
                    )
            if row.kind == "total":
                p.setPen(QPen(QColor(C.SEPARATOR), 1))
                p.drawLine(0, int(rect.bottom()), width, int(rect.bottom()))
        if self.hasFocus():
            p.setPen(QPen(QColor(C.ACCENT), 1))
            p.drawLine(0, 0, width, 0)
        p.end()


class AccountsPanel(QWidget):
    accountSelected = Signal(int)
    openRequested = Signal(int)
    editRequested = Signal(int)
    deleteRequested = Signal(int)
    addRequested = Signal()
    importRequested = Signal()
    settingsRequested = Signal()
    reorderRequested = Signal(int, int)
    addTransactionRequested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.accounts: list[Account] = []
        self.balances: dict[int, Balance] = {}
        self.rows: list[AccountRow] = []
        self.selected_id: int | None = None
        self.expanded: set[str] = set(KIND_LABELS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = AccountsHeader(self)
        layout.addWidget(self.header)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.canvas = _AccountCanvas(self)
        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll, 1)

        self.footer = AccountsFooter(self)
        layout.addWidget(self.footer)

        self.header.settingsClicked.connect(self.settingsRequested.emit)
        self.footer.settingsClicked.connect(self.settingsRequested.emit)
        self.footer.importClicked.connect(self.importRequested.emit)
        self.footer.editClicked.connect(self._edit_selected)
        self.footer.upClicked.connect(lambda: self._reorder(-1))
        self.footer.downClicked.connect(lambda: self._reorder(1))

    # ------------------------------------------------------------- data flow
    def set_data(self, accounts: list[Account], balances: dict[int, Balance]) -> None:
        self.accounts = accounts
        self.balances = balances
        if self.selected_id is None or all(a.id != self.selected_id for a in accounts):
            self.selected_id = accounts[0].id if accounts else None
        self._rebuild()
        self._sync_buttons()

    def flash(self) -> None:
        self.header.flash()

    def select_account(self, account_id: int | None) -> None:
        if account_id is None:
            return
        self.selected_id = account_id
        self._sync_buttons()
        for index, row in enumerate(self.rows):
            if row.kind == "account" and row.account_id == account_id:
                self.scroll.ensureVisible(0, index * ROW_H + ROW_H // 2, 0, ROW_H * 2)
                break
        self.canvas.update()
        self.accountSelected.emit(account_id)

    def focus_list(self) -> None:
        if self.selected_id is None and self.accounts:
            self.select_account(self.accounts[0].id)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        self.canvas.update()

    def toggle_group(self, group: str | None) -> None:
        if not group:
            return
        if group in self.expanded:
            self.expanded.remove(group)
        else:
            self.expanded.add(group)
        self._rebuild()

    def _edit_selected(self) -> None:
        if self.selected_id is not None:
            self.editRequested.emit(self.selected_id)

    def _reorder(self, direction: int) -> None:
        if self.selected_id is not None:
            self.reorderRequested.emit(self.selected_id, direction)

    def _sync_buttons(self) -> None:
        has_selection = self.selected_id is not None
        for button in (self.footer.edit_btn, self.footer.up_btn, self.footer.down_btn):
            button.setEnabled(has_selection)

    def _values_for(self, account: Account) -> tuple[float, float, float, float]:
        balance = self.balances.get(account.id)
        if balance is None:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            balance.reconciled,
            balance.cleared,
            balance.today,
            balance.future,
        )

    def _rebuild(self) -> None:
        rows: list[AccountRow] = []
        for group in KIND_LABELS:
            members = [a for a in self.accounts if a.kind == group]
            if not members:
                continue
            totals = [0.0, 0.0, 0.0, 0.0]
            for account in members:
                for i, value in enumerate(self._values_for(account)):
                    totals[i] += value
            rows.append(
                AccountRow(
                    kind="group",
                    name=group,
                    values=tuple(totals),
                    collapsed=group not in self.expanded,
                    group=group,
                )
            )
            if group not in self.expanded:
                continue
            for account in members:
                rows.append(
                    AccountRow(
                        kind="account",
                        name=account.name,
                        values=self._values_for(account),
                        account_id=account.id,
                        warning=account.warning,
                        group=group,
                    )
                )
            if len(members) > 1:
                rows.append(
                    AccountRow(
                        kind="total",
                        name="Total",
                        values=tuple(totals),
                        group=group,
                    )
                )

        grand = [0.0, 0.0, 0.0, 0.0]
        for account in self.accounts:
            for i, value in enumerate(self._values_for(account)):
                grand[i] += value
        rows.append(AccountRow(kind="grand", name="Grand total", values=tuple(grand)))

        self.rows = rows
        self.canvas.setMinimumHeight(max(1, len(rows) * ROW_H))
        self.canvas.updateGeometry()
        self.canvas.update()
