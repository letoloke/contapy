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

        self._button("📄", "New transaction  (Ctrl+N)", self.newTransaction.emit, layout)
        self._button("🗂️", "Accounts", self.manageAccounts.emit, layout)

        menu_button = QToolButton(self)
        menu_button.setText("⌄")
        menu_button.setFont(font(15, 400))
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

        self._button("⬇️", "Import transactions", self.importRequested.emit, layout)
        layout.addSpacing(28)
        layout.addWidget(self._separator())

        self._button("🗃️", "Categories", self.categoriesRequested.emit, layout)
        self._button("👥", "Payees", self.payeesRequested.emit, layout)
        self._button("🧩", "Manage accounts", self.manageAccounts.emit, layout)
        self._button("📋", "Spending report", self.spendingFocus.emit, layout)
        self._button("📨", "Cash flow report", self.cashflowFocus.emit, layout)
        self._button("🪄", "Preferences", self.preferencesRequested.emit, layout)

        layout.addWidget(self._separator())
        self._button("📖", "Keyboard shortcuts", self.helpRequested.emit, layout)

        add_button = QToolButton(self)
        add_button.setText("Add")
        add_button.setIcon(QIcon(emoji_pixmap("📝", 20)))
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
        self._button("🥧", "Top spending by category", self.spendingFocus.emit, layout)
        self._button("👤", "Payees", self.payeesRequested.emit, layout)
        self._button("🏦", "Accounts", self.manageAccounts.emit, layout)
        self._button("📊", "Spending & revenue", self.cashflowFocus.emit, layout)
        self._button("🔄", "Refresh dashboard  (F5)", self.refreshRequested.emit, layout)
        self._button("🎯", "Preferences", self.preferencesRequested.emit, layout)
        self._button("❤️", "About ContaPy", self.aboutRequested.emit, layout)
        layout.addStretch(1)

    def _button(self, emoji: str, tip: str, slot, layout: QHBoxLayout) -> QToolButton:
        button = QToolButton(self)
        button.setIcon(QIcon(emoji_pixmap(emoji, 24)))
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
