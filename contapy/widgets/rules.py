"""Automatic transaction assignment rules.

A rule has a condition (search text in the memo and/or payee, optionally a
signed-amount filter) and a set of assignments. Each assignment can overwrite
an existing value or only fill a field that is still empty.
"""

from __future__ import annotations

import re
from dataclasses import replace

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..db import DataStore
from ..models import Rule, RuleCondition, Template, ordered_categories
from ..theme import C, font, radius, terminal_theme
from ..xhb_rules import import_xhb_rules
from .dialogs import SearchCombo


def _section(title: str, subtitle: str, parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
    """Rounded outline panel with a heading, matching the other dialogs."""
    frame = QFrame(parent)
    frame.setObjectName("ruleSection")
    frame.setStyleSheet(
        f"QFrame#ruleSection {{ background:{C.PANEL_RAISED};"
        f" border:1px solid {C.BORDER_SOFT}; border-radius:{radius(5)}; }}"
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


TEMPLATE_STATUS_CHOICES: list[tuple[str, str]] = [
    ("Leave unchanged", ""),
    ("No status", "none"),
    ("Cleared", "cleared"),
    ("Reconciled", "reconciled"),
    ("Remind", "remind"),
    ("Flagged", "flagged"),
    ("Voided", "voided"),
]
TEMPLATE_STATUS_LABELS = {
    value: label for label, value in TEMPLATE_STATUS_CHOICES if value
}


class _AssignmentFieldsMixin:
    """Shared Payee/Category/Payment/Tags/Notes assignment form."""

    store: DataStore

    # ----------------------------------------------------------- assignments
    def _build_assignments(
        self,
        layout: QVBoxLayout,
        *,
        memo_modes: bool = False,
        show_status: bool = False,
    ) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(5)

        self.payee_combo = SearchCombo(
            "Leave blank to keep the payee", auto_match=False
        )
        self.payee_combo.set_choices(
            [(payee, payee) for payee in self.store.payees()], select_first=False
        )
        self.payee_overwrite = _overwrite_check(
            "Replace the existing payee instead of only filling an empty one."
        )
        self._assignment_row(grid, 0, "Payee", self.payee_combo, self.payee_overwrite)

        self.category_combo = SearchCombo(
            "Leave blank, or type a category / Parent : Child",
            keep_text_unselected=True,
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

        self.payment_combo = SearchCombo(
            "Leave blank to keep the payment type", auto_match=False
        )
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

        notes_row = 4
        if show_status:
            self.status_combo = QComboBox()
            for label, value in TEMPLATE_STATUS_CHOICES:
                self.status_combo.addItem(label, value)
            self.status_combo.setFont(font(13, 400))
            self.status_combo.setToolTip(
                "Replace the transaction's status, or leave it unchanged."
            )
            grid.addWidget(_label("Status"), notes_row, 0)
            grid.addWidget(self.status_combo, notes_row, 1, 1, 2)
            notes_row += 1

        self.memo_edit = QLineEdit()
        if memo_modes:
            self.memo_edit.setPlaceholderText(
                "Note to fill, append or replace"
            )
            self.memo_mode = QComboBox()
            self.memo_mode.addItem("Fill empty", "empty")
            self.memo_mode.addItem("Append", "append")
            self.memo_mode.addItem("Overwrite", "overwrite")
            self.memo_mode.setFixedWidth(128)
            self._assignment_row(
                grid, notes_row, "Notes", self.memo_edit, self.memo_mode
            )
        else:
            self.memo_edit.setPlaceholderText("Default note added to the memo")
            self.memo_overwrite = _overwrite_check(
                "Replace the existing memo instead of only filling an empty one."
            )
            self._assignment_row(
                grid, notes_row, "Notes", self.memo_edit, self.memo_overwrite
            )

        layout.addLayout(grid)

    def _assignment_row(
        self,
        grid: QGridLayout,
        row: int,
        text: str,
        widget: QWidget,
        overwrite: QWidget,
    ) -> None:
        grid.addWidget(_label(text), row, 0)
        grid.addWidget(widget, row, 1)
        grid.addWidget(overwrite, row, 2)

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


class _ConditionEditor(QFrame):
    """One editable search/amount condition inside :class:`RuleDialog`."""

    def __init__(
        self,
        condition: RuleCondition | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("ruleCondition")
        self.setStyleSheet(
            f"QFrame#ruleCondition {{ background:{C.PANEL};"
            f" border:1px solid {C.BORDER_SOFT}; border-radius:{radius(4)}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 9)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title = QLabel("Condition")
        self.title.setFont(font(13, 600))
        self.title.setStyleSheet(f"color:{C.TITLE};")
        header.addWidget(self.title)
        header.addStretch(1)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setAutoDefault(False)
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.setFont(font(12, 400))
        header.addWidget(self.remove_button)
        layout.addLayout(header)

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
            "Require both the text and amount parts of this condition. When "
            "unchecked, matching either one is enough."
        )
        amount_row.addWidget(self.amount_and_check)
        self.amount_op_combo = QComboBox()
        self.amount_op_combo.addItem("= exactly", "=")
        self.amount_op_combo.addItem("- at most", "-")
        self.amount_op_combo.addItem("+ at least", "+")
        self.amount_op_combo.setFixedWidth(
            132 if terminal_theme() else 112
        )
        amount_row.addWidget(self.amount_op_combo)
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setDecimals(2)
        self.amount_spin.setRange(-999_999_999.0, 999_999_999.0)
        self.amount_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.amount_spin.setFixedWidth(150)
        amount_row.addWidget(self.amount_spin)
        amount_row.addStretch(1)
        layout.addLayout(amount_row)

        for widget in (
            self.amount_op_combo,
            self.amount_spin,
            self.amount_and_check,
        ):
            widget.setEnabled(False)
        self.amount_check.toggled.connect(self._amount_toggled)
        self.search_edit.textChanged.connect(self._search_changed)

        if condition is not None:
            self.set_condition(condition)
        else:
            self.memo_check.setChecked(True)
            self.amount_and_check.setChecked(True)

    def set_index(self, index: int) -> None:
        self.title.setText(f"Condition {index}")

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

    def set_condition(self, condition: RuleCondition) -> None:
        self.search_edit.setText(condition.search)
        self.memo_check.setChecked(condition.match_memo)
        self.payee_check.setChecked(condition.match_payee)
        self.case_check.setChecked(condition.case_sensitive)
        self.regex_check.setChecked(condition.regex)
        self.amount_check.setChecked(condition.amount_enabled)
        self.amount_and_check.setChecked(condition.amount_and)
        index = self.amount_op_combo.findData(condition.amount_op)
        self.amount_op_combo.setCurrentIndex(index if index >= 0 else 0)
        self.amount_spin.setValue(condition.amount)
        self._search_changed(condition.search)
        self._amount_toggled(condition.amount_enabled)

    def condition(self) -> RuleCondition:
        return RuleCondition(
            search=self.search_edit.text(),
            match_memo=self.memo_check.isChecked(),
            match_payee=self.payee_check.isChecked(),
            case_sensitive=self.case_check.isChecked(),
            regex=self.regex_check.isChecked(),
            amount_enabled=self.amount_check.isChecked(),
            amount_and=self.amount_and_check.isChecked(),
            amount_op=self.amount_op_combo.currentData(),
            amount=self.amount_spin.value(),
        )


class RuleDialog(_AssignmentFieldsMixin, QDialog):
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
        self.resize(760, 760)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 18, 20, 8)
        root.setSpacing(10)
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area, 1)

        heading = QLabel("Edit rule" if rule else "New assignment rule")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        intro = QLabel(
            "When a new transaction matches the conditions, the assignments are "
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

        conditions, conditions_layout = _section(
            "Conditions",
            "Match any or all of these conditions. Each one can search text, "
            "filter by amount, or both.",
            self,
        )
        self._build_conditions(conditions_layout)
        root.addWidget(conditions)

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

        button_bar = QWidget()
        button_layout = QHBoxLayout(button_bar)
        button_layout.setContentsMargins(20, 8, 20, 16)
        button_layout.addWidget(buttons)
        outer.addWidget(button_bar)

        if rule is not None:
            self._populate(rule)

    # ------------------------------------------------------------ conditions
    def _build_conditions(self, layout: QVBoxLayout) -> None:
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(_label("Match"))
        self.condition_mode_combo = QComboBox()
        self.condition_mode_combo.addItem("any condition (OR)", "any")
        self.condition_mode_combo.addItem("all conditions (AND)", "all")
        self.condition_mode_combo.setFixedWidth(
            220 if terminal_theme() else 180
        )
        mode_row.addWidget(self.condition_mode_combo)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        self.conditions_layout = QVBoxLayout()
        self.conditions_layout.setContentsMargins(0, 0, 0, 0)
        self.conditions_layout.setSpacing(6)
        self.conditions_layout.addStretch(1)
        layout.addLayout(self.conditions_layout)

        add_row = QHBoxLayout()
        self.add_condition_button = QPushButton("Add condition")
        self.add_condition_button.setAutoDefault(False)
        self.add_condition_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.add_condition_button.setFont(font(12, 400))
        self.add_condition_button.clicked.connect(
            lambda: self._add_condition()
        )
        add_row.addWidget(self.add_condition_button)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        hint = QLabel(
            "Expenses are negative and income is positive. “At most -100” "
            "matches expenses of 100 or more."
        )
        hint.setWordWrap(True)
        hint.setFont(font(11, 400))
        hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        layout.addWidget(hint)

        self.condition_editors: list[_ConditionEditor] = []
        self._add_condition()

    def _add_condition(
        self, condition: RuleCondition | None = None
    ) -> _ConditionEditor:
        editor = _ConditionEditor(condition, self)
        editor.remove_button.clicked.connect(
            lambda _checked=False, current=editor: self._remove_condition(
                current
            )
        )
        self.condition_editors.append(editor)
        self.conditions_layout.insertWidget(
            self.conditions_layout.count() - 1, editor
        )
        self._renumber_conditions()
        return editor

    def _remove_condition(self, editor: _ConditionEditor) -> None:
        if len(self.condition_editors) <= 1:
            return
        self.condition_editors.remove(editor)
        self.conditions_layout.removeWidget(editor)
        editor.hide()
        editor.setParent(None)
        editor.deleteLater()
        self._renumber_conditions()

    def _renumber_conditions(self) -> None:
        removable = len(self.condition_editors) > 1
        for index, editor in enumerate(self.condition_editors, 1):
            editor.set_index(index)
            editor.remove_button.setEnabled(removable)

    def _clear_conditions(self) -> None:
        for editor in self.condition_editors:
            self.conditions_layout.removeWidget(editor)
            editor.hide()
            editor.setParent(None)
            editor.deleteLater()
        self.condition_editors.clear()

    # --------------------------------------------------------------- values
    def _populate(self, rule: Rule) -> None:
        self.name_edit.setText(rule.name)
        self._clear_conditions()
        for condition in rule.effective_conditions():
            self._add_condition(condition)
        mode_index = self.condition_mode_combo.findData(rule.condition_mode)
        self.condition_mode_combo.setCurrentIndex(
            mode_index if mode_index >= 0 else 0
        )

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

    def values(self) -> Rule:
        """Build the rule from the current form values."""
        conditions = [
            editor.condition() for editor in self.condition_editors
        ]
        primary = conditions[0] if conditions else RuleCondition()
        mode = self.condition_mode_combo.currentData() or "any"
        rule = Rule(
            id=self.rule_model.id if self.rule_model is not None else 0,
            name=self.name_edit.text().strip(),
            enabled=self.rule_model.enabled if self.rule_model is not None else True,
            sort_order=self.rule_model.sort_order if self.rule_model is not None else 0,
            search=primary.search,
            match_memo=primary.match_memo,
            match_payee=primary.match_payee,
            case_sensitive=primary.case_sensitive,
            regex=primary.regex,
            amount_enabled=primary.amount_enabled,
            amount_and=primary.amount_and,
            amount_op=primary.amount_op,
            amount=primary.amount,
            conditions=conditions,
            condition_mode=mode,
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
            if len(conditions) == 1:
                rule.name = primary.search.strip() or "Amount rule"
            else:
                rule.name = f"{len(conditions)} conditions"
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


class TemplateDialog(_AssignmentFieldsMixin, QDialog):
    """Create or edit one saved template of assignment values."""

    def __init__(
        self,
        store: DataStore,
        template: Template | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.template_model = template
        self._template: Template | None = None
        self.setWindowTitle("Edit Template" if template else "New Template")
        self.setModal(True)
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Edit template" if template else "New template")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        intro = QLabel(
            "A template stores Payee, Category, Payment, Tags, Status and Notes "
            "values that can be applied to any selected ledger transactions. "
            "Unlike a rule, a template has no matching condition."
        )
        intro.setWordWrap(True)
        intro.setFont(font(13, 400))
        intro.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(intro)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(_label("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Template name, e.g. Coffee shop")
        name_row.addWidget(self.name_edit, 1)
        root.addLayout(name_row)

        assignments, assignments_layout = _section(
            "Assignments",
            "Overwrite forces the value; otherwise a field is only filled when empty.",
            self,
        )
        self._build_assignments(
            assignments_layout, memo_modes=True, show_status=True
        )
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

        if template is not None:
            self._populate(template)

    def _populate(self, template: Template) -> None:
        self.name_edit.setText(template.name)
        self.payee_combo.setEditText(template.payee)
        self.payee_overwrite.setChecked(template.payee_overwrite)
        if template.category_set:
            if template.category_id is not None:
                index = self.category_combo.findData(template.category_id)
                if index >= 0:
                    self.category_combo.setCurrentIndex(index)
                    self.category_combo.setEditText(
                        self.category_combo.itemText(index)
                    )
            else:
                self.category_combo.setEditText("Uncategorized")
        self.category_overwrite.setChecked(template.category_overwrite)
        self.payment_combo.setEditText(template.payment)
        self.payment_overwrite.setChecked(template.payment_overwrite)
        self.tags_combo.setEditText(template.tags)
        self.tags_overwrite.setChecked(template.tags_overwrite)
        index = self.status_combo.findData(template.status)
        self.status_combo.setCurrentIndex(index if index >= 0 else 0)
        self.memo_edit.setText(template.memo)
        index = self.memo_mode.findData(template.memo_mode)
        self.memo_mode.setCurrentIndex(index if index >= 0 else 0)

    def values(self) -> Template:
        """Build the template from the current form values."""
        category_text = self.category_combo.resolved_text()
        return Template(
            id=self.template_model.id if self.template_model is not None else 0,
            name=self.name_edit.text().strip(),
            sort_order=(
                self.template_model.sort_order
                if self.template_model is not None
                else 0
            ),
            payee=self.payee_combo.resolved_text(),
            payee_overwrite=self.payee_overwrite.isChecked(),
            category_id=self._resolved_category(),
            category_set=bool(category_text),
            category_overwrite=self.category_overwrite.isChecked(),
            payment=self.payment_combo.resolved_text(),
            payment_overwrite=self.payment_overwrite.isChecked(),
            tags=self.tags_combo.resolved_text(),
            tags_overwrite=self.tags_overwrite.isChecked(),
            memo=self.memo_edit.text().strip(),
            memo_mode=self.memo_mode.currentData(),
            status=self.status_combo.currentData(),
        )

    def _save(self) -> None:
        category_text = self.category_combo.resolved_text()
        category_id = self._resolved_category()
        if (
            category_text
            and category_id is None
            and category_text.casefold() != "uncategorized"
        ):
            QMessageBox.warning(
                self,
                "Invalid category",
                f"“{category_text}” is not a valid category. Choose an existing "
                "category or type Uncategorized.",
            )
            return
        template = self.values()
        if not template.name:
            QMessageBox.warning(
                self, "Incomplete template", "Give the template a name."
            )
            return
        if not template.has_values():
            QMessageBox.warning(
                self,
                "Incomplete template",
                "Fill in at least one of Payee, Category, Payment, Tags or Notes.",
            )
            return
        self._template = template
        super().accept()

    def template(self) -> Template | None:
        return self._template


class TemplatesDialog(QDialog):
    """Manage saved templates, optionally choosing one to apply."""

    def __init__(
        self,
        store: DataStore,
        parent: QWidget | None = None,
        *,
        count: int | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.count = count
        self.pick_mode = count is not None
        self.changed = False
        self._selected: Template | None = None
        if self.pick_mode:
            self.setWindowTitle(
                f"Apply Template to {count} transaction(s)"
            )
        else:
            self.setWindowTitle("Templates")
        self.setModal(True)
        self.setMinimumSize(560, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Apply template" if self.pick_mode else "Templates")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        if self.pick_mode:
            subtitle_text = (
                f"Choose a saved template to apply to the {count} selected "
                "transaction(s). Templates assign values directly; they have no "
                "matching conditions."
            )
        else:
            subtitle_text = (
                "Templates are reusable sets of Payee, Category, Payment, Tags "
                "and Notes values. Apply one from an account ledger."
            )
        subtitle = QLabel(subtitle_text)
        subtitle.setWordWrap(True)
        subtitle.setFont(font(13, 400))
        subtitle.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(subtitle)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search templates by name or assignment…"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFont(font(13, 400))
        self.search_edit.textChanged.connect(self._search_changed)
        self.search_edit.installEventFilter(self)
        root.addWidget(self.search_edit)
        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self._focus_search)

        self.listing = QListWidget()
        self.listing.setFont(font(13, 400))
        self.listing.setSpacing(2)
        self.listing.setWordWrap(True)
        self.listing.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.listing.setStyleSheet(
            f"QListWidget::item:selected {{ background:{C.ACCENT};"
            f" color:{C.ON_ACCENT}; }}"
            f"QListWidget::item:selected:!active {{ background:{C.ACCENT};"
            f" color:{C.ON_ACCENT}; }}"
        )
        self.listing.itemDoubleClicked.connect(
            lambda _item: self._item_activated()
        )
        self.listing.itemSelectionChanged.connect(self._update_buttons)
        for key in ("Return", "Enter"):
            shortcut = QShortcut(QKeySequence(key), self.listing)
            shortcut.activated.connect(self._item_activated)
        root.addWidget(self.listing, 1)

        self.empty_hint = QLabel("")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setFont(font(12, 400))
        self.empty_hint.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(self.empty_hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.new_button = QPushButton("New…")
        self.edit_button = QPushButton("Edit…")
        self.duplicate_button = QPushButton("Duplicate")
        self.delete_button = QPushButton("Delete")
        for button in (
            self.new_button,
            self.edit_button,
            self.duplicate_button,
            self.delete_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(13, 400))
        self.new_button.setProperty("role", "primary")
        self.new_button.clicked.connect(self.new_template)
        self.edit_button.clicked.connect(self.edit_template)
        self.duplicate_button.clicked.connect(self.duplicate_template)
        self.delete_button.clicked.connect(self.delete_template)
        duplicate_shortcut = QShortcut(QKeySequence("Ctrl+D"), self)
        duplicate_shortcut.activated.connect(self.duplicate_template)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.duplicate_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)

        self.apply_button: QPushButton | None = None
        if self.pick_mode:
            cancel = QPushButton("Cancel")
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.setFont(font(13, 400))
            cancel.setAutoDefault(False)
            cancel.clicked.connect(self.reject)
            self.apply_button = QPushButton(f"Apply to {count}")
            self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.apply_button.setFont(font(13, 400))
            self.apply_button.setProperty("role", "primary")
            self.apply_button.setAutoDefault(True)
            self.apply_button.setDefault(True)
            self.apply_button.clicked.connect(self._apply)
            buttons.addWidget(cancel)
            buttons.addWidget(self.apply_button)
        else:
            close = QPushButton("Close")
            close.setCursor(Qt.CursorShape.PointingHandCursor)
            close.setFont(font(13, 400))
            close.setAutoDefault(False)
            close.clicked.connect(self.accept)
            buttons.addWidget(close)
        root.addLayout(buttons)

        self._reload_list()

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def eventFilter(self, watched, event):  # noqa: N802
        if (
            watched is self.search_edit
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.key() == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if event.key() == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._item_activated()
                return True
        return super().eventFilter(watched, event)

    def _move_selection(self, step: int) -> None:
        count = self.listing.count()
        if count == 0:
            return
        current = self.listing.currentRow()
        if current < 0:
            row = 0 if step > 0 else count - 1
        else:
            row = max(0, min(count - 1, current + step))
        self.listing.setCurrentRow(row)
        self.listing.scrollToItem(self.listing.item(row))

    def _search_changed(self, _text: str) -> None:
        self._reload_list(select_id=self._current_id())

    def _reload_list(self, select_id: int | None = None) -> None:
        query = self.search_edit.text().strip().casefold()
        templates = self.store.templates()
        self.listing.clear()
        for template in templates:
            summary = self._summary(template)
            if query and query not in summary.casefold():
                continue
            item = QListWidgetItem(summary)
            item.setData(Qt.ItemDataRole.UserRole, template.id)
            self.listing.addItem(item)
            if select_id is not None and template.id == select_id:
                self.listing.setCurrentItem(item)
        if self.listing.count() and self.listing.currentRow() < 0:
            if query or select_id is not None:
                self.listing.setCurrentRow(0)
                self.listing.scrollToItem(self.listing.item(0))
        if not templates:
            self.empty_hint.setText(
                "No templates yet. Use New… to create one."
            )
        elif self.listing.count() == 0:
            self.empty_hint.setText("No templates match this search.")
        else:
            self.empty_hint.setText("")
        self._update_buttons()

    def _summary(self, template: Template) -> str:
        parts: list[str] = []
        if template.payee:
            parts.append(f"Payee → {template.payee}")
        if template.category_set:
            if template.category_id is None:
                parts.append("Category → Uncategorized")
            else:
                category = self.store.category(template.category_id)
                parts.append(
                    f"Category → {category.full_name}"
                    if category is not None
                    else "Category → Uncategorized"
                )
        if template.payment:
            parts.append(f"Payment → {template.payment}")
        if template.tags:
            parts.append(f"Tags → {template.tags}")
        if template.status:
            parts.append(
                f"Status → "
                f"{TEMPLATE_STATUS_LABELS.get(template.status, template.status)}"
            )
        if template.memo:
            mode = {"append": " (append)", "overwrite": " (overwrite)"}.get(
                template.memo_mode, ""
            )
            parts.append(f"Notes → {template.memo}{mode}")
        if not parts:
            return f"{template.name}\nNo assignments"
        lines = [template.name]
        for start in range(0, len(parts), 2):
            lines.append(" · ".join(parts[start : start + 2]))
        return "\n".join(lines)

    def _current_id(self) -> int | None:
        item = self.listing.currentItem()
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _update_buttons(self) -> None:
        has_selection = self.listing.currentItem() is not None
        self.edit_button.setEnabled(has_selection)
        self.duplicate_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        if self.apply_button is not None:
            self.apply_button.setEnabled(has_selection)

    def _item_activated(self) -> None:
        if self.pick_mode:
            self._apply()
        else:
            self.edit_template()

    def new_template(self) -> None:
        dialog = TemplateDialog(self.store, parent=self)
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.template() is not None
        ):
            template_id = self.store.add_template(dialog.template())
            self.changed = True
            self._reload_list(template_id)

    def edit_template(self) -> None:
        template_id = self._current_id()
        if template_id is None:
            return
        template = self.store.template(template_id)
        if template is None:
            return
        dialog = TemplateDialog(self.store, template, self)
        if (
            dialog.exec() == QDialog.DialogCode.Accepted
            and dialog.template() is not None
        ):
            self.store.update_template(dialog.template())
            self.changed = True
            self._reload_list(template_id)

    def _copy_name(self, name: str) -> str:
        stem = re.sub(
            r"\s*\(copy(?: \d+)?\)$", "", name, flags=re.IGNORECASE
        ).strip() or "Template"
        base = f"{stem} (copy)"
        existing = {
            template.name.casefold() for template in self.store.templates()
        }
        if base.casefold() not in existing:
            return base
        index = 2
        while f"{stem} (copy {index})".casefold() in existing:
            index += 1
        return f"{stem} (copy {index})"

    def duplicate_template(self) -> None:
        template_id = self._current_id()
        if template_id is None:
            return
        template = self.store.template(template_id)
        if template is None:
            return
        copy = replace(
            template,
            id=0,
            sort_order=0,
            name=self._copy_name(template.name),
        )
        new_id = self.store.add_template(copy)
        self.changed = True
        self._reload_list(new_id)

    def delete_template(self) -> None:
        template_id = self._current_id()
        if template_id is None:
            return
        template = self.store.template(template_id)
        if template is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete template?",
            f"Delete “{template.name}”?\n\nThis only removes the template; "
            "transactions it already changed keep their values.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_template(template_id)
        self.changed = True
        self._reload_list()

    def _apply(self) -> None:
        template_id = self._current_id()
        if template_id is None:
            return
        template = self.store.template(template_id)
        if template is None:
            return
        self._selected = template
        self.accept()

    def template_values(self) -> Template | None:
        """The template chosen for application, after the dialog is accepted."""
        return self._selected


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
            "bottom, so a later overwrite rule wins.\n\n"
            "Import from HomeBank… reads the automatic assignments stored in a "
            "HomeBank .xhb wallet, creating any categories it needs."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(font(13, 400))
        subtitle.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(subtitle)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search rules by name, condition or assignment…"
        )
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFont(font(13, 400))
        self.search_edit.setToolTip(
            "Press Enter when nothing matches to create a new rule."
        )
        self.search_edit.textChanged.connect(self._search_changed)
        self.search_edit.returnPressed.connect(self._search_returned)
        root.addWidget(self.search_edit)
        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self._focus_search)

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
        self.import_button = QPushButton("Import from HomeBank…")
        close = QPushButton("Close")
        for button in (
            self.new_button,
            self.edit_button,
            self.delete_button,
            self.import_button,
            close,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(13, 400))
        self.new_button.setProperty("role", "primary")
        self.new_button.clicked.connect(self.new_rule)
        self.edit_button.clicked.connect(self.edit_rule)
        self.delete_button.clicked.connect(self.delete_rule)
        self.import_button.clicked.connect(self.import_homebank)
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        buttons.addWidget(self.new_button)
        buttons.addWidget(self.edit_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.import_button)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._reload_list()

    def _focus_search(self) -> None:
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    def _search_changed(self, _text: str) -> None:
        current = self._current_id()
        self._reload_list(select_id=current)

    def _search_returned(self) -> None:
        text = self.search_edit.text().strip()
        if not text or self.listing.count():
            return
        answer = QMessageBox.question(
            self,
            "No matching rule",
            f"No rule matches “{text}”.\n\nCreate a new rule?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        rule_id = self._open_new_rule(text)
        if rule_id is None:
            return
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.blockSignals(False)
        self._reload_list(rule_id)

    def _reload_list(self, select_id: int | None = None) -> None:
        query = self.search_edit.text().strip().casefold()
        self.listing.blockSignals(True)
        self.listing.clear()
        for rule in self.store.rules():
            summary = self._summary(rule)
            if query and query not in summary.casefold():
                continue
            item = QListWidgetItem(summary)
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

    @staticmethod
    def _condition_summary(condition: RuleCondition) -> str:
        fields = []
        if condition.match_memo:
            fields.append("Memo")
        if condition.match_payee:
            fields.append("Payee")
        parts: list[str] = []
        if condition.search:
            parts.append(f"“{condition.search}” in {' + '.join(fields) or '—'}")
        if condition.amount_enabled:
            symbol = {"-": "≤", "+": "≥"}.get(condition.amount_op, "=")
            parts.append(f"Amount {symbol} {condition.amount:,.2f}")
        if not parts:
            return "No condition"
        if condition.search and condition.amount_enabled:
            joiner = " AND " if condition.amount_and else " OR "
            return joiner.join(parts)
        return " · ".join(parts)

    def _summary(self, rule: Rule) -> str:
        conditions = rule.effective_conditions()
        if len(conditions) == 1:
            condition = self._condition_summary(conditions[0])
        else:
            joiner = " AND " if rule.condition_mode == "all" else " OR "
            condition = joiner.join(
                f"({self._condition_summary(item)})"
                for item in conditions
            )
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

    def _open_new_rule(self, prefill: str | None = None) -> int | None:
        dialog = RuleDialog(self.store, parent=self)
        if prefill:
            dialog.name_edit.setText(prefill)
            if dialog.condition_editors:
                dialog.condition_editors[0].search_edit.setText(prefill)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        rule = dialog.rule()
        if rule is None:
            return None
        rule_id = self.store.add_rule(rule)
        self.changed = True
        return rule_id

    def new_rule(self) -> None:
        rule_id = self._open_new_rule()
        if rule_id is not None:
            self._reload_list(rule_id)

    def import_homebank(self) -> None:
        """Import the automatic assignments stored in a HomeBank .xhb wallet."""
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Import HomeBank rules",
            "",
            "HomeBank wallet (*.xhb);;All files (*)",
        )
        if not path:
            return
        try:
            result = import_xhb_rules(self.store, path)
        except ValueError as error:
            QMessageBox.critical(self, "HomeBank import", str(error))
            return

        if result.imported:
            self.changed = True
        self._reload_list()

        box = QMessageBox(self)
        box.setWindowTitle("HomeBank import")
        box.setIcon(
            QMessageBox.Icon.Information
            if result.imported
            else QMessageBox.Icon.Warning
        )
        box.setText(result.summary())
        if result.warnings:
            box.setDetailedText("\n".join(result.warnings))
        box.exec()

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
