"""Modal dialogs: transactions, schedules, accounts, preferences."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import (
    QDate,
    QEvent,
    QRectF,
    QSize,
    QStringListModel,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import (
    date_format_choice,
    ledger_status_choice,
    remember_date_format,
    remember_ledger_status,
    remember_theme,
    theme_choice,
)
from ..dates import DATE_FORMATS, qt_date_format
from ..db import DataStore
from ..models import Account, Category, TransactionDraft
from ..theme import C, CLEARED, font, theme_options
from .icons import (
    IconButton,
    draw_bell,
    draw_check_circle,
    draw_flag,
    draw_info,
    draw_reconciled,
    draw_void,
)


class SearchCombo(QComboBox):
    """Editable combo with a contains-style completion popup."""

    def __init__(
        self,
        placeholder: str = "",
        parent: QWidget | None = None,
        auto_match: bool = True,
    ):
        super().__init__(parent)
        self._auto_match = auto_match
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMaxVisibleItems(12)
        self.lineEdit().setPlaceholderText(placeholder)
        self.lineEdit().setStyleSheet(
            f"background: transparent; border: none; padding: 0px; color: {C.TEXT};"
        )
        self._completion_model = QStringListModel(self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setMaxVisibleItems(12)
        self.setCompleter(self._completer)
        popup = self._completer.popup()
        popup.setStyleSheet(
            f"QListView {{ background:{C.POPUP_BG}; color:{C.POPUP_TEXT};"
            f" border:1px solid {C.POPUP_BORDER};"
            f" selection-background-color:{C.SELECTION};"
            f" selection-color:{C.SELECTION_TEXT}; outline:0; padding:3px; }}"
        )
        self.lineEdit().textEdited.connect(self._update_completion)
        self.lineEdit().installEventFilter(self)
        self._completer.activated[str].connect(self._apply_completion)

    def set_choices(
        self,
        choices: list[tuple[str, object]],
        preserve_text: bool = True,
        select_first: bool = True,
    ) -> None:
        old_text = self.currentText() if preserve_text else ""
        self.blockSignals(True)
        self.clear()
        for text, data in choices:
            self.addItem(text, data)
        self.blockSignals(False)
        self._completion_model.setStringList(
            [self.itemText(i) for i in range(self.count())]
        )
        if preserve_text and old_text:
            index = self.findText(old_text, Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchCaseSensitive)
            if index < 0:
                index = self.findText(old_text, Qt.MatchFlag.MatchExactly)
            if index >= 0:
                self.setCurrentIndex(index)
                self.setEditText(self.itemText(index))
            else:
                self.setEditText(old_text)
        elif select_first and self.count():
            self.setCurrentIndex(0)
        elif not select_first:
            self.setCurrentIndex(-1)
            self.setEditText("")

    def _update_completion(self, text: str) -> None:
        text = text.strip()
        if not text:
            self._completer.popup().hide()
            return
        self._completer.setCompletionPrefix(text)
        if self._completer.completionCount():
            self._completer.complete()
        else:
            self._completer.popup().hide()

    def _apply_completion(self, text: str) -> None:
        index = self.findText(text, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            self.setCurrentIndex(index)
        self.setEditText(text)
        self._completer.popup().hide()

    def commit_completion(self) -> None:
        popup = self._completer.popup()
        if popup.isVisible():
            index = popup.currentIndex()
            if index.isValid():
                text = str(index.data())
                self.setEditText(text)
                item_index = self.findText(text, Qt.MatchFlag.MatchExactly)
                if item_index >= 0:
                    self.setCurrentIndex(item_index)
                popup.hide()
                return
        text = self.currentText().strip()
        if not text or not self._auto_match:
            return
        index = self.findText(text, Qt.MatchFlag.MatchExactly)
        if index < 0:
            matches = [
                i for i in range(self.count())
                if self.itemText(i).lower().startswith(text.lower())
            ]
            if len(matches) == 1:
                index = matches[0]
        if index >= 0:
            self.setCurrentIndex(index)
            self.setEditText(self.itemText(index))

    def resolved_data(self):
        self.commit_completion()
        text = self.currentText().strip()
        index = self.findText(text, Qt.MatchFlag.MatchExactly)
        return self.itemData(index) if index >= 0 else None

    def resolved_text(self) -> str:
        self.commit_completion()
        return self.currentText().strip()

    def focusInEvent(self, event):  # noqa: N802
        super().focusInEvent(event)
        self.lineEdit().selectAll()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.lineEdit() and event.type() == QEvent.Type.FocusIn:
            self.lineEdit().selectAll()
        return super().eventFilter(obj, event)


def _info_button(text: str, parent: QWidget) -> IconButton:
    button = IconButton(draw_info, 22, text, color=C.INFO, parent=parent)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return button


def _drawer_icon(draw_fn, color: str, size: int = 18) -> QIcon:
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw_fn(p, QRectF(2, 2, size * scale - 4, size * scale - 4), QColor(color), 1.7)
    p.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


class TransactionDialog(QDialog):
    def __init__(
        self,
        store: DataStore,
        accounts: list[Account],
        categories: list[Category],
        draft: TransactionDraft | None = None,
        scheduled: bool = False,
        title: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.accounts = accounts
        self.categories = categories
        self._scheduled = scheduled
        self._draft: TransactionDraft | None = None
        self._type = "expense"
        self._cleared = True
        self._reconciled = False
        self._remind = False
        self._flagged = False
        self._voided = False
        self._transfer_id = draft.transfer_id if draft else None
        self.currency_code = store.get_setting("currency_code", "MXN") or "MXN"

        self.setWindowTitle(
            title or ("Scheduled Transaction" if scheduled else "Transaction")
        )
        self.setModal(True)
        self.setMinimumWidth(780)
        self.resize(820, 560 if not scheduled else 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 32, 14)
        root.setSpacing(10)

        tabs_row = QHBoxLayout()
        tabs_row.addStretch(1)
        tabs_row.addWidget(self._build_type_tabs())
        tabs_row.addStretch(1)
        root.addLayout(tabs_row)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat(qt_date_format())
        self.date_edit.setDate(
            QDate.currentDate().addDays(7) if scheduled else QDate.currentDate()
        )
        self.date_edit.setFixedWidth(194)
        root.addWidget(
            self._field_row(
                "Date",
                self.date_edit,
                "Transaction date. Type a date or use the calendar popup.",
                fixed=194,
            )
        )

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setDecimals(2)
        self.amount_spin.setRange(-999_999_999.0, 999_999_999.0)
        self.amount_spin.setSingleStep(1.0)
        self.amount_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.amount_spin.setGroupSeparatorShown(False)
        self.amount_spin.setFixedWidth(194)
        self.amount_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.amount_spin.lineEdit().setMinimumWidth(180)
        self.amount_spin.editingFinished.connect(self._normalize_amount_sign)
        amount_wrap = QWidget()
        amount_layout = QHBoxLayout(amount_wrap)
        amount_layout.setContentsMargins(0, 0, 0, 0)
        amount_layout.setSpacing(8)
        amount_layout.addWidget(self.amount_spin)
        currency = QLabel(self.currency_code)
        currency.setFont(font(13, 400))
        currency.setStyleSheet(f"color:{C.MUTED};")
        amount_layout.addWidget(currency)
        amount_layout.addStretch(1)
        root.addWidget(self._field_row("Amount", amount_wrap))

        self.account_combo = QComboBox()
        for account in accounts:
            self.account_combo.addItem(account.name, account.id)
        root.addWidget(
            self._field_row(
                "Account",
                self.account_combo,
                "The account this transaction belongs to.",
            )
        )

        self.to_account_row = self._field_row(
            "To account",
            self._build_to_account(),
            "The destination account for an internal transfer.",
        )
        self.to_account_row.setVisible(False)
        root.addWidget(self.to_account_row)

        self.payment_combo = SearchCombo("(none)", auto_match=False)
        payment_choices = [("(none)", "")]
        presets = [
            "Cash",
            "Credit card",
            "Debit card",
            "Bank transfer",
            "Check",
            "Direct debit",
            "Standing order",
            "Electronic payment",
            "Deposit",
            "Financial institution fee",
        ]
        seen = {""}
        for item in presets + store.payments():
            if item and item not in seen:
                payment_choices.append((item, item))
                seen.add(item)
        self.payment_combo.set_choices(payment_choices)
        self.payment_row = self._field_row("Payment", self.payment_combo, fixed=380)
        root.addWidget(self.payment_row)

        self.number_edit = QLineEdit()
        self.number_edit.setPlaceholderText("Cheque, invoice or reference number")
        self.number_edit.setFixedWidth(380)
        self.number_row = self._field_row("Number", self.number_edit, fixed=380)
        root.addWidget(self.number_row)

        self.payee_combo = SearchCombo("Type to search or add a payee", auto_match=False)
        self.payee_combo.set_choices([(p, p) for p in store.payees()], select_first=False)
        self.payee_row = self._field_row(
            "Payee",
            self.payee_combo,
            "Who paid or was paid. Start typing to search existing payees.",
        )
        root.addWidget(self.payee_row)

        self.category_combo = SearchCombo("Type to search categories")
        self._rebuild_categories("expense")
        self.category_row = self._field_row(
            "Category",
            self.category_combo,
            "Start typing to filter. Use the arrow keys to choose a match.",
        )
        root.addWidget(self.category_row)

        self.status_row = self._build_status_row()
        root.addWidget(self.status_row)

        self.memo_edit = QLineEdit()
        self.memo_edit.setPlaceholderText("Optional note")
        root.addWidget(
            self._field_row("Memo", self.memo_edit, "Optional free-text note.")
        )

        self.tags_combo = SearchCombo("Space-separated tags", auto_match=False)
        self.tags_combo.set_choices([(t, t) for t in store.tags()], select_first=False)
        self.tags_row = self._field_row(
            "Tags",
            self.tags_combo,
            "Tags separated by spaces, e.g. work travel.",
        )
        root.addWidget(self.tags_row)

        root.addStretch(1)

        bottom = QHBoxLayout()
        hint = QLabel(
            "Enter saves · Tab moves · Alt+E/I type"
            if scheduled
            else "Enter saves · Tab moves · Alt+E/I/T type · Ctrl+0–5 status"
        )
        hint.setFont(font(11, 400))
        hint.setStyleSheet(f"color:{C.MUTED_DARK};")
        bottom.addWidget(hint)
        bottom.addStretch(1)

        buttons = QDialogButtonBox()
        self.cancel_button = buttons.addButton(
            "Cancel", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setAutoDefault(False)
        self.ok_button = buttons.addButton(
            "Schedule" if scheduled else "OK",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self.ok_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ok_button.setProperty("role", "primary")
        self.ok_button.setDefault(True)
        self.ok_button.setAutoDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

        if scheduled:
            for widget in (
                self.payment_row,
                self.number_row,
                self.status_row,
                self.tags_row,
            ):
                widget.setVisible(False)
            self.type_buttons["transfer"].setVisible(False)

        self._type_shortcuts()
        self._status_shortcuts()
        self._wire_enter()
        self._set_tab_order()

        if draft is not None:
            self._populate(draft)
        else:
            self._set_type("expense", adjust_amount=False)
            self.amount_spin.setValue(0.0)
            self.payment_combo.setCurrentIndex(0)
            self.date_edit.setFocus()
            self._sync_status_buttons()

    # ------------------------------------------------------------------ pieces
    def _build_type_tabs(self) -> QWidget:
        tabs = QWidget()
        tabs.setObjectName("typeTabs")
        layout = QHBoxLayout(tabs)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_buttons: dict[str, QPushButton] = {}
        for index, (key, text) in enumerate(
            (("expense", "Expense"), ("income", "Income"), ("transfer", "Transfer"))
        ):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("typeTab", True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(31)
            button.setMinimumWidth(92)
            button.setToolTip(
                f"{text} (Alt+{text[0]})"
            )
            if index == 2:
                button.setStyleSheet("border-right: none;")
            button.clicked.connect(lambda _checked=False, k=key: self._set_type(k))
            self.type_group.addButton(button, index)
            self.type_buttons[key] = button
            layout.addWidget(button)
        tabs.setStyleSheet(
            f"""
            QWidget#typeTabs {{
                background: {C.PANEL};
                border: 1px solid {C.INPUT_BORDER};
                border-radius: 4px;
            }}
            QPushButton[typeTab="true"] {{
                background: transparent;
                border: none;
                border-right: 1px solid {C.INPUT_BORDER};
                border-radius: 0px;
                padding: 5px 20px;
                color: {C.TEXT_SOFT};
                font-size: 14px;
            }}
            QPushButton[typeTab="true"]:checked {{
                background: {C.TAB_ACTIVE_BG};
                color: {C.TEXT};
            }}
            """
        )
        return tabs

    def _build_to_account(self) -> QComboBox:
        self.to_account_combo = QComboBox()
        for account in self.accounts:
            self.to_account_combo.addItem(account.name, account.id)
        return self.to_account_combo

    def _field_row(
        self,
        label_text: str,
        widget: QWidget,
        info_text: str | None = None,
        fixed: int | None = None,
    ) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(f"{label_text}:")
        label.setFixedWidth(78)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setFont(font(13, 400))
        label.setStyleSheet(f"color:{C.MUTED};")
        layout.addWidget(label)
        if fixed is not None:
            widget.setFixedWidth(fixed)
        layout.addWidget(widget, 0 if fixed is not None else 1)
        if info_text:
            layout.addWidget(_info_button(info_text, self))
        if fixed is not None:
            layout.addStretch(1)
        return row

    def _build_status_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel("Status:")
        label.setFixedWidth(78)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setFont(font(13, 400))
        label.setStyleSheet(f"color:{C.MUTED};")
        layout.addWidget(label)

        box = QWidget()
        box.setStyleSheet(
            f"""
            QToolButton {{
                background: {C.INPUT_BG};
                border: 1px solid {C.INPUT_BORDER};
                border-radius: 3px;
                padding: 2px;
            }}
            QToolButton:hover {{ background: {C.ROW_HOVER}; }}
            QToolButton:checked {{
                background: {C.TAB_ACTIVE_BG};
                border-color: {C.FOCUS_BORDER};
            }}
            """
        )
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(4)

        definitions = [
            ("none", QIcon(), "No status (Ctrl+0)"),
            ("flagged", _drawer_icon(draw_flag, C.WARNING), "Flagged (Ctrl+1)"),
            ("cleared", _drawer_icon(draw_check_circle, CLEARED), "Cleared (Ctrl+2)"),
            ("reconciled", _drawer_icon(draw_reconciled, C.RECONCILED), "Reconciled (Ctrl+3)"),
            ("remind", _drawer_icon(draw_bell, C.WARNING), "Remind (Ctrl+4)"),
            ("voided", _drawer_icon(draw_void, C.MUTED_DARK), "Voided (Ctrl+5)"),
        ]
        self.status_buttons: dict[str, QToolButton] = {}
        for key, icon, tooltip in definitions:
            button = QToolButton()
            button.setCheckable(True)
            button.setFixedSize(32, 28)
            button.setIcon(icon)
            button.setIconSize(QSize(17, 17))
            button.setToolTip(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, k=key: self._status_clicked(k))
            self.status_buttons[key] = button
            box_layout.addWidget(button)
        layout.addWidget(box)
        layout.addStretch(1)
        return row

    # ------------------------------------------------------------------- type
    def _type_shortcuts(self) -> None:
        for key, sequence in (
            ("expense", "Alt+E"),
            ("income", "Alt+I"),
            ("transfer", "Alt+T"),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(lambda k=key: self._set_type(k))

    def _status_shortcuts(self) -> None:
        for key, sequence in (
            ("none", "Ctrl+0"),
            ("flagged", "Ctrl+1"),
            ("cleared", "Ctrl+2"),
            ("reconciled", "Ctrl+3"),
            ("remind", "Ctrl+4"),
            ("voided", "Ctrl+5"),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(lambda k=key: self._shortcut_status(k))

    def _set_type(self, kind: str, adjust_amount: bool = True) -> None:
        if kind == "transfer" and self._scheduled:
            return
        self._type = kind
        button = self.type_buttons.get(kind)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        is_transfer = kind == "transfer"
        if is_transfer:
            if adjust_amount:
                self.amount_spin.setValue(abs(self.amount_spin.value()))
            self.payee_row.setVisible(False)
            self.category_row.setVisible(False)
            self.to_account_row.setVisible(True)
            if self.to_account_combo.currentData() in (None, self.account_combo.currentData()):
                for i in range(self.to_account_combo.count()):
                    if self.to_account_combo.itemData(i) != self.account_combo.currentData():
                        self.to_account_combo.setCurrentIndex(i)
                        break
            self.category_combo.setCurrentIndex(0)
        else:
            self.payee_row.setVisible(True)
            self.category_row.setVisible(True)
            self.to_account_row.setVisible(False)
            if adjust_amount:
                value = abs(self.amount_spin.value())
                self.amount_spin.setValue(-value if kind == "expense" else value)
            self._rebuild_categories(kind)

    def _rebuild_categories(self, kind: str) -> None:
        current = self.category_combo.currentData()
        choices = [("Uncategorized", None)]
        for category in sorted(self.categories, key=lambda c: (c.sort_order, c.name)):
            if category.kind == kind:
                choices.append((category.name, category.id))
        self.category_combo.set_choices(choices, preserve_text=False)
        index = self.category_combo.findData(current)
        if index < 0:
            index = 0
        self.category_combo.setCurrentIndex(index)
        self.category_combo.setEditText(self.category_combo.itemText(index))

    def _normalize_amount_sign(self) -> None:
        if self._type == "expense":
            self.amount_spin.setValue(-abs(self.amount_spin.value()))
        elif self._type in ("income", "transfer"):
            self.amount_spin.setValue(abs(self.amount_spin.value()))

    # ----------------------------------------------------------------- status
    def _status_clicked(self, key: str) -> None:
        if key == "none":
            self._cleared = self._reconciled = self._remind = self._flagged = False
            self._voided = False
        elif key == "flagged":
            self._flagged = self.status_buttons["flagged"].isChecked()
        elif key == "cleared":
            if self.status_buttons["cleared"].isChecked():
                self._cleared = True
                self._reconciled = False
            else:
                self._cleared = False
                self._reconciled = False
        elif key == "reconciled":
            if self.status_buttons["reconciled"].isChecked():
                self._cleared = True
                self._reconciled = True
            else:
                self._reconciled = False
                self._cleared = False
        elif key == "remind":
            self._remind = self.status_buttons["remind"].isChecked()
        elif key == "voided":
            self._voided = self.status_buttons["voided"].isChecked()
        self._sync_status_buttons()

    def _shortcut_status(self, key: str) -> None:
        if key == "none":
            self._cleared = self._reconciled = self._remind = self._flagged = False
            self._voided = False
        elif key == "cleared":
            self._cleared, self._reconciled = True, False
        elif key == "reconciled":
            self._cleared, self._reconciled = True, True
        elif key == "remind":
            self._remind = not self._remind
        elif key == "flagged":
            self._flagged = not self._flagged
        elif key == "voided":
            self._voided = not self._voided
        self._sync_status_buttons()

    def _sync_status_buttons(self) -> None:
        if not hasattr(self, "status_buttons"):
            return
        states = {
            "none": not (
                self._cleared
                or self._reconciled
                or self._remind
                or self._flagged
                or self._voided
            ),
            "flagged": self._flagged,
            "cleared": self._cleared and not self._reconciled,
            "reconciled": self._reconciled,
            "remind": self._remind,
            "voided": self._voided,
        }
        for key, state in states.items():
            button = self.status_buttons[key]
            button.blockSignals(True)
            button.setChecked(state)
            button.blockSignals(False)

    # ------------------------------------------------------------------ enter
    def _wire_enter(self) -> None:
        targets: list[QWidget] = [self, self.cancel_button, self.ok_button]
        for widget in (
            self.date_edit,
            self.amount_spin,
            self.account_combo,
            self.to_account_combo,
            self.payment_combo,
            self.number_edit,
            self.payee_combo,
            self.category_combo,
            self.memo_edit,
            self.tags_combo,
        ):
            targets.append(widget)
            line_edit = getattr(widget, "lineEdit", lambda: None)()
            if line_edit is not None:
                targets.append(line_edit)
        targets.extend(self.status_buttons.values())
        for target in targets:
            target.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            if event.modifiers() in (
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.KeypadModifier,
            ):
                self._commit_editors()
                self._save()
                return True
        return super().eventFilter(obj, event)

    def _commit_editors(self) -> None:
        self.date_edit.interpretText()
        self.amount_spin.interpretText()
        for combo in (
            self.payment_combo,
            self.payee_combo,
            self.category_combo,
            self.tags_combo,
        ):
            combo.commit_completion()

    def _set_tab_order(self) -> None:
        order = [
            self.date_edit,
            self.amount_spin,
            self.account_combo,
            self.to_account_combo,
            self.payment_combo,
            self.number_edit,
            self.payee_combo,
            self.category_combo,
            self.memo_edit,
            self.tags_combo,
            self.cancel_button,
            self.ok_button,
        ]
        for first, second in zip(order, order[1:]):
            self.setTabOrder(first, second)

    # ---------------------------------------------------------------- populate
    def _populate(self, draft: TransactionDraft) -> None:
        if draft.transfer_account_id is not None or draft.transfer_id:
            kind = "transfer"
        else:
            kind = "expense" if draft.amount < 0 else "income"
        self._set_type(kind, adjust_amount=False)

        self.date_edit.setDate(QDate.fromString(draft.date, "yyyy-MM-dd"))
        account_index = self.account_combo.findData(draft.account_id)
        if account_index >= 0:
            self.account_combo.setCurrentIndex(account_index)
        if draft.transfer_account_id is not None:
            to_index = self.to_account_combo.findData(draft.transfer_account_id)
            if to_index >= 0:
                self.to_account_combo.setCurrentIndex(to_index)

        self.amount_spin.setValue(draft.amount)
        self.payment_combo.setEditText(draft.payment or "(none)")
        payment_index = self.payment_combo.findText(draft.payment or "(none)")
        if payment_index >= 0:
            self.payment_combo.setCurrentIndex(payment_index)
        self.number_edit.setText(draft.number)
        self._set_combo_text(self.payee_combo, draft.payee)
        self._set_combo_text(self.tags_combo, draft.tags)
        # Category belongs to the type; select it by id after the choices exist.
        category_index = self.category_combo.findData(draft.category_id)
        if category_index >= 0:
            self.category_combo.setCurrentIndex(category_index)
        self.memo_edit.setText(draft.memo)

        self._cleared = draft.reconciled or draft.cleared
        self._reconciled = draft.reconciled
        self._remind = draft.remind
        self._flagged = draft.flagged
        self._voided = draft.voided
        self._sync_status_buttons()
        self._normalize_amount_sign()
        self.date_edit.setFocus()

    @staticmethod
    def _set_combo_text(combo: SearchCombo, text: str) -> None:
        index = combo.findText(text, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            combo.setCurrentIndex(index)
            combo.setEditText(text)
        elif text:
            combo.setEditText(text)

    # -------------------------------------------------------------------- save
    def _save(self) -> None:
        self._commit_editors()
        amount = self.amount_spin.value()
        if abs(amount) < 0.005:
            QMessageBox.warning(self, "Missing amount", "Enter an amount before saving.")
            return
        account_id = self.account_combo.currentData()
        if account_id is None:
            QMessageBox.warning(self, "Missing account", "Choose an account.")
            return

        transfer_account_id = None
        if self._type == "transfer":
            transfer_account_id = self.to_account_combo.currentData()
            if transfer_account_id is None or transfer_account_id == account_id:
                QMessageBox.warning(
                    self,
                    "Invalid transfer",
                    "Choose a different destination account.",
                )
                return
            payee = "Transfer"
            category_id = None
            signed_amount = -abs(amount)
        else:
            payee = self.payee_combo.resolved_text()
            category_id = self.category_combo.resolved_data()
            signed_amount = -abs(amount) if self._type == "expense" else abs(amount)

        cleared = self._cleared
        reconciled = self._reconciled
        if self._scheduled:
            cleared = True
            reconciled = False
        self._draft = TransactionDraft(
            date=self.date_edit.date().toString("yyyy-MM-dd"),
            account_id=account_id,
            payee=payee,
            category_id=category_id,
            amount=signed_amount,
            memo=self.memo_edit.text().strip(),
            cleared=cleared,
            reconciled=reconciled,
            remind=self._remind if not self._scheduled else False,
            flagged=self._flagged if not self._scheduled else False,
            voided=self._voided if not self._scheduled else False,
            payment=self.payment_combo.resolved_text().strip()
            if self.payment_combo.resolved_text().strip() != "(none)"
            else "",
            number=self.number_edit.text().strip(),
            tags=self.tags_combo.resolved_text().strip(),
            transfer_account_id=transfer_account_id,
            transfer_id=self._transfer_id if transfer_account_id is not None else None,
            scheduled=self._scheduled,
        )
        super().accept()

    def draft(self) -> TransactionDraft | None:
        return self._draft


class AccountDialog(QDialog):
    def __init__(
        self,
        account: Account | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.account = account
        self.setWindowTitle("Edit Account" if account else "New Account")
        self.setModal(True)
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        heading = QLabel("Edit account" if account else "Add an account")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Account name")
        form.addRow("Name", self.name_edit)

        self.kind_combo = QComboBox()
        for label in ("Bank", "Cash", "Credit card", "Savings"):
            self.kind_combo.addItem(label, label)
        form.addRow("Type", self.kind_combo)

        self.opening_spin = QDoubleSpinBox()
        self.opening_spin.setPrefix("$ ")
        self.opening_spin.setRange(-999_999_999.0, 999_999_999.0)
        self.opening_spin.setDecimals(2)
        self.opening_spin.setGroupSeparatorShown(True)
        form.addRow("Opening balance", self.opening_spin)
        root.addLayout(form)

        note = QLabel("Balances are computed from the opening balance plus all transactions.")
        note.setWordWrap(True)
        note.setFont(font(12, 400))
        note.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(note)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        save = buttons.addButton("Save account", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        save.setProperty("role", "primary")
        save.setAutoDefault(True)
        save.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self._save)
        root.addWidget(buttons)

        if account:
            self.name_edit.setText(account.name)
            index = self.kind_combo.findData(account.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
            self.opening_spin.setValue(account.opening)

    def _save(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Give the account a name.")
            return
        super().accept()

    def values(self) -> tuple[str, str, float]:
        return (
            self.name_edit.text().strip(),
            self.kind_combo.currentData(),
            self.opening_spin.value(),
        )


class DateRangeDialog(QDialog):
    """Ask for a custom start and end date."""

    def __init__(
        self,
        start: date,
        end: date,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Custom date range")
        self.setModal(True)
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        heading = QLabel("Custom date range")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        note = QLabel("Show transactions dated inside this range, inclusive.")
        note.setWordWrap(True)
        note.setFont(font(12, 400))
        note.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(note)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)
        self.start_edit = QDateEdit(QDate(start.year, start.month, start.day))
        self.end_edit = QDateEdit(QDate(end.year, end.month, end.day))
        for editor in (self.start_edit, self.end_edit):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat(qt_date_format())
            editor.setFixedWidth(170)
        form.addRow("From", self.start_edit)
        form.addRow("To", self.end_edit)
        root.addLayout(form)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        apply = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        apply.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        apply.setProperty("role", "primary")
        apply.setAutoDefault(True)
        apply.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    def values(self) -> tuple[date, date]:
        start = self.start_edit.date()
        end = self.end_edit.date()
        return (
            date(start.year(), start.month(), start.day()),
            date(end.year(), end.month(), end.day()),
        )

    def accept(self) -> None:
        start, end = self.values()
        if start > end:
            QMessageBox.warning(
                self,
                "Invalid date range",
                "The start date must be on or before the end date.",
            )
            return
        super().accept()


class PreferencesDialog(QDialog):
    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.was_reset = False
        self.changed_theme = False
        self.changed_date_format = False
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        heading = QLabel("Preferences")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        intro = QLabel("ContaPy is local-first. Everything lives in one SQLite file on this machine.")
        intro.setWordWrap(True)
        intro.setFont(font(13, 400))
        intro.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(intro)

        theme_row = QHBoxLayout()
        theme_row.setSpacing(10)
        theme_label = QLabel("Theme")
        theme_label.setFont(font(13, 400))
        theme_label.setStyleSheet(f"color:{C.TEXT_SOFT};")
        theme_row.addWidget(theme_label)
        self.theme_combo = QComboBox()
        self.theme_combo.setFont(font(13, 400))
        for option in theme_options():
            self.theme_combo.addItem(option.label, option.slug)
        current_theme = theme_choice()
        index = self.theme_combo.findData(current_theme)
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)
        theme_row.addWidget(self.theme_combo, 1)
        root.addLayout(theme_row)

        theme_help = QLabel(
            "One Dark is the default. Theme changes apply immediately."
        )
        theme_help.setWordWrap(True)
        theme_help.setFont(font(12, 400))
        theme_help.setStyleSheet(f"color:{C.MUTED_DARK};")
        root.addWidget(theme_help)

        date_row = QHBoxLayout()
        date_row.setSpacing(10)
        date_label = QLabel("Date format")
        date_label.setFont(font(13, 400))
        date_label.setStyleSheet(f"color:{C.TEXT_SOFT};")
        date_row.addWidget(date_label)
        self.date_format_combo = QComboBox()
        self.date_format_combo.setFont(font(13, 400))
        for item in DATE_FORMATS:
            self.date_format_combo.addItem(item.label, item.key)
        date_index = self.date_format_combo.findData(date_format_choice())
        self.date_format_combo.setCurrentIndex(date_index if date_index >= 0 else 0)
        date_row.addWidget(self.date_format_combo, 1)
        root.addLayout(date_row)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_label = QLabel("Ledger status")
        status_label.setFont(font(13, 400))
        status_label.setStyleSheet(f"color:{C.TEXT_SOFT};")
        status_row.addWidget(status_label)
        self.ledger_status_combo = QComboBox()
        self.ledger_status_combo.setFont(font(13, 400))
        for key, label in (
            ("any", "Any status"),
            ("unreconciled", "Unreconciled"),
            ("cleared", "Cleared"),
            ("reconciled", "Reconciled"),
            ("remind", "Remind"),
            ("flagged", "Flagged"),
            ("voided", "Voided"),
        ):
            self.ledger_status_combo.addItem(label, key)
        status_index = self.ledger_status_combo.findData(ledger_status_choice())
        self.ledger_status_combo.setCurrentIndex(status_index if status_index >= 0 else 0)
        status_row.addWidget(self.ledger_status_combo, 1)
        root.addLayout(status_row)

        display_help = QLabel(
            "Dates use this format across the dashboard. The ledger opens with "
            "the selected status filter; Any status shows everything."
        )
        display_help.setWordWrap(True)
        display_help.setFont(font(12, 400))
        display_help.setStyleSheet(f"color:{C.MUTED_DARK};")
        root.addWidget(display_help)

        path_label = QLabel(str(store.path))
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setFont(font(12, 400))
        path_label.setStyleSheet(
            f"color:{C.TEXT_SOFT}; background:{C.INPUT_BG}; border:1px solid {C.INPUT_BORDER};"
            f"border-radius:4px; padding:8px;"
        )
        root.addWidget(path_label)

        stats = QLabel(store.summary_line())
        stats.setFont(font(13, 400))
        stats.setStyleSheet(f"color:{C.TEXT_SOFT};")
        root.addWidget(stats)

        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(8)
        open_button = QPushButton("Open data folder")
        open_button.setAutoDefault(False)
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self._open_folder)
        buttons_row.addWidget(open_button)
        reset_button = QPushButton("Reset demo data")
        reset_button.setAutoDefault(False)
        reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_button.clicked.connect(self._reset)
        buttons_row.addWidget(reset_button)
        buttons_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.setAutoDefault(False)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.clicked.connect(self.accept)
        buttons_row.addWidget(close_button)
        root.addLayout(buttons_row)

        footer = QLabel(
            "Resetting replaces all accounts, transactions and schedules with the demo dataset."
        )
        footer.setWordWrap(True)
        footer.setFont(font(12, 400))
        footer.setStyleSheet(f"color:{C.MUTED_DARK};")
        root.addWidget(footer)

    def accept(self) -> None:
        choice = self.theme_combo.currentData()
        if choice and choice != theme_choice():
            remember_theme(choice)
            self.changed_theme = True
        date_key = self.date_format_combo.currentData()
        if date_key and date_key != date_format_choice():
            remember_date_format(date_key)
            self.changed_date_format = True
        status = self.ledger_status_combo.currentData()
        if status and status != ledger_status_choice():
            remember_ledger_status(status)
        super().accept()

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.path.parent)))

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset demo data?",
            "This deletes every account, transaction and scheduled item and restores the demo dataset.\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Reset,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Reset:
            self.store.reset_demo_data()
            self.was_reset = True
            self.accept()


class ListDialog(QDialog):
    def __init__(
        self,
        title: str,
        subtitle: str,
        rows: list[tuple[str, str]],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(460, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        heading = QLabel(title)
        heading.setFont(font(18, 600))
        root.addWidget(heading)
        sub = QLabel(subtitle)
        sub.setWordWrap(True)
        sub.setFont(font(13, 400))
        sub.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(sub)

        listing = QListWidget()
        for name, detail in rows:
            listing.addItem(f"{name}\n{detail}" if detail else name)
        listing.setFont(font(13, 400))
        listing.setSpacing(2)
        root.addWidget(listing, 1)

        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


def about_text() -> str:
    return (
        f"<h3 style='color:{C.TITLE};'>ContaPy</h3>"
        f"<p style='color:{C.TEXT_SOFT};'>A local-first personal finance dashboard.<br>"
        "Accounts, a transaction ledger, scheduled transactions, category spending and cash flow — "
        "built with Python, PySide6 and SQLite.</p>"
        f"<p style='color:{C.MUTED_DARK};'>Version {__version__} · no cloud, no account, no telemetry.</p>"
    )


def shortcuts_text() -> str:
    return (
        "<b>Ctrl+N</b> &nbsp; New transaction<br>"
        "<b>Ctrl+Shift+N</b> &nbsp; New account<br>"
        "<b>Ctrl+I</b> &nbsp; Import CSV<br>"
        "<b>Ctrl+E</b> &nbsp; Export CSV<br>"
        "<b>Ctrl+O</b> &nbsp; Open database<br>"
        "<b>Ctrl+Shift+S</b> &nbsp; Save database as<br>"
        "<b>Ctrl+L</b> &nbsp; Open account ledger<br>"
        "<b>Ctrl+R</b> &nbsp; Open reports<br>"
        "<b>F5</b> &nbsp; Refresh dashboard<br>"
        "<b>Ctrl+,</b> &nbsp; Preferences<br>"
        "<b>Ctrl+Q</b> &nbsp; Quit<br><br>"
        "<b>In the accounts list</b><br>"
        "<b>↑/↓</b> move · <b>Home/End</b> jump · <b>Enter</b> open ledger<br><br>"
        "<b>In the ledger</b><br>"
        "<b>↑/↓</b> move · <b>Home/End</b> jump · <b>Enter</b> open · "
        "<b>Delete</b> remove · <b>Esc</b> close<br><br>"
        "<b>In the transaction window</b><br>"
        "<b>Enter</b> saves · <b>Tab</b> moves · <b>Alt+E/I/T</b> type · "
        "<b>Ctrl+0–5</b> status<br><br>"
        "<b>In the reports window</b><br>"
        "<b>Ctrl+1/2/3</b> table, pie, bar · <b>F5</b> refresh · "
        "<b>Esc</b> close<br><br>"
        f"<span style='color:{C.MUTED};'>Double-click an account to open its ledger, or a "
        "scheduled transaction to edit and post it.</span>"
    )
