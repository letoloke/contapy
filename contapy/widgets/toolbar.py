"""Top application chrome: emoji shortcuts and report quick actions."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QWidget,
)

from ..fontawesome import glyph_icon
from ..theme import C, emoji_pixmap, font


class AppToolbar(QWidget):
    newTransaction = Signal()
    newAccount = Signal()
    importRequested = Signal()
    exportRequested = Signal()
    manageAccounts = Signal()
    payeesRequested = Signal()
    categoriesRequested = Signal()
    preferencesRequested = Signal()
    aboutRequested = Signal()
    helpRequested = Signal()
    refreshRequested = Signal()
    spendingFocus = Signal()
    cashflowFocus = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 10, 4)
        layout.setSpacing(9)

        self._button(
            "file-circle-plus", "📄", "New transaction  (Ctrl+N)",
            self.newTransaction.emit, layout,
        )
        self._button(
            "wallet", "🗂️", "Accounts", self.manageAccounts.emit, layout
        )

        menu_button = QToolButton(self)
        menu_button.setIcon(self._icon("chevron-down", "⌄", 16))
        menu_button.setIconSize(QSize(16, 16))
        menu_button.setFixedSize(18, 34)
        menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_button.setToolTip("More account actions")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(menu_button)
        menu.addAction("New account…", self.newAccount.emit)
        menu.addAction("Import CSV…", self.importRequested.emit)
        menu.addAction("Export CSV…", self.exportRequested.emit)
        menu.addSeparator()
        menu.addAction("Preferences…", self.preferencesRequested.emit)
        menu_button.setMenu(menu)
        layout.addWidget(menu_button)

        layout.addWidget(self._separator())

        self._button(
            "download", "⬇️", "Import transactions",
            self.importRequested.emit, layout,
        )
        layout.addSpacing(28)
        layout.addWidget(self._separator())

        self._button("tags", "🗃️", "Categories", self.categoriesRequested.emit, layout)
        self._button("users", "👥", "Payees", self.payeesRequested.emit, layout)
        self._button(
            "sliders", "🧩", "Manage accounts", self.manageAccounts.emit, layout
        )
        self._button(
            "chart-pie", "📋", "Spending report", self.spendingFocus.emit, layout
        )
        self._button(
            "money-bill-transfer", "📨", "Cash flow report",
            self.cashflowFocus.emit, layout,
        )
        self._button("gear", "🪄", "Preferences", self.preferencesRequested.emit, layout)

        layout.addWidget(self._separator())
        self._button(
            "keyboard", "📖", "Keyboard shortcuts", self.helpRequested.emit, layout
        )

        add_button = QToolButton(self)
        add_button.setText("Add")
        add_button.setIcon(self._icon("circle-plus", "📝", 20))
        add_button.setIconSize(QSize(20, 20))
        add_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        add_button.setFont(font(14, 400))
        add_button.setFixedHeight(34)
        add_button.setMinimumWidth(74)
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.setToolTip("Add a transaction")
        add_button.clicked.connect(self.newTransaction.emit)
        layout.addWidget(add_button)

        layout.addSpacing(31)
        self._button(
            "chart-pie", "🥧", "Top spending by category",
            self.spendingFocus.emit, layout,
        )
        self._button(
            "user-group", "👤", "Payees", self.payeesRequested.emit, layout
        )
        self._button(
            "building-columns", "🏦", "Accounts",
            self.manageAccounts.emit, layout,
        )
        self._button(
            "chart-column", "📊", "Spending & revenue",
            self.cashflowFocus.emit, layout,
        )
        self._button(
            "arrows-rotate", "🔄", "Refresh dashboard  (F5)",
            self.refreshRequested.emit, layout,
        )
        self._button(
            "gear", "🎯", "Preferences", self.preferencesRequested.emit, layout
        )
        self._button(
            "heart", "❤️", "About ContaPy", self.aboutRequested.emit, layout
        )
        layout.addStretch(1)

    @staticmethod
    def _icon(glyph: str, emoji: str, size: int) -> QIcon:
        icon = glyph_icon(glyph, logical=size)
        return icon if icon is not None else QIcon(emoji_pixmap(emoji, size))

    def _button(
        self,
        glyph: str,
        emoji: str,
        tip: str,
        slot,
        layout: QHBoxLayout,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(self._icon(glyph, emoji, 24))
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(34, 34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFixedHeight(24)
        line.setStyleSheet(f"color:{C.SEPARATOR}; background:{C.SEPARATOR}; max-width:1px;")
        return line

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C.BG))
        p.setPen(QPen(QColor(C.BORDER), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()
