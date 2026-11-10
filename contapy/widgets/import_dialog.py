"""CSV import dialog with editable, remembered header mappings."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..csv_io import CsvPlan, parse_amount, parse_date, read_csv_plan
from ..dates import format_date
from ..db import DataStore, import_fingerprint
from ..models import Account
from ..money import money
from ..theme import C, font


class CsvImportDialog(QDialog):
    FIELDS = (
        ("date", "Date", True),
        ("amount", "Amount", True),
        ("payee", "Payee", False),
        ("memo", "Memo", False),
        ("payment", "Payment", False),
        ("number", "Number", False),
        ("category", "Category", False),
        ("tags", "Tags", False),
        ("account", "Account", False),
        ("status", "Status", False),
        ("cleared", "Cleared", False),
        ("reconciled", "Reconciled", False),
        ("remind", "Remind", False),
        ("flagged", "Flagged", False),
        ("voided", "Voided", False),
    )

    def __init__(
        self,
        store: DataStore,
        accounts: list[Account],
        path: str | Path,
        default_account_id: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.accounts = accounts
        self.path = Path(path)
        self.plan: CsvPlan = read_csv_plan(path)
        self._saved_profile = self.store.import_profile(self.plan.headers)
        if self._saved_profile is not None:
            self.plan.mapping = dict(self._saved_profile)
        self._mapping_dirty = False
        self._valid_count = 0
        self._skipped_count = 0
        self._duplicate_count = 0
        self._duplicate_rows: set[int] = set()
        self._valid_rows: set[int] = set()
        self._updating_preview = False
        self.field_combos: dict[str, QComboBox] = {}

        self.setWindowTitle("Import transactions")
        self.setModal(True)
        self.setMinimumSize(900, 680)
        self.resize(940, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(9)

        heading = QLabel("Import transactions")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        file_label = QLabel(self.path.name)
        file_label.setFont(font(14, 600))
        file_label.setToolTip(str(self.path))
        root.addWidget(file_label)

        mapping_title = QHBoxLayout()
        title = QLabel("Header mapping")
        title.setFont(font(12, 600))
        mapping_title.addWidget(title)
        mapping_title.addStretch(1)
        required_hint = QLabel("* required")
        required_hint.setFont(font(11, 400))
        required_hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        mapping_title.addWidget(required_hint)
        root.addLayout(mapping_title)

        self.mapping_status = QLabel()
        self.mapping_status.setFont(font(11, 400))
        self.mapping_status.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(self.mapping_status)

        mapping = QGridLayout()
        mapping.setContentsMargins(0, 0, 0, 2)
        mapping.setHorizontalSpacing(14)
        mapping.setVerticalSpacing(6)
        for index, (field, label, required) in enumerate(self.FIELDS):
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(6)
            label_widget = QLabel(f"{label} *" if required else label)
            label_widget.setFont(font(11, 400))
            label_widget.setStyleSheet(
                f"color:{C.TEXT_SOFT if required else C.MUTED};"
            )
            label_widget.setFixedWidth(72)
            label_widget.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            combo = QComboBox()
            combo.setMinimumWidth(120)
            combo.addItem("(not mapped)", "")
            for header in self.plan.headers:
                combo.addItem(header, header)
            selected = self.plan.mapping.get(field, "")
            selected_index = combo.findData(selected) if selected else 0
            combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
            combo.currentIndexChanged.connect(self._mapping_changed)
            cell_layout.addWidget(label_widget)
            cell_layout.addWidget(combo, 1)
            self.field_combos[field] = combo
            mapping.addWidget(cell, index // 3, index % 3)
        root.addLayout(mapping)

        options = QHBoxLayout()
        options.setSpacing(8)
        self.account_label = self._label("Import into account")
        options.addWidget(self.account_label)
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(220)
        for account in accounts:
            self.account_combo.addItem(account.name, account.id)
        if default_account_id is not None:
            index = self.account_combo.findData(default_account_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.account_combo.currentIndexChanged.connect(self._refresh_preview)
        options.addWidget(self.account_combo)
        options.addSpacing(12)
        self.memo_payee = QCheckBox("Use Memo as payee when Beneficiario/Payee is empty")
        self.memo_payee.setChecked(True)
        self.memo_payee.toggled.connect(self._refresh_preview)
        options.addWidget(self.memo_payee)
        options.addSpacing(12)
        duplicate_hint = QLabel("Duplicates start unchecked")
        duplicate_hint.setFont(font(11, 400))
        duplicate_hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        duplicate_hint.setToolTip(
            "Rows that match an existing transaction are unchecked. Tick them "
            "to import them anyway."
        )
        options.addWidget(duplicate_hint)
        options.addStretch(1)
        root.addLayout(options)

        self.account_help = QLabel()
        self.account_help.setWordWrap(True)
        self.account_help.setFont(font(11, 400))
        self.account_help.setStyleSheet(f"color:{C.MUTED_DARK};")
        root.addWidget(self.account_help)

        self.preview = QTableWidget(0, 7)
        self.preview.setHorizontalHeaderLabels(
            ["Import", "Date", "Payee", "Memo", "Amount", "Category", "Status"]
        )
        self.preview.horizontalHeaderItem(0).setToolTip(
            "Tick the rows you want to import. Duplicates start unchecked."
        )
        self.preview.verticalHeader().setVisible(False)
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.preview.setAlternatingRowColors(True)
        self.preview.setShowGrid(False)
        self.preview.setWordWrap(False)
        self.preview.verticalHeader().setDefaultSectionSize(27)
        self.preview.itemChanged.connect(self._selection_changed)
        header = self.preview.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 56)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 100)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(2, 230)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 120)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(5, 140)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(6, 90)
        self.preview.setStyleSheet(
            f"QTableWidget {{ background:{C.PANEL}; alternate-background-color:{C.ALT_ROW};"
            f" border:none; }}"
        )
        root.addWidget(self.preview, 1)

        self.status_label = QLabel()
        self.status_label.setFont(font(12, 400))
        root.addWidget(self.status_label)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        self.import_button = buttons.addButton(
            "Import transactions", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.import_button.setProperty("role", "primary")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._update_account_help()
        self._update_mapping_status()
        self._refresh_preview()

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(font(12, 400))
        label.setStyleSheet(f"color:{C.MUTED};")
        return label

    def current_mapping(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for field, combo in self.field_combos.items():
            header = combo.currentData()
            if header:
                mapping[field] = header
        return mapping

    def _mapping_changed(self, *_args) -> None:
        self.plan.mapping = self.current_mapping()
        self._mapping_dirty = True
        self._update_account_help()
        self._update_mapping_status()
        self._refresh_preview()

    def _update_mapping_status(self) -> None:
        if self._mapping_dirty:
            self.mapping_status.setText(
                "Custom mapping — it will be saved for these columns when you import."
            )
        elif self._saved_profile is not None:
            self.mapping_status.setText(
                "Saved mapping loaded for these columns. Change any dropdown to update it."
            )
        else:
            self.mapping_status.setText(
                "Auto-detected mapping. It will be saved for these columns when you import."
            )

    def _update_account_help(self) -> None:
        if self.plan.has("account"):
            self.account_label.setText("Fallback account")
            self.account_help.setText(
                "The file contains account names; those accounts are used per row, "
                "with the selected account as a fallback."
            )
        else:
            self.account_label.setText("Import into account")
            self.account_help.setText(
                "This file has no Account/Cuenta column, so every row will be "
                "imported into the selected account."
            )

    def _row_account_id(self, row: dict[str, str]) -> int | None:
        """Mirror the account selection the importer will use for this row."""
        file_account = self.plan.value(row, "account").strip()
        if file_account:
            for account in self.accounts:
                if account.name.strip() == file_account:
                    return account.id
            return None
        return self.account_combo.currentData()

    def _preview_row(self, row: dict[str, str]) -> tuple[str, str, str, float, str] | None:
        parsed_date = parse_date(self.plan.value(row, "date"))
        amount = parse_amount(self.plan.value(row, "amount"))
        if parsed_date is None or amount is None:
            return None
        payee = self.plan.value(row, "payee")
        memo = self.plan.value(row, "memo")
        if self.memo_payee.isChecked() and not payee and memo:
            payee = memo
        category = self.plan.value(row, "category") or "Uncategorized"
        return parsed_date.isoformat(), payee, memo, amount, category

    def _refresh_preview(self, *_args) -> None:
        existing = self.store.import_fingerprints([account.id for account in self.accounts])
        preview_rows: list[tuple[int, str, str, str, float, str, bool]] = []
        duplicate_rows: set[int] = set()
        skipped = 0
        for index, row in enumerate(self.plan.rows):
            parsed = self._preview_row(row)
            if parsed is None:
                skipped += 1
                continue
            date_text, payee, memo, amount, category = parsed
            account_id = self._row_account_id(row)
            is_duplicate = False
            if account_id is not None:
                key = import_fingerprint(account_id, date_text, amount, memo, payee)
                is_duplicate = key in existing
            if is_duplicate:
                duplicate_rows.add(index)
            preview_rows.append(
                (index, date_text, payee, memo, amount, category, is_duplicate)
            )

        self._valid_count = len(preview_rows)
        self._skipped_count = skipped
        self._duplicate_count = len(duplicate_rows)
        self._duplicate_rows = duplicate_rows
        self._valid_rows = {row[0] for row in preview_rows}

        tint = QColor(C.ORANGE)
        tint.setAlpha(32)
        duplicate_background = QBrush(tint)
        duplicate_foreground = QBrush(QColor(C.ORANGE))

        self._updating_preview = True
        try:
            self.preview.setRowCount(0)
            for (
                plan_index,
                date_text,
                payee,
                memo,
                amount,
                category,
                is_duplicate,
            ) in preview_rows:
                row_index = self.preview.rowCount()
                self.preview.insertRow(row_index)
                check = QTableWidgetItem()
                check.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                check.setCheckState(
                    Qt.CheckState.Unchecked
                    if is_duplicate
                    else Qt.CheckState.Checked
                )
                check.setData(Qt.ItemDataRole.UserRole, plan_index)
                check.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                check.setToolTip(
                    "Duplicate — tick to import it anyway."
                    if is_duplicate
                    else "Tick to import this row."
                )
                self.preview.setItem(row_index, 0, check)

                status = "Duplicate" if is_duplicate else ""
                values = (format_date(date_text), payee, memo, money(amount), category, status)
                for column, value in enumerate(values, start=1):
                    item = QTableWidgetItem(value)
                    if column == 4:
                        item.setTextAlignment(
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                        )
                    if is_duplicate:
                        item.setBackground(duplicate_background)
                        if column == 6:
                            item.setForeground(duplicate_foreground)
                            item.setToolTip(
                                "Same memo, date and amount as an existing "
                                "transaction in this account."
                            )
                    self.preview.setItem(row_index, column, item)
                if is_duplicate:
                    check.setBackground(duplicate_background)
        finally:
            self._updating_preview = False

        self._update_selection_summary()

    def _checked_rows(self) -> set[int]:
        checked: set[int] = set()
        for row in range(self.preview.rowCount()):
            item = self.preview.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                checked.add(int(item.data(Qt.ItemDataRole.UserRole)))
        return checked

    def _selection_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_preview or item.column() != 0:
            return
        self._update_selection_summary()

    def _update_selection_summary(self) -> None:
        checked = self._checked_rows()
        selected = len(checked)
        unchecked_duplicates = len(self._duplicate_rows - checked)
        has_required = not self.plan.missing_required
        self.import_button.setEnabled(
            has_required and selected > 0 and bool(self.accounts)
        )
        if not self.accounts:
            self.status_label.setText("Create an account before importing.")
            self.status_label.setStyleSheet(f"color:{C.ORANGE};")
            return
        if self.plan.missing_required:
            self.status_label.setText("Map both Date and Amount to continue.")
            self.status_label.setStyleSheet(f"color:{C.ORANGE};")
            return
        if selected == 0:
            self.status_label.setText(
                "No rows selected — tick the rows you want to import."
            )
            self.status_label.setStyleSheet(f"color:{C.ORANGE};")
            return
        suffix = (
            f" · {self._skipped_count} unreadable row(s)"
            if self._skipped_count
            else ""
        )
        if unchecked_duplicates:
            text = (
                f"{selected} of {self._valid_count} row(s) selected · "
                f"{unchecked_duplicates} duplicate(s) not selected{suffix}"
            )
            self.status_label.setStyleSheet(f"color:{C.ORANGE};")
        elif self._duplicate_count:
            text = (
                f"{selected} of {self._valid_count} row(s) selected · "
                f"{self._duplicate_count} duplicate(s) included{suffix}"
            )
            self.status_label.setStyleSheet(f"color:{C.ORANGE};")
        elif selected == self._valid_count:
            text = f"{selected} transactions ready to import{suffix}"
            self.status_label.setStyleSheet(
                f"color:{C.ORANGE if self._skipped_count else C.MUTED};"
            )
        else:
            text = f"{selected} of {self._valid_count} row(s) selected{suffix}"
            self.status_label.setStyleSheet(
                f"color:{C.ORANGE if self._skipped_count else C.MUTED};"
            )
        self.status_label.setText(text)

    def skip_row_indexes(self) -> set[int]:
        return self._valid_rows - self._checked_rows()

    def accept(self) -> None:
        if not self.import_button.isEnabled():
            return
        self.store.remember_import_profile(self.plan.headers, self.current_mapping())
        super().accept()

    def account_id(self) -> int | None:
        return self.account_combo.currentData()

    def memo_as_payee(self) -> bool:
        return self.memo_payee.isChecked()
