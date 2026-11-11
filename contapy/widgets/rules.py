"""Automatic transaction assignment rules.

A rule has a condition (search text in the memo and/or payee, optionally a
signed-amount filter) and a set of assignments. Each assignment can overwrite
an existing value or only fill a field that is still empty.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..db import DataStore
from ..models import Rule, ordered_categories
from ..theme import C, font
from .dialogs import SearchCombo


def _section(title: str, subtitle: str, parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
    """Rounded outline panel with a heading, matching the other dialogs."""
    frame = QFrame(parent)
    frame.setObjectName("ruleSection")
    frame.setStyleSheet(
        f"QFrame#ruleSection {{ background:{C.PANEL_RAISED};"
        f" border:1px solid {C.BORDER_SOFT}; border-radius:5px; }}"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(5)
    heading = QLabel(title)
    heading.setFont(font(14, 600))
    heading.setStyleSheet(f"color:{C.TITLE};")
    layout.addWidget(heading)
    caption = QLabel(subtitle)
    caption.setWordWrap(True)
    caption.setFont(font(12, 400))
    caption.setStyleSheet(f"color:{C.MUTED};")
    layout.addWidget(caption)
    return frame, layout


def _label(text: str) -> QLabel:
    label = QLabel(f"{text}:")
    label.setFixedWidth(82)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setFont(font(13, 400))
    label.setStyleSheet(f"color:{C.MUTED};")
    return label


def _overwrite_check(tooltip: str) -> QCheckBox:
    check = QCheckBox("Overwrite")
    check.setToolTip(tooltip)
    check.setFont(font(12, 400))
    return check


class RuleDialog(QDialog):
    """Create or edit one assignment rule."""

    def __init__(
        self,
        store: DataStore,
        rule: Rule | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.rule_model = rule
        self._rule: Rule | None = None
        self.setWindowTitle("Edit Rule" if rule else "New Rule")
        self.setModal(True)
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Edit rule" if rule else "New assignment rule")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        intro = QLabel(
            "When a new transaction matches the condition, the assignments are "
            "applied automatically. Leave an assignment blank to skip it."
        )
        intro.setWordWrap(True)
        intro.setFont(font(13, 400))
        intro.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(intro)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(_label("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Optional name, e.g. Coffee shops")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        condition, condition_layout = _section(
            "Condition",
            "Choose where to search, how to compare, and optionally limit by amount.",
            self,
        )
        self._build_condition(condition_layout)
        root.addWidget(condition)

        assignments, assignments_layout = _section(
            "Assignments",
            "Overwrite forces the value; otherwise a field is only filled when empty.",
            self,
        )
        self._build_assignments(assignments_layout)
        root.addWidget(assignments)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        for button in (cancel, save):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        save.setProperty("role", "primary")
        save.setAutoDefault(True)
        save.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save)
        root.addWidget(buttons)

        if rule is not None:
            self._populate(rule)
        else:
            self.memo_check.setChecked(True)
            self.amount_and_check.setChecked(True)

    # ------------------------------------------------------------- condition
    def _build_condition(self, layout: QVBoxLayout) -> None:
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(_label("Search"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('Text to look for, e.g. "aki"')
        search_row.addWidget(self.search_edit, 1)
        layout.addLayout(search_row)

        in_row = QHBoxLayout()
        in_row.setSpacing(12)
        in_row.addWidget(_label("In"))
        self.memo_check = QCheckBox("Memo")
        self.payee_check = QCheckBox("Payee")
        for check in (self.memo_check, self.payee_check):
            check.setFont(font(13, 400))
            in_row.addWidget(check)
        in_row.addStretch(1)
        layout.addLayout(in_row)

        option_row = QHBoxLayout()
        option_row.setSpacing(12)
        option_row.addWidget(_label("Options"))
        self.case_check = QCheckBox("Case sensitive")
        self.regex_check = QCheckBox("Regular expression")
        for check in (self.case_check, self.regex_check):
            check.setFont(font(13, 400))
            option_row.addWidget(check)
        option_row.addStretch(1)
        layout.addLayout(option_row)

        amount_row = QHBoxLayout()
        amount_row.setSpacing(8)
        amount_row.addWidget(_label("Amount"))
        self.amount_check = QCheckBox("Filter by amount")
        self.amount_check.setFont(font(13, 400))
        amount_row.addWidget(self.amount_check)
        self.amount_and_check = QCheckBox("AND")
        self.amount_and_check.setFont(font(13, 400))
        self.amount_and_check.setToolTip(
            "Require both the text and amount conditions. When unchecked, "
            "matching either one is enough."
        )
        amount_row.addWidget(self.amount_and_check)
        self.amount_op_combo = QComboBox()
        self.amount_op_combo.addItem("= exactly", "=")
        self.amount_op_combo.addItem("- at most", "-")
        self.amount_op_combo.addItem("+ at least", "+")
        self.amount_op_combo.setFixedWidth(112)
        amount_row.addWidget(self.amount_op_combo)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setDecimals(2)
        self.amount_spin.setRange(-999_999_999.0, 999_999_999.0)
        self.amount_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.amount_spin.setFixedWidth(150)
        amount_row.addWidget(self.amount_spin)
        amount_row.addStretch(1)
        layout.addLayout(amount_row)

        hint = QLabel(
            "Expenses are negative and income is positive. “At most -100” "
            "matches expenses of 100 or more."
        )
        hint.setWordWrap(True)
        hint.setFont(font(11, 400))
        hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        layout.addWidget(hint)

        for widget in (
            self.amount_op_combo,
            self.amount_spin,
            self.amount_and_check,
        ):
            widget.setEnabled(False)
        self.amount_check.toggled.connect(self._amount_toggled)
        self.search_edit.textChanged.connect(self._search_changed)

    def _amount_toggled(self, checked: bool) -> None:
        for widget in (
            self.amount_op_combo,
            self.amount_spin,
            self.amount_and_check,
        ):
            widget.setEnabled(checked)

    def _search_changed(self, text: str) -> None:
        has_text = bool(text.strip())
        self.memo_check.setEnabled(has_text)
        self.payee_check.setEnabled(has_text)
        self.case_check.setEnabled(has_text)
        self.regex_check.setEnabled(has_text)

    # ----------------------------------------------------------- assignments
    def _build_assignments(self, layout: QVBoxLayout) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)

        self.payee_combo = SearchCombo("Leave blank to keep the payee", auto_match=False)
        self.payee_combo.set_choices(
            [(payee, payee) for payee in self.store.payees()], select_first=False
        )
        self.payee_overwrite = _overwrite_check(
            "Replace the existing payee instead of only filling an empty one."
        )
        self._assignment_row(grid, 0, "Payee", self.payee_combo, self.payee_overwrite)

        self.category_combo = SearchCombo(
            "Leave blank, or type a category / Parent : Child"
        )
        self.category_combo.set_choices(
            [
                (category.full_name, category.id)
                for category in ordered_categories(self.store.categories())
            ],
            select_first=False,
        )
        self.category_overwrite = _overwrite_check(
            "Replace the existing category instead of only filling an empty one."
        )
        self._assignment_row(
            grid, 1, "Category", self.category_combo, self.category_overwrite
        )

        self.payment_combo = SearchCombo("Leave blank to keep the payment type", auto_match=False)
        self.payment_combo.set_choices(
            [(payment, payment) for payment in self.store.payments()],
            select_first=False,
        )
        self.payment_overwrite = _overwrite_check(
            "Replace the existing payment type instead of only filling it."
        )
        self._assignment_row(
            grid, 2, "Payment", self.payment_combo, self.payment_overwrite
        )

        self.tags_combo = SearchCombo("Space-separated tags", auto_match=False)
        self.tags_combo.set_choices(
            [(tag, tag) for tag in self.store.tags()], select_first=False
        )
        self.tags_overwrite = _overwrite_check(
            "Replace the existing tags instead of only filling them."
        )
        self._assignment_row(grid, 3, "Tags", self.tags_combo, self.tags_overwrite)

        self.memo_edit = QLineEdit()
        self.memo_edit.setPlaceholderText("Default note added to the memo")
        self.memo_overwrite = _overwrite_check(
            "Replace the existing memo instead of only filling an empty one."
        )
        self._assignment_row(grid, 4, "Notes", self.memo_edit, self.memo_overwrite)

        layout.addLayout(grid)

    def _assignment_row(
        self,
        grid: QGridLayout,
        row: int,
        text: str,
        widget: QWidget,
        overwrite: QCheckBox,
    ) -> None:
        grid.addWidget(_label(text), row, 0)
        grid.addWidget(widget, row, 1)
        grid.addWidget(overwrite, row, 2)

    # --------------------------------------------------------------- values
    def _populate(self, rule: Rule) -> None:
        self.name_edit.setText(rule.name)
        self.search_edit.setText(rule.search)
        self.memo_check.setChecked(rule.match_memo)
        self.payee_check.setChecked(rule.match_payee)
        self.case_check.setChecked(rule.case_sensitive)
        self.regex_check.setChecked(rule.regex)
        self.amount_check.setChecked(rule.amount_enabled)
        self.amount_and_check.setChecked(rule.amount_and)
        index = self.amount_op_combo.findData(rule.amount_op)
        self.amount_op_combo.setCurrentIndex(index if index >= 0 else 0)
        self.amount_spin.setValue(rule.amount)

        self.payee_combo.setEditText(rule.assign_payee)
        self.payee_overwrite.setChecked(rule.payee_overwrite)
        if rule.category_id is not None:
            index = self.category_combo.findData(rule.category_id)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
                self.category_combo.setEditText(self.category_combo.itemText(index))
        self.category_overwrite.setChecked(rule.category_overwrite)
        self.payment_combo.setEditText(rule.assign_payment)
        self.payment_overwrite.setChecked(rule.payment_overwrite)
        self.tags_combo.setEditText(rule.assign_tags)
        self.tags_overwrite.setChecked(rule.tags_overwrite)
        self.memo_edit.setText(rule.assign_memo)
        self.memo_overwrite.setChecked(rule.memo_overwrite)
        self._search_changed(rule.search)
        self._amount_toggled(rule.amount_enabled)

    def _resolved_category(self) -> int | None:
        category_id = self.category_combo.resolved_data()
        typed = self.category_combo.resolved_text()
        if category_id is not None or not typed:
            return category_id
        if typed.casefold() == "uncategorized":
            return None
        try:
            return self.store.ensure_category(typed, "expense")
        except ValueError:
            return None

    def values(self) -> Rule:
        """Build the rule from the current form values."""
        rule = Rule(
            id=self.rule_model.id if self.rule_model is not None else 0,
            name=self.name_edit.text().strip(),
            enabled=self.rule_model.enabled if self.rule_model is not None else True,
            sort_order=self.rule_model.sort_order if self.rule_model is not None else 0,
            search=self.search_edit.text(),
            match_memo=self.memo_check.isChecked(),
            match_payee=self.payee_check.isChecked(),
            case_sensitive=self.case_check.isChecked(),
            regex=self.regex_check.isChecked(),
            amount_enabled=self.amount_check.isChecked(),
            amount_and=self.amount_and_check.isChecked(),
            amount_op=self.amount_op_combo.currentData(),
            amount=self.amount_spin.value(),
            assign_payee=self.payee_combo.resolved_text(),
            payee_overwrite=self.payee_overwrite.isChecked(),
            category_id=self._resolved_category(),
            category_overwrite=self.category_overwrite.isChecked(),
            assign_payment=self.payment_combo.resolved_text(),
            payment_overwrite=self.payment_overwrite.isChecked(),
            assign_tags=self.tags_combo.resolved_text(),
            tags_overwrite=self.tags_overwrite.isChecked(),
            assign_memo=self.memo_edit.text().strip(),
            memo_overwrite=self.memo_overwrite.isChecked(),
        )
        if not rule.name:
            rule.name = rule.search.strip() or "Amount rule"
        return rule

    def _save(self) -> None:
        try:
            rule = self.values()
            rule.validate()
        except ValueError as error:
            QMessageBox.warning(self, "Incomplete rule", str(error))
            return
        self._rule = rule
        super().accept()

    def rule(self) -> Rule | None:
        return self._rule


class RulesDialog(QDialog):
    """List, create, edit and enable automatic assignment rules."""

    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.changed = False
        self.setWindowTitle("Rules")
        self.setModal(True)
        self.setMinimumSize(560, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Rules")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        subtitle = QLabel(
            "Rules run when a transaction is added or imported. Untick a rule to "
            "disable it without deleting it. Rules are applied from top to "
            "bottom, so a later overwrite rule wins."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(font(13, 400))
        subtitle.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(subtitle)

        self.listing = QListWidget()
        self.listing.setFont(font(13, 400))
        self.listing.setSpacing(2)
        self.listing.itemDoubleClicked.connect(lambda _item: self.edit_rule())
        self.listing.itemChanged.connect(self._item_toggled)
        root.addWidget(self.listing, 1)

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
        self.new_button.clicked.connect(self.new_rule)
        self.edit_button.clicked.connect(self.edit_rule)
        self.delete_button.clicked.connect(self.delete_rule)
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._reload_list()

    def _reload_list(self, select_id: int | None = None) -> None:
        self.listing.blockSignals(True)
        self.listing.clear()
        for rule in self.store.rules():
            item = QListWidgetItem(self._summary(rule))
            item.setData(Qt.ItemDataRole.UserRole, rule.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked
            )
            item.setForeground(QColor(C.TEXT if rule.enabled else C.MUTED_DARK))
            self.listing.addItem(item)
            if select_id is not None and rule.id == select_id:
                self.listing.setCurrentItem(item)
        self.listing.blockSignals(False)
        self._update_buttons()

    def _summary(self, rule: Rule) -> str:
        fields = []
        if rule.match_memo:
            fields.append("Memo")
        if rule.match_payee:
            fields.append("Payee")
        parts: list[str] = []
        if rule.search:
            parts.append(f"“{rule.search}” in {' + '.join(fields) or '—'}")
        if rule.amount_enabled:
            symbol = {"-": "≤", "+": "≥"}.get(rule.amount_op, "=")
            parts.append(f"Amount {symbol} {rule.amount:,.2f}")
        condition = " · ".join(parts) if parts else "No condition"
        targets = []
        if rule.assign_payee:
            targets.append(f"Payee → {rule.assign_payee}")
        if rule.category_id is not None:
            category = self.store.category(rule.category_id)
            if category is not None:
                targets.append(f"Category → {category.full_name}")
        if rule.assign_payment:
            targets.append(f"Payment → {rule.assign_payment}")
        if rule.assign_tags:
            targets.append(f"Tags → {rule.assign_tags}")
        if rule.assign_memo:
            targets.append(f"Notes → {rule.assign_memo}")
        assigned = " · ".join(targets) if targets else "No assignments"
        name = f"{rule.name} — " if rule.name else ""
        return f"{name}{condition}\n{assigned}"

    def _current_id(self) -> int | None:
        item = self.listing.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _update_buttons(self) -> None:
        has_selection = self.listing.currentItem() is not None
        self.edit_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)

    def _item_toggled(self, item: QListWidgetItem) -> None:
        rule_id = int(item.data(Qt.ItemDataRole.UserRole))
        enabled = item.checkState() == Qt.CheckState.Checked
        self.store.set_rule_enabled(rule_id, enabled)
        item.setForeground(QColor(C.TEXT if enabled else C.MUTED_DARK))
        self.changed = True

    def new_rule(self) -> None:
        dialog = RuleDialog(self.store, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.rule() is not None:
            rule_id = self.store.add_rule(dialog.rule())
            self.changed = True
            self._reload_list(rule_id)

    def edit_rule(self) -> None:
        rule_id = self._current_id()
        if rule_id is None:
            return
        rule = self.store.rule(rule_id)
        if rule is None:
            return
        dialog = RuleDialog(self.store, rule, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.rule() is not None:
            self.store.update_rule(dialog.rule())
            self.changed = True
            self._reload_list(rule_id)

    def delete_rule(self) -> None:
        rule_id = self._current_id()
        if rule_id is None:
            return
        rule = self.store.rule(rule_id)
        if rule is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete rule?",
            f"Delete “{rule.name}”?\n\nThis only removes the rule; transactions "
            "it already assigned keep their values.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_rule(rule_id)
        self.changed = True
        self._reload_list()
