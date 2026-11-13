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
    QAbstractItemView,
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..branding import APP_NAME
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
from ..models import (
    Account,
    Category,
    SplitDraft,
    TransactionDraft,
    TransactionRow,
    ordered_categories,
)
from ..money import friendly_date, money
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


class _SplitDistributionBar(QWidget):
    """Thin stacked bar showing how the split total is distributed."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.parts: list[tuple[float, str]] = []
        self.setFixedHeight(9)
        self.setStyleSheet("background:transparent;")

    def set_parts(self, parts: list[tuple[float, str]]) -> None:
        self.parts = parts
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        total = sum(value for value, _color in self.parts) or 1.0
        x = 0.0
        width = self.width()
        for index, (value, color) in enumerate(self.parts):
            segment = width * value / total
            gap = 2 if index < len(self.parts) - 1 else 0
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(
                QRectF(x, 0, max(1.0, segment - gap), self.height()), 4, 4
            )
            x += segment
        painter.end()


class SplitEditorRow(QFrame):
    """One editable category allocation inside a split transaction."""

    def __init__(
        self,
        categories: list[Category],
        split: SplitDraft,
        on_changed,
        on_remove,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("splitEditorRow")
        self.setStyleSheet(
            f"QFrame#splitEditorRow {{ background:{C.INPUT_BG};"
            f" border:1px solid {C.INPUT_BORDER}; border-radius:7px; }}"
        )
        self._category_colors = {
            category.id: category.color for category in categories
        }
        self._on_changed = on_changed
        self._on_remove = on_remove
        self.split_id = split.id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(9)

        self.dot = QLabel()
        self.dot.setFixedSize(9, 9)
        layout.addWidget(self.dot)

        self.category_combo = QComboBox()
        self.category_combo.setFixedWidth(220)
        self.category_combo.setFont(font(13, 400))
        self.category_combo.addItem("Choose a category…", None)
        for category in ordered_categories(categories):
            self.category_combo.addItem(category.full_name, category.id)
        index = self.category_combo.findData(split.category_id)
        self.category_combo.setCurrentIndex(index if index >= 0 else 0)
        self.category_combo.currentIndexChanged.connect(self._category_changed)
        layout.addWidget(self.category_combo)

        self.memo_edit = QLineEdit(split.memo)
        self.memo_edit.setPlaceholderText("What was this part for?")
        self.memo_edit.setFont(font(13, 400))
        layout.addWidget(self.memo_edit, 1)

        self.tags_edit = QLineEdit(split.tags)
        self.tags_edit.setPlaceholderText("Tags")
        self.tags_edit.setFixedWidth(135)
        self.tags_edit.setFont(font(12, 400))
        layout.addWidget(self.tags_edit)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setDecimals(2)
        self.amount_spin.setRange(0.0, 999_999_999.0)
        self.amount_spin.setSingleStep(1.0)
        self.amount_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.amount_spin.setGroupSeparatorShown(True)
        self.amount_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.amount_spin.setFixedWidth(126)
        self.amount_spin.lineEdit().setMinimumWidth(110)
        self.amount_spin.setFont(font(14, 600))
        self.amount_spin.setValue(abs(float(split.amount)))
        self.amount_spin.valueChanged.connect(lambda _value: self._on_changed())
        layout.addWidget(self.amount_spin)

        self.percent_label = QLabel("—")
        self.percent_label.setFixedWidth(44)
        self.percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.percent_label.setFont(font(12, 500))
        self.percent_label.setStyleSheet(f"color:{C.MUTED};")
        layout.addWidget(self.percent_label)

        self.remove_button = QPushButton("×")
        self.remove_button.setProperty("role", "action")
        self.remove_button.setFixedSize(28, 28)
        self.remove_button.setFont(font(16, 400))
        self.remove_button.setToolTip("Remove this split")
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.clicked.connect(lambda: self._on_remove(self))
        layout.addWidget(self.remove_button)

        self._category_changed()

    def _category_changed(self) -> None:
        color = self._category_colors.get(self.category_combo.currentData())
        self.dot.setStyleSheet(
            f"background:{color or C.MUTED_DARK}; border-radius:4px;"
        )
        self._on_changed()

    def values(self) -> SplitDraft:
        return SplitDraft(
            id=self.split_id,
            category_id=self.category_combo.currentData(),
            amount=float(self.amount_spin.value()),
            memo=self.memo_edit.text().strip(),
            tags=self.tags_edit.text().strip(),
        )

    def set_percent(self, percent: float) -> None:
        self.percent_label.setText(f"{percent:.0f}%" if percent > 0 else "—")

    def set_remove_enabled(self, enabled: bool) -> None:
        self.remove_button.setEnabled(enabled)


class SplitDialog(QDialog):
    """Editor for dividing one transaction across several categories."""

    def __init__(
        self,
        store: DataStore,
        categories: list[Category],
        total: float,
        splits: list[SplitDraft] | None = None,
        currency_code: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.categories = ordered_categories(categories)
        self.total = abs(float(total))
        self.currency_code = currency_code
        self.rows: list[SplitEditorRow] = []
        self._result: list[SplitDraft] = []

        self.setWindowTitle("Split transaction")
        self.setModal(True)
        self.setMinimumSize(1040, 560)
        self.resize(1120, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        heading = QLabel("Split transaction")
        heading.setFont(font(20, 600))
        root.addWidget(heading)

        note = QLabel(
            f"Divide {money(self.total)} across two or more categories. "
            "The parent transaction keeps the bank amount; these splits feed "
            "reports, budgets and category totals."
        )
        note.setWordWrap(True)
        note.setFont(font(12, 400))
        note.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(note)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(18)
        summary_row.addWidget(self._stat("Bank amount", money(self.total)))
        self.count_label = QLabel("")
        self.count_label.setFont(font(12, 400))
        self.count_label.setStyleSheet(f"color:{C.MUTED};")
        summary_row.addWidget(self.count_label)
        summary_row.addStretch(1)
        distribute = QPushButton("Distribute remainder")
        distribute.setProperty("role", "action")
        distribute.setCursor(Qt.CursorShape.PointingHandCursor)
        distribute.setFont(font(12, 400))
        distribute.clicked.connect(self._distribute_remainder)
        summary_row.addWidget(distribute)
        root.addLayout(summary_row)

        self.bar = _SplitDistributionBar()
        root.addWidget(self.bar)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(9, 0, 9, 0)
        header_layout.setSpacing(9)
        for text, width in (
            ("", 9),
            ("Category", 220),
            ("Memo", 0),
            ("Tags", 135),
            ("Amount", 126),
            ("%", 44),
            ("", 28),
        ):
            label = QLabel(text)
            label.setFont(font(10, 600))
            label.setStyleSheet(f"color:{C.MUTED};")
            if width:
                label.setFixedWidth(width)
            if text in ("Amount", "%"):
                label.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            header_layout.addWidget(label, 1 if width == 0 else 0)
        root.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setMaximumHeight(280)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(
            f"QScrollArea {{ background:transparent; border:none; }}"
        )
        self.rows_widget = QWidget()
        self.rows_widget.setStyleSheet("background:transparent;")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(7)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.rows_widget)
        root.addWidget(self.scroll, 1)

        add_button = QPushButton("+  Add another split")
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.setFont(font(13, 500))
        add_button.setFixedHeight(36)
        add_button.setStyleSheet(
            f"QPushButton {{ background:transparent; border:1px dashed {C.INPUT_BORDER};"
            f" border-radius:7px; color:{C.MUTED}; text-align:left; padding-left:12px; }}"
            f"QPushButton:hover {{ background:{C.ROW_HOVER}; color:{C.TEXT}; }}"
        )
        add_button.clicked.connect(lambda: self.add_row(focus=True))
        root.addWidget(add_button)

        self.balance_label = QLabel("")
        self.balance_label.setFont(font(13, 500))
        root.addWidget(self.balance_label)
        root.addStretch(1)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button = buttons.addButton(
            "Save split", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        self.save_button.setProperty("role", "primary")
        self.save_button.setDefault(True)
        self.save_button.setAutoDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        initial = list(splits or [])
        if not initial:
            initial = [
                SplitDraft(category_id=None, amount=self.total),
                SplitDraft(category_id=None, amount=0.0),
            ]
        elif len(initial) == 1:
            initial.append(SplitDraft(category_id=None, amount=0.0))
        for split in initial:
            self.add_row(split)
        self._update_state()

    @staticmethod
    def _stat(label_text: str, value: str) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        label = QLabel(label_text.upper())
        label.setFont(font(10, 500))
        label.setStyleSheet(f"color:{C.MUTED};")
        value_label = QLabel(value)
        value_label.setFont(font(15, 600))
        value_label.setStyleSheet(f"color:{C.TEXT};")
        layout.addWidget(label)
        layout.addWidget(value_label)
        return box

    def _category_metadata(self, category_id: int | None) -> tuple[str, str, str]:
        for category in self.categories:
            if category.id == category_id:
                return category.full_name, category.color, category.kind
        return "Uncategorized", "", "expense"

    def add_row(
        self, split: SplitDraft | None = None, focus: bool = False
    ) -> SplitEditorRow:
        row = SplitEditorRow(
            self.categories,
            split or SplitDraft(category_id=None, amount=0.0),
            self._update_state,
            self.remove_row,
            self.rows_widget,
        )
        self.rows.append(row)
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self._update_state()
        if focus:
            row.category_combo.setFocus(Qt.FocusReason.OtherFocusReason)
        return row

    def remove_row(self, row: SplitEditorRow) -> None:
        if len(self.rows) <= 1:
            return
        self.rows.remove(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self._update_state()

    def _update_state(self) -> None:
        if not self.rows:
            return
        assigned = sum(row.amount_spin.value() for row in self.rows)
        remaining = self.total - assigned
        for row in self.rows:
            row.set_percent(
                (row.amount_spin.value() / self.total * 100)
                if self.total > 0
                else 0.0
            )
            row.set_remove_enabled(len(self.rows) > 1)
        self.count_label.setText(
            f"{len(self.rows)} parts · {money(assigned)} assigned"
        )
        self.bar.set_parts(
            [
                (
                    row.amount_spin.value(),
                    self._category_metadata(row.category_combo.currentData())[1]
                    or C.MUTED,
                )
                for row in self.rows
                if row.amount_spin.value() > 0.005
            ]
        )
        if abs(remaining) <= 0.005:
            self.balance_label.setText(
                f"✓ Balanced · {money(assigned)} of {money(self.total)} assigned"
            )
            self.balance_label.setStyleSheet(f"color:{C.GREEN};")
        elif remaining > 0:
            self.balance_label.setText(
                f"Remaining to assign: {money(remaining)}"
            )
            self.balance_label.setStyleSheet(f"color:{C.WARNING};")
        else:
            self.balance_label.setText(
                f"Over-assigned by {money(-remaining)}"
            )
            self.balance_label.setStyleSheet(f"color:{C.RED_BAR};")

    def _distribute_remainder(self) -> None:
        if not self.rows:
            return
        assigned = sum(row.amount_spin.value() for row in self.rows)
        remaining = round(self.total - assigned, 2)
        if abs(remaining) < 0.005:
            return
        last = self.rows[-1]
        value = round(last.amount_spin.value() + remaining, 2)
        last.amount_spin.setValue(max(0.0, value))

    def _validation_error(self) -> str | None:
        if len(self.rows) < 2:
            return "A split transaction needs at least two allocations."
        for index, row in enumerate(self.rows, start=1):
            if row.category_combo.currentData() is None:
                return f"Choose a category for split {index}."
            if row.amount_spin.value() <= 0.005:
                return f"Enter an amount greater than zero for split {index}."
        assigned = sum(row.amount_spin.value() for row in self.rows)
        if abs(assigned - self.total) > 0.005:
            return (
                f"The split total is {money(assigned)}, but the transaction "
                f"amount is {money(self.total)}."
            )
        return None

    def accept(self) -> None:
        error = self._validation_error()
        if error:
            QMessageBox.warning(self, "Split is not balanced", error)
            return
        self._result = []
        for row in self.rows:
            values = row.values()
            name, color, kind = self._category_metadata(values.category_id)
            values.category_name = name
            values.category_color = color
            values.category_kind = kind
            self._result.append(values)
        super().accept()

    def splits(self) -> list[SplitDraft]:
        return list(self._result)


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
        self._splits: list[SplitDraft] = list(draft.splits) if draft else []
        self._loading = draft is not None
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

        self.category_combo = SearchCombo(
            "Type a category, or Parent : Child to add one"
        )
        self._rebuild_categories("expense")
        self.category_row = self._field_row(
            "Category",
            self.category_combo,
            "Start typing to filter and choose a match. Text that is not in the "
            "list becomes a new category when you save; type Parent : Child to "
            "create a subcategory.",
        )
        root.addWidget(self.category_row)

        split_wrap = QWidget()
        split_layout = QHBoxLayout(split_wrap)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(8)
        self.split_summary = QLabel("One category")
        self.split_summary.setFont(font(12, 400))
        self.split_summary.setStyleSheet(f"color:{C.MUTED};")
        split_layout.addWidget(self.split_summary, 1)
        self.clear_split_button = QPushButton("Remove split")
        self.clear_split_button.setProperty("role", "action")
        self.clear_split_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_split_button.setFont(font(12, 400))
        self.clear_split_button.setAutoDefault(False)
        self.clear_split_button.clicked.connect(self._clear_split)
        self.clear_split_button.setVisible(False)
        split_layout.addWidget(self.clear_split_button)
        self.split_button = QPushButton("Split…")
        self.split_button.setProperty("role", "action")
        self.split_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.split_button.setFont(font(12, 400))
        self.split_button.setAutoDefault(False)
        self.split_button.clicked.connect(self.open_split_dialog)
        split_layout.addWidget(self.split_button)
        self.split_row = self._field_row(
            "Split",
            split_wrap,
            "Divide this transaction across several categories. The split "
            "total must match the transaction amount.",
        )
        root.addWidget(self.split_row)

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
            else "Enter saves · Tab moves · Alt+E/I/T type · Ctrl+0–5 status · Ctrl+R reconcile"
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
                self.split_row,
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
        self._sync_split_ui()

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
        if not self._scheduled:
            shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
            shortcut.activated.connect(self._reconcile_shortcut)

    def _reconcile_shortcut(self) -> None:
        if not self._scheduled:
            self._shortcut_status("reconciled")

    def _set_type(self, kind: str, adjust_amount: bool = True) -> None:
        if kind == "transfer" and self._scheduled:
            return
        previous = self._type
        self._type = kind
        if previous != kind and self._splits and not self._loading:
            self._splits = []
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
        if hasattr(self, "split_row"):
            self.split_row.setVisible(not is_transfer and not self._scheduled)
            self._sync_split_ui()

    def _rebuild_categories(self, kind: str) -> None:
        current = self.category_combo.currentData()
        choices = [("Uncategorized", None)]
        for category in ordered_categories(self.categories):
            if category.kind == kind:
                choices.append((category.full_name, category.id))
        self.category_combo.set_choices(choices, preserve_text=False)
        index = self.category_combo.findData(current)
        if index < 0:
            index = 0
        self.category_combo.setCurrentIndex(index)
        self.category_combo.setEditText(self.category_combo.itemText(index))

    # ------------------------------------------------------------------ split
    def _sync_split_ui(self) -> None:
        has_split = bool(self._splits)
        if not hasattr(self, "split_button"):
            return
        self.category_combo.setEnabled(not has_split)
        if has_split:
            total = sum(abs(split.amount) for split in self._splits)
            self.category_combo.setEditText(f"Split · {len(self._splits)} parts")
            self.split_summary.setText(
                f"{len(self._splits)} parts · {money(total)} assigned"
            )
            self.split_button.setText("Edit split…")
            self.clear_split_button.setVisible(True)
        else:
            self.split_summary.setText("One category")
            self.split_button.setText("Split…")
            self.clear_split_button.setVisible(False)

    def open_split_dialog(self) -> None:
        if self._type == "transfer":
            return
        total = abs(self.amount_spin.value())
        if total < 0.005:
            QMessageBox.warning(
                self, "Missing amount", "Enter the transaction amount first."
            )
            return
        initial = list(self._splits)
        if not initial:
            initial = [
                SplitDraft(
                    category_id=self.category_combo.resolved_data(),
                    amount=total,
                ),
                SplitDraft(category_id=None, amount=0.0),
            ]
        dialog = SplitDialog(
            self.store,
            [category for category in self.categories if category.kind == self._type],
            total,
            initial,
            self.currency_code,
            self,
        )
        if dialog.exec() == SplitDialog.DialogCode.Accepted:
            self._splits = dialog.splits()
            self._sync_split_ui()

    def _clear_split(self) -> None:
        self._splits = []
        self._rebuild_categories(self._type)
        self._sync_split_ui()

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
            self.split_button,
            self.clear_split_button,
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
        self._loading = False
        self._sync_split_ui()
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
            if self._splits:
                category_id = None
            else:
                category_id = self.category_combo.resolved_data()
                typed_category = self.category_combo.resolved_text()
                if (
                    category_id is None
                    and typed_category
                    and typed_category.casefold() != "uncategorized"
                ):
                    try:
                        category_id = self.store.ensure_category(
                            typed_category, self._type
                        )
                    except ValueError as error:
                        QMessageBox.warning(self, "Invalid category", str(error))
                        return
                    # Pick up the new category so the combo reflects it now.
                    self.categories = self.store.categories()
                    self._rebuild_categories(self._type)
                    index = self.category_combo.findData(category_id)
                    if index >= 0:
                        self.category_combo.setCurrentIndex(index)
            signed_amount = -abs(amount) if self._type == "expense" else abs(amount)

        splits: list[SplitDraft] = []
        if self._splits and self._type != "transfer":
            if len(self._splits) < 2:
                QMessageBox.warning(
                    self,
                    "Split is not balanced",
                    "A split transaction needs at least two allocations.",
                )
                return
            for index, split in enumerate(self._splits, start=1):
                if split.category_id is None:
                    QMessageBox.warning(
                        self,
                        "Split is not balanced",
                        f"Choose a category for split {index}.",
                    )
                    return
                if abs(split.amount) <= 0.005:
                    QMessageBox.warning(
                        self,
                        "Split is not balanced",
                        f"Enter an amount greater than zero for split {index}.",
                    )
                    return
            assigned = sum(abs(split.amount) for split in self._splits)
            if abs(assigned - abs(signed_amount)) > 0.005:
                QMessageBox.warning(
                    self,
                    "Split is not balanced",
                    f"The split total is {money(assigned)}, but the "
                    f"transaction amount is {money(abs(signed_amount))}.",
                )
                return
            sign = -1 if signed_amount < 0 else 1
            for split in self._splits:
                name = split.category_name
                color = split.category_color
                kind = split.category_kind or self._type
                if not name:
                    match = next(
                        (
                            category
                            for category in self.categories
                            if category.id == split.category_id
                        ),
                        None,
                    )
                    if match is not None:
                        name, color, kind = match.full_name, match.color, match.kind
                splits.append(
                    SplitDraft(
                        id=split.id,
                        category_id=split.category_id,
                        amount=sign * abs(split.amount),
                        memo=split.memo.strip(),
                        tags=split.tags.strip(),
                        category_name=name,
                        category_color=color,
                        category_kind=kind,
                    )
                )

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
            splits=splits,
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


class BulkEditDialog(QDialog):
    """Change fields shared by several selected ledger transactions."""

    def __init__(
        self,
        store: DataStore,
        categories: list[Category],
        count: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.count = count
        self.setWindowTitle(f"Edit {count} transactions")
        self.setModal(True)
        self.setMinimumWidth(590)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        heading = QLabel(f"Edit {count} transactions")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        note = QLabel(
            "Tick only the fields you want to change. Every other value is kept "
            "exactly as it is, and dates, amounts and accounts are not touched."
        )
        note.setWordWrap(True)
        note.setFont(font(12, 400))
        note.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(note)

        form = QFormLayout()
        form.setVerticalSpacing(9)
        form.setHorizontalSpacing(16)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.payee_combo = SearchCombo("Type a payee", auto_match=False)
        self.payee_combo.set_choices(
            [(payee, payee) for payee in store.payees()], select_first=False
        )
        self.payee_check, payee_row = self._edit_row(
            self.payee_combo, "Replace the payee on every selected transaction"
        )
        form.addRow("Payee:", payee_row)

        self.category_combo = QComboBox()
        self.category_combo.addItem("Uncategorized", None)
        for category in ordered_categories(categories):
            self.category_combo.addItem(category.full_name, category.id)
        self.category_check, category_row = self._edit_row(
            self.category_combo, "Replace the category on every selected transaction"
        )
        form.addRow("Category:", category_row)

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
        self.payment_check, payment_row = self._edit_row(
            self.payment_combo, "Replace the payment method on every selected transaction"
        )
        form.addRow("Payment:", payment_row)

        self.number_edit = QLineEdit()
        self.number_edit.setPlaceholderText("Cheque, invoice or reference number")
        self.number_check, number_row = self._edit_row(
            self.number_edit, "Replace the reference number on every selected transaction"
        )
        form.addRow("Number:", number_row)

        tags_field = QWidget()
        tags_layout = QHBoxLayout(tags_field)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(6)
        self.tags_combo = SearchCombo("Space-separated tags", auto_match=False)
        self.tags_combo.set_choices(
            [(tag, tag) for tag in store.tags()], select_first=False
        )
        tags_layout.addWidget(self.tags_combo, 1)
        self.tags_mode = QComboBox()
        self.tags_mode.addItem("Set to", "set")
        self.tags_mode.addItem("Add to", "add")
        self.tags_mode.setFixedWidth(108)
        self.tags_mode.setToolTip(
            "Set replaces the current tags; Add appends this text to them."
        )
        tags_layout.addWidget(self.tags_mode)
        self.tags_check, tags_row = self._edit_row(
            tags_field, "Change tags on every selected transaction"
        )
        form.addRow("Tags:", tags_row)

        self.memo_edit = QLineEdit()
        self.memo_edit.setPlaceholderText("Optional note")
        self.memo_check, memo_row = self._edit_row(
            self.memo_edit, "Replace the memo on every selected transaction"
        )
        form.addRow("Memo:", memo_row)

        root.addLayout(form)
        root.addStretch(1)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        self.apply_button = buttons.addButton(
            f"Apply to {count}", QDialogButtonBox.ButtonRole.AcceptRole
        )
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setAutoDefault(False)
        self.apply_button.setProperty("role", "primary")
        self.apply_button.setAutoDefault(True)
        self.apply_button.setDefault(True)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._update_apply()

    # ----------------------------------------------------------------- pieces
    def _edit_row(
        self, widget: QWidget, tooltip: str
    ) -> tuple[QCheckBox, QWidget]:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        check = QCheckBox()
        check.setToolTip(tooltip)
        widget.setEnabled(False)
        check.toggled.connect(widget.setEnabled)
        check.toggled.connect(self._update_apply)
        layout.addWidget(check)
        layout.addWidget(widget, 1)
        return check, row

    def _update_apply(self) -> None:
        enabled = any(
            check.isChecked()
            for check in (
                self.payee_check,
                self.category_check,
                self.payment_check,
                self.number_check,
                self.tags_check,
                self.memo_check,
            )
        )
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(enabled)

    # ----------------------------------------------------------------- result
    def changes(self) -> dict[str, object]:
        """Only the fields the user explicitly ticked."""
        changes: dict[str, object] = {}
        if self.payee_check.isChecked():
            changes["payee"] = self.payee_combo.currentText().strip()
        if self.category_check.isChecked():
            changes["category_id"] = self.category_combo.currentData()
        if self.payment_check.isChecked():
            text = self.payment_combo.currentText().strip()
            changes["payment"] = "" if text == "(none)" else text
        if self.number_check.isChecked():
            changes["number"] = self.number_edit.text().strip()
        if self.tags_check.isChecked():
            changes["tags"] = self.tags_combo.currentText().strip()
            changes["tags_mode"] = self.tags_mode.currentData()
        if self.memo_check.isChecked():
            changes["memo"] = self.memo_edit.text().strip()
        return changes


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

        intro = QLabel(f"{APP_NAME} is local-first. Everything lives in one SQLite file on this machine.")
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


class CategoryDialog(QDialog):
    """Create or edit a category, optionally as someone's subcategory."""

    def __init__(
        self,
        store: DataStore,
        category: Category | None = None,
        parent_id: int | None = None,
        parent: QWidget | None = None,
        kind: str = "expense",
    ):
        super().__init__(parent)
        self.store = store
        self.category = category
        self.setWindowTitle("Edit Category" if category else "New Category")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        heading = QLabel("Edit category" if category else "Add a category")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        intro = QLabel(
            "Subcategories share their parent's type and roll up into its "
            "charts, reports and budgets."
        )
        intro.setWordWrap(True)
        intro.setFont(font(13, 400))
        intro.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(intro)

        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(16)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Category name")
        if category is not None:
            self.name_edit.setText(category.name)
        self.name_edit.setFocus()
        form.addRow("Name", self.name_edit)

        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Expense", "expense")
        self.kind_combo.addItem("Income", "income")
        if category is not None and category.kind == "income":
            self.kind_combo.setCurrentIndex(1)
        elif category is None and kind == "income":
            self.kind_combo.setCurrentIndex(1)
        form.addRow("Type", self.kind_combo)

        self.parent_combo = QComboBox()
        self._rebuild_parents()
        form.addRow("Parent", self.parent_combo)
        root.addLayout(form)

        if parent_id is not None:
            index = self.parent_combo.findData(parent_id)
            if index >= 0:
                self.parent_combo.setCurrentIndex(index)
        elif category is not None and category.parent_id is not None:
            index = self.parent_combo.findData(category.parent_id)
            if index >= 0:
                self.parent_combo.setCurrentIndex(index)

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
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.kind_combo.currentIndexChanged.connect(self._rebuild_parents)

    def _rebuild_parents(self) -> None:
        kind = self.kind_combo.currentData()
        current = self.parent_combo.currentData()
        self.parent_combo.blockSignals(True)
        self.parent_combo.clear()
        self.parent_combo.addItem("None — top level", None)
        for category in ordered_categories(self.store.categories()):
            if category.kind != kind or category.parent_id is not None:
                continue
            if self.category is not None and category.id == self.category.id:
                continue
            self.parent_combo.addItem(category.name, category.id)
        index = self.parent_combo.findData(current)
        self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
        self.parent_combo.blockSignals(False)

    def values(self) -> tuple[str, str, int | None]:
        """(name, kind, parent id) as entered."""
        return (
            self.name_edit.text().strip(),
            self.kind_combo.currentData(),
            self.parent_combo.currentData(),
        )


class CategoryTransactionsDialog(QDialog):
    """All transactions filed under one category, newest first."""

    def __init__(
        self,
        store: DataStore,
        category: Category,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.category = category
        self._rows = []
        self._has_children = category.parent_id is None and any(
            child.parent_id == category.id for child in store.categories()
        )
        self.setWindowTitle(f"Transactions — {category.full_name}")
        self.setModal(True)
        self.setMinimumSize(860, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Transactions")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        subtitle = QLabel(
            f"Posted transactions in “{category.full_name}”, newest first."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(font(13, 400))
        subtitle.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(subtitle)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search payee, memo, account or tags…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(300)
        controls.addWidget(self.search_edit)
        controls.addStretch(1)
        self.sub_check = QCheckBox("Include subcategories")
        self.sub_check.setChecked(True)
        self.sub_check.setVisible(self._has_children)
        self.sub_check.setToolTip(
            "Also show transactions filed under this category's subcategories."
        )
        controls.addWidget(self.sub_check)
        root.addLayout(controls)

        self.summary = QLabel("")
        self.summary.setFont(font(13, 500))
        self.summary.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Account", "Payee", "Category", "Status", "Amount"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 105)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(1, 140)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(3, 190)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(4, 100)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(5, 120)
        root.addWidget(self.table, 1)

        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close)
        root.addLayout(close_row)

        self.search_edit.textChanged.connect(self._refresh)
        self.sub_check.toggled.connect(self._reload)
        self._reload()

    # ------------------------------------------------------------------- data
    def _reload(self) -> None:
        include = self._has_children and self.sub_check.isChecked()
        self._rows = self.store.category_transactions(
            self.category.id, include_subcategories=include
        )
        self._refresh()

    def _refresh(self) -> None:
        text = self.search_edit.text().strip().casefold()
        rows = self._rows
        if text:
            rows = [
                row
                for row in rows
                if text
                in " ".join(
                    (
                        row.payee,
                        row.account_name,
                        row.category_name,
                        row.memo,
                        row.tags,
                    )
                ).casefold()
            ]
        self._populate(rows)

    def _populate(self, rows: list[TransactionRow]) -> None:
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            date_item = QTableWidgetItem(friendly_date(row.date))
            date_item.setForeground(QColor(C.TEXT))
            self.table.setItem(index, 0, date_item)

            account_item = QTableWidgetItem(row.account_name)
            account_item.setForeground(QColor(C.TEXT))
            self.table.setItem(index, 1, account_item)

            payee_item = QTableWidgetItem(row.payee or "")
            payee_item.setForeground(QColor(C.TEXT))
            self.table.setItem(index, 2, payee_item)

            category_item = QTableWidgetItem(row.category_name)
            category_item.setForeground(QColor(C.TEXT))
            pixmap = QPixmap(10, 10)
            pixmap.fill(QColor(row.category_color))
            category_item.setIcon(QIcon(pixmap))
            self.table.setItem(index, 3, category_item)

            status_item = QTableWidgetItem(self._status(row))
            status_item.setForeground(
                QColor(C.MUTED if row.voided else C.TEXT)
            )
            self.table.setItem(index, 4, status_item)

            amount = QTableWidgetItem(money(row.amount))
            amount.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            if row.voided:
                strike = font(13, 400)
                strike.setStrikeOut(True)
                amount.setFont(strike)
                amount.setForeground(QColor(C.MUTED))
            else:
                amount.setForeground(
                    QColor(C.ORANGE if row.amount < 0 else C.GREEN)
                )
            self.table.setItem(index, 5, amount)

        total = sum(row.amount for row in rows if not row.voided)
        voided = sum(1 for row in rows if row.voided)
        count = len(rows)
        parts = [
            f"{count} transaction{'s' if count != 1 else ''}",
            f"net {money(total)}",
        ]
        if voided:
            parts.append(f"{voided} voided excluded")
        self.summary.setText("  ·  ".join(parts))

    @staticmethod
    def _status(row: TransactionRow) -> str:
        if row.voided:
            return "Void"
        if row.reconciled:
            return "Reconciled"
        if row.cleared:
            return "Cleared"
        return "Open"


class CategoriesDialog(QDialog):
    """Manage categories and their subcategories."""

    def __init__(self, store: DataStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.changed = False
        self.setWindowTitle("Categories")
        self.setModal(True)
        self.setMinimumSize(500, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Categories")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        sub = QLabel(
            "Expense and income categories are on separate tabs. Categories "
            "group transactions for the charts, reports, budgets and the "
            "ledger. Subcategories appear as “Parent : Child” and roll up into "
            "their parent. Select a category and press Delete to remove it."
        )
        sub.setWordWrap(True)
        sub.setFont(font(13, 400))
        sub.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(sub)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.expense_listing = self._make_listing()
        self.income_listing = self._make_listing()
        self.tabs.addTab(self.expense_listing, "Expense")
        self.tabs.addTab(self.income_listing, "Income")
        self.tabs.currentChanged.connect(self._update_buttons)
        root.addWidget(self.tabs, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.new_button = QPushButton("New…")
        self.edit_button = QPushButton("Edit…")
        self.transactions_button = QPushButton("Transactions…")
        self.transactions_button.setToolTip(
            "Show the transactions filed under the selected category"
        )
        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Delete the selected category (Del)")
        close = QPushButton("Close")
        for button in (
            self.new_button,
            self.edit_button,
            self.transactions_button,
            self.delete_button,
            close,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(font(13, 400))
        self.new_button.setProperty("role", "primary")
        self.new_button.clicked.connect(self.new_category)
        self.edit_button.clicked.connect(self.edit_category)
        self.transactions_button.clicked.connect(self.show_transactions)
        self.delete_button.clicked.connect(self.delete_category)
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        button_row.addWidget(self.new_button)
        button_row.addWidget(self.edit_button)
        button_row.addWidget(self.transactions_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(close)
        root.addLayout(button_row)

        self._reload_list()

    # ------------------------------------------------------------------ rows
    def _make_listing(self) -> QListWidget:
        listing = QListWidget()
        listing.setFont(font(13, 400))
        listing.setSpacing(2)
        listing.setIconSize(QSize(12, 12))
        listing.itemDoubleClicked.connect(lambda _item: self.edit_category())
        listing.itemSelectionChanged.connect(self._update_buttons)
        listing.installEventFilter(self)
        return listing

    @property
    def listing(self) -> QListWidget:
        """The list shown in the active tab (Expense by default)."""
        return self.tabs.currentWidget()

    def _current_kind(self) -> str:
        return "income" if self.tabs.currentWidget() is self.income_listing else "expense"

    def _reload_list(self, select_id: int | None = None) -> None:
        categories = ordered_categories(self.store.categories())
        subs_by_parent: dict[int, int] = {}
        for category in categories:
            if category.parent_id is not None:
                subs_by_parent[category.parent_id] = (
                    subs_by_parent.get(category.parent_id, 0) + 1
                )

        listings = {
            "expense": self.expense_listing,
            "income": self.income_listing,
        }
        counts = {"expense": 0, "income": 0}
        for listing in listings.values():
            listing.clear()
        for category in categories:
            kind = "income" if category.kind == "income" else "expense"
            detail = ""
            if category.parent_id is None and subs_by_parent.get(category.id):
                detail = f"{subs_by_parent[category.id]} subcategories"
            listings[kind].addItem(self._item(category, detail))
            counts[kind] += 1

        self.tabs.setTabText(0, f"Expense ({counts['expense']})")
        self.tabs.setTabText(1, f"Income ({counts['income']})")

        if select_id is not None:
            self._select_category(select_id)
        self._update_buttons()

    def _select_category(self, category_id: int) -> None:
        category = self.store.category(category_id)
        if category is None:
            return
        listing = (
            self.income_listing if category.kind == "income" else self.expense_listing
        )
        self.tabs.setCurrentWidget(listing)
        for row in range(listing.count()):
            item = listing.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == category_id:
                listing.setCurrentRow(row)
                break

    @staticmethod
    def _item(category: Category, detail: str) -> QListWidgetItem:
        item = QListWidgetItem()
        pixmap = QPixmap(12, 12)
        pixmap.fill(QColor(category.color))
        item.setIcon(QIcon(pixmap))
        item.setText(f"{category.full_name}\n{detail}" if detail else category.full_name)
        item.setData(Qt.ItemDataRole.UserRole, category.id)
        return item

    def _selected_category(self) -> Category | None:
        item = self.listing.currentItem()
        if item is None:
            return None
        return self.store.category(item.data(Qt.ItemDataRole.UserRole))

    def _update_buttons(self, *_args) -> None:
        selected = self._selected_category() is not None
        self.edit_button.setEnabled(selected)
        self.transactions_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    # ------------------------------------------------------------ keyboard
    def _is_delete_key(self, event) -> bool:
        return (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
        )

    @staticmethod
    def _is_edit_key(event) -> bool:
        return (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers()
            in (
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.KeypadModifier,
            )
        )

    def eventFilter(self, watched, event):  # noqa: N802
        if watched in (self.expense_listing, self.income_listing):
            if self._is_edit_key(event):
                self.tabs.setCurrentWidget(watched)
                self.edit_category()
                return True
            if self._is_delete_key(event):
                self.tabs.setCurrentWidget(watched)
                self.delete_category()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):  # noqa: N802
        if self._is_delete_key(event):
            self.delete_category()
            return
        super().keyPressEvent(event)

    def _default_parent_id(self) -> int | None:
        """Parent to offer first when adding from the current selection."""
        selected = self._selected_category()
        if selected is None:
            return None
        return selected.parent_id if selected.parent_id is not None else selected.id

    # --------------------------------------------------------------- actions
    def show_transactions(self) -> None:
        category = self._selected_category()
        if category is None:
            return
        CategoryTransactionsDialog(self.store, category, self).exec()

    def new_category(self) -> None:
        dialog = CategoryDialog(
            self.store,
            None,
            self._default_parent_id(),
            self,
            kind=self._current_kind(),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, kind, parent_id = dialog.values()
        try:
            category_id = self.store.add_category(name, kind, parent_id)
        except ValueError as error:
            self._warn(error)
            return
        self.changed = True
        self._reload_list(select_id=category_id)

    def edit_category(self) -> None:
        category = self._selected_category()
        if category is None:
            return
        dialog = CategoryDialog(self.store, category, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, kind, parent_id = dialog.values()
        try:
            self.store.update_category(category.id, name, kind, parent_id)
        except ValueError as error:
            self._warn(error)
            return
        self.changed = True
        self._reload_list(select_id=category.id)

    def delete_category(self) -> None:
        category = self._selected_category()
        if category is None:
            return
        if category.parent_id is not None:
            question = (
                f"Delete “{category.full_name}”?\n\n"
                f"Its transactions move to “{category.parent_name}”."
            )
        else:
            question = (
                f"Delete “{category.name}”?\n\n"
                "Its transactions become uncategorized and its subcategories "
                "become top-level categories."
            )
        box = QMessageBox(self)
        box.setWindowTitle("Delete category")
        box.setText(question)
        box.setInformativeText("This action cannot be undone.")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        )
        delete_button = box.button(QMessageBox.StandardButton.Discard)
        if delete_button is not None:
            delete_button.setText("Delete")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() != QMessageBox.StandardButton.Discard:
            return
        self.store.delete_category(category.id)
        self.changed = True
        self._reload_list()

    def _warn(self, error: Exception) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Cannot save category")
        box.setText(str(error))
        box.setIcon(QMessageBox.Icon.Warning)
        box.exec()


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
        f"<h3 style='color:{C.TITLE};'>{APP_NAME}</h3>"
        f"<p style='color:{C.TEXT_SOFT};'>A local-first personal finance dashboard.<br>"
        "Accounts, a transaction ledger, scheduled transactions, category spending and cash flow — "
        "built with Python, PySide6 and SQLite.</p>"
        f"<p style='color:{C.MUTED_DARK};'>Version {__version__} · no cloud, no account, no telemetry.</p>"
    )


SHORTCUT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Global",
        [
            ("Ctrl+K", "Show this shortcut list"),
            ("Ctrl+N", "New transaction"),
            ("Ctrl+Shift+N", "New account"),
            ("Ctrl+I", "Import CSV"),
            ("Ctrl+E", "Export CSV"),
            ("Ctrl+O", "Open database"),
            ("Ctrl+Shift+S", "Save database as"),
            ("Ctrl+L", "Open the selected account's ledger"),
            ("Ctrl+R", "Open the reports window"),
            ("Ctrl+B", "Open the budgets window"),
            ("F5", "Refresh the dashboard"),
            ("Ctrl+,", "Preferences"),
            ("Ctrl+Q", "Quit"),
        ],
    ),
    (
        "Accounts list",
        [
            ("↑ / ↓", "Move between accounts"),
            ("Home / End", "Jump to the first or last account"),
            ("Enter", "Open the selected account's ledger"),
        ],
    ),
    (
        "Account ledger",
        [
            ("↑ / ↓", "Move between transactions"),
            ("Home / End", "Jump to the newest or oldest transaction"),
            ("Enter", "Edit the selection (bulk edit when several rows are selected)"),
            ("Delete", "Delete the selected transaction"),
            ("Ctrl+Z", "Undo the last ledger change"),
            ("Ctrl+R", "Reconcile the selected transactions"),
            ("Ctrl+N", "New transaction"),
            ("Ctrl+D", "Inherit a new transaction from the selection"),
            (
                "Alt+V",
                "Void the highlighted closest amounts and reconcile the selected rows",
            ),
            ("Ctrl+W / Esc", "Close the ledger"),
        ],
    ),
    (
        "Transaction window",
        [
            ("Enter", "Save the transaction"),
            ("Tab", "Move to the next field"),
            ("Alt+E / Alt+I / Alt+T", "Expense, Income or Transfer"),
            ("Ctrl+0–5", "No status, Flagged, Cleared, Reconciled, Remind, Voided"),
            ("Ctrl+R", "Mark the transaction reconciled"),
            ("Esc", "Cancel"),
        ],
    ),
    (
        "Categories",
        [
            ("Enter", "Edit the selected category"),
            ("Delete", "Delete the selected category"),
        ],
    ),
    (
        "Reports window",
        [
            ("Ctrl+1 / Ctrl+2 / Ctrl+3", "Table, Pie chart or Bar chart"),
            ("F5", "Refresh the report"),
            ("Ctrl+W / Esc", "Close the reports window"),
        ],
    ),
    (
        "Budgets window",
        [
            ("← / →", "Previous or next budget period"),
            ("Esc", "Close the budgets window"),
        ],
    ),
]


def _shortcut_rows() -> list[tuple[str, str, str]]:
    return [
        (group, shortcut, description)
        for group, items in SHORTCUT_GROUPS
        for shortcut, description in items
    ]


def shortcuts_text() -> str:
    """Rich-text fallback listing every shortcut by context."""
    parts: list[str] = []
    for group, items in SHORTCUT_GROUPS:
        parts.append(f"<b>{group}</b><br>")
        for shortcut, description in items:
            parts.append(f"<b>{shortcut}</b> &nbsp; {description}<br>")
        parts.append("<br>")
    parts.append(
        f"<span style='color:{C.MUTED};'>Press Ctrl+K anywhere in {APP_NAME} to "
        "open this list.</span>"
    )
    return "".join(parts)


class ShortcutsDialog(QDialog):
    """Searchable list of every keyboard shortcut, opened with Ctrl+K."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Shortcuts")
        self.setModal(True)
        self.setMinimumSize(680, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        heading = QLabel("Keyboard shortcuts")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        subtitle = QLabel(
            f"Press Ctrl+K anywhere in {APP_NAME} to open this list. Type below to "
            "filter by context, key or action; Esc closes."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(font(13, 400))
        subtitle.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(subtitle)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter shortcuts…")
        self.search_edit.setClearButtonEnabled(True)
        root.addWidget(self.search_edit)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Where", "Shortcut", "Action"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setFont(font(13, 400))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        rows = _shortcut_rows()
        self.table.setRowCount(len(rows))
        for row, (group, shortcut, description) in enumerate(rows):
            for column, text in enumerate((group, shortcut, description)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 1:
                    item.setFont(font(13, 600))
                    item.setForeground(QColor(C.TITLE))
                self.table.setItem(row, column, item)
        root.addWidget(self.table, 1)

        self.search_edit.textChanged.connect(self._filter)
        self.search_edit.setFocus()

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.table.rowCount()):
            match = not needle or any(
                needle in (self.table.item(row, column).text().casefold())
                for column in range(self.table.columnCount())
            )
            self.table.setRowHidden(row, not match)

    def visible_rows(self) -> int:
        """Number of shortcut rows currently shown (tests and future search)."""
        return sum(
            not self.table.isRowHidden(row) for row in range(self.table.rowCount())
        )
