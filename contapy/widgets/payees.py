"""Payee management: list, edit and safe reassignment on deletion."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import DataStore
from ..models import Payee
from ..theme import C, font


class PayeeEditDialog(QDialog):
    """Create or rename a payee."""

    def __init__(
        self,
        store: DataStore,
        payee: Payee | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.payee = payee
        self.setWindowTitle("Edit Payee" if payee else "New Payee")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        heading = QLabel("Edit payee" if payee else "Add payee")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        note = QLabel(
            "Renaming a payee updates every transaction and scheduled item "
            "that uses it."
        )
        note.setWordWrap(True)
        note.setFont(font(12, 400))
        note.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(note)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)
        self.name_edit = QLineEdit(payee.name if payee else "")
        self.name_edit.setPlaceholderText("Payee name")
        form.addRow("Name", self.name_edit)
        self.notes_edit = QLineEdit(payee.notes if payee else "")
        self.notes_edit.setPlaceholderText("Optional notes")
        form.addRow("Notes", self.notes_edit)
        root.addLayout(form)
        root.addStretch(1)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton(
            "Save", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        save.setProperty("role", "primary")
        save.setDefault(True)
        save.setAutoDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.notes_edit.text().strip()

    def accept(self) -> None:
        name, _notes = self.values()
        if not name:
            QMessageBox.warning(self, "Missing name", "Enter a payee name.")
            return
        existing = self.store.payee_by_name(name)
        if existing is not None and (
            self.payee is None or existing.id != self.payee.id
        ):
            QMessageBox.warning(
                self,
                "Payee already exists",
                f"A payee named “{existing.name}” already exists.",
            )
            return
        super().accept()


class PayeeReassignDialog(QDialog):
    """Ask which payee should receive the transactions before deletion."""

    def __init__(
        self,
        payee: Payee,
        replacements: list[Payee],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.payee = payee
        self.setWindowTitle("Reassign payee transactions")
        self.setModal(True)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        heading = QLabel("Reassign transactions")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        count = payee.transaction_count
        message = QLabel(
            f"This payee has {count} associated transaction(s). "
            "Please select a replacement payee to reassign them to before "
            "deletion."
        )
        message.setWordWrap(True)
        message.setFont(font(12, 400))
        message.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(message)

        self.replacement_combo = QComboBox()
        for candidate in replacements:
            self.replacement_combo.addItem(candidate.name, candidate.id)
        root.addWidget(self.replacement_combo)
        root.addStretch(1)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        delete = buttons.addButton(
            "Reassign && delete", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        delete.setProperty("role", "primary")
        delete.setDefault(True)
        delete.setAutoDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def replacement_id(self) -> int | None:
        return self.replacement_combo.currentData()


class PayeesDialog(QDialog):
    """Manage registered payees and their transaction counts."""

    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.changed = False
        self._payees: list[Payee] = []
        self.setWindowTitle("Payees")
        self.setModal(True)
        self.setMinimumSize(680, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Payees")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        note = QLabel(
            "Registered payees with the number of posted and scheduled "
            "transactions linked to each one. Renaming updates all linked "
            "transactions. Deleting a payee with transactions requires "
            "choosing a replacement."
        )
        note.setWordWrap(True)
        note.setFont(font(12, 400))
        note.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(note)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Payee", "Notes", "Transactions"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit_payee())
        self.table.installEventFilter(self)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(2, 110)
        self.table.setStyleSheet(
            f"QTableWidget {{ background:{C.PANEL};"
            f" alternate-background-color:{C.ALT_ROW}; border:none; }}"
        )
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.new_button = QPushButton("New…")
        self.edit_button = QPushButton("Edit…")
        self.delete_button = QPushButton("Delete")
        close = QPushButton("Close")
        for button in (
            self.new_button,
            self.edit_button,
            self.delete_button,
            close,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(13, 400))
        self.new_button.setProperty("role", "primary")
        self.new_button.clicked.connect(self.new_payee)
        self.edit_button.clicked.connect(self.edit_payee)
        self.delete_button.clicked.connect(self.delete_payee)
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._reload()

    # ------------------------------------------------------------------ rows
    def _reload(self, select_id: int | None = None) -> None:
        self._payees = self.store.payee_records()
        self.table.setRowCount(len(self._payees))
        for index, payee in enumerate(self._payees):
            name_item = QTableWidgetItem(payee.name)
            name_item.setData(Qt.ItemDataRole.UserRole, payee.id)
            name_item.setForeground(QColor(C.TEXT))
            self.table.setItem(index, 0, name_item)

            notes_item = QTableWidgetItem(payee.notes)
            notes_item.setForeground(QColor(C.MUTED))
            self.table.setItem(index, 1, notes_item)

            count_item = QTableWidgetItem(str(payee.transaction_count))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(index, 2, count_item)

        if select_id is not None:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == select_id:
                    self.table.selectRow(row)
                    self.table.scrollToItem(item)
                    break
        self._update_buttons()

    def _selected_payee(self) -> Payee | None:
        rows = self.table.selectionModel().selectedRows(0)
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return None
        payee_id = int(item.data(Qt.ItemDataRole.UserRole))
        return next(
            (payee for payee in self._payees if payee.id == payee_id),
            None,
        )

    def _update_buttons(self, *_args) -> None:
        selected = self._selected_payee() is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    # --------------------------------------------------------------- actions
    def new_payee(self) -> None:
        dialog = PayeeEditDialog(self.store, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, notes = dialog.values()
        try:
            payee_id = self.store.add_payee(name, notes)
        except ValueError as error:
            self._warn(str(error))
            return
        self.changed = True
        self._reload(select_id=payee_id)

    def edit_payee(self) -> None:
        payee = self._selected_payee()
        if payee is None:
            return
        dialog = PayeeEditDialog(self.store, payee, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, notes = dialog.values()
        try:
            self.store.update_payee(payee.id, name, notes)
        except ValueError as error:
            self._warn(str(error))
            return
        self.changed = True
        self._reload(select_id=payee.id)

    def delete_payee(self) -> None:
        payee = self._selected_payee()
        if payee is None:
            return

        replacement_id: int | None = None
        if payee.transaction_count:
            replacements = [
                candidate
                for candidate in self._payees
                if candidate.id != payee.id
            ]
            if not replacements:
                QMessageBox.warning(
                    self,
                    "Cannot delete payee",
                    "This payee has linked transactions. Add another payee "
                    "first so those transactions can be reassigned.",
                )
                return
            dialog = PayeeReassignDialog(payee, replacements, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            replacement_id = dialog.replacement_id()
            if replacement_id is None:
                return
        else:
            answer = QMessageBox.question(
                self,
                "Delete payee?",
                f"Delete “{payee.name}”? It has no linked transactions.",
                QMessageBox.StandardButton.Cancel
                | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            self.store.delete_payee(payee.id, replacement_id)
        except ValueError as error:
            self._warn(str(error))
            return
        self.changed = True
        self._reload()

    def eventFilter(self, watched, event):  # noqa: N802
        if (
            watched is self.table
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        ):
            self.delete_payee()
            return True
        return super().eventFilter(watched, event)

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Payees", message)
