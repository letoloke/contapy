"""Tests for the ledger's date filters and amount highlighting."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from contapy.db import DataStore
from contapy.models import (
    Rule,
    SplitDraft,
    Template,
    TransactionDraft,
    TransactionRow,
)
from contapy.theme import C
from contapy.widgets.dialogs import BulkEditDialog, DateRangeDialog
from contapy.widgets.ledger import (
    CUSTOM_RANGE,
    EXPENSE,
    HEADERS,
    LedgerWindow,
    category_text_color,
    date_bounds,
    exact_amount_ids,
)


def row(row_id: int, amount: float, voided: bool = False) -> TransactionRow:
    return TransactionRow(
        id=row_id,
        account_id=1,
        account_name="Checking",
        date="2026-02-14",
        payee="Payee",
        category_id=None,
        category_name="Uncategorized",
        category_color="#ffffff",
        category_kind="expense",
        amount=amount,
        voided=voided,
    )


class DateBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_custom_range_is_returned_as_is(self) -> None:
        custom = (date(2026, 9, 1), date(2026, 11, 8))
        self.assertEqual(date_bounds(CUSTOM_RANGE, custom), custom)

    def test_custom_range_without_a_selection_has_no_bounds(self) -> None:
        self.assertEqual(date_bounds(CUSTOM_RANGE, None), (None, None))

    def test_custom_range_dialog_returns_the_selected_dates(self) -> None:
        dialog = DateRangeDialog(date(2026, 1, 5), date(2026, 2, 10))
        self.assertEqual(dialog.values(), (date(2026, 1, 5), date(2026, 2, 10)))
        dialog.deleteLater()


class CategoryColorTests(unittest.TestCase):
    def test_uncategorized_transactions_use_red_letters(self) -> None:
        uncategorized = row(1, -10)
        color = category_text_color(uncategorized, QColor("#ffffff"), False)
        self.assertEqual(color.name(), QColor(C.RED_BAR).name())

    def test_assigned_categories_keep_the_normal_text_color(self) -> None:
        assigned = row(1, -10)
        assigned.category_id = 7
        color = category_text_color(assigned, QColor("#ffffff"), False)
        self.assertEqual(color.name(), "#ffffff")

    def test_transfer_category_uses_muted_gray(self) -> None:
        transfer = row(1, -10)
        transfer.transfer_id = "transfer-group"
        color = category_text_color(transfer, QColor("#ffffff"), False)
        self.assertEqual(color.name(), QColor(C.MUTED).name())

    def test_voided_category_uses_muted_gray(self) -> None:
        voided = row(1, -10, voided=True)
        voided.category_id = 7
        color = category_text_color(voided, QColor("#ffffff"), False)
        self.assertEqual(color.name(), QColor(C.MUTED).name())

        uncategorized = row(2, -10, voided=True)
        color = category_text_color(uncategorized, QColor("#ffffff"), False)
        self.assertEqual(color.name(), QColor(C.MUTED).name())


class LedgerHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from contapy.widgets import ledger as ledger_module

        ledger_module._COPIED_TRANSACTIONS.clear()
        self.addCleanup(ledger_module._COPIED_TRANSACTIONS.clear)
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "hint.db", seed=False)
        account = self.store.add_account("Checking", "Bank", 1_000)
        today = date.today().isoformat()
        for amount in (-400, -600, -1_000):
            self.store.add_transaction(
                TransactionDraft(
                    date=today,
                    account_id=account,
                    payee="Test",
                    category_id=None,
                    amount=amount,
                )
            )
        self.window = LedgerWindow(self.store, account)

    def tearDown(self) -> None:
        self.window.close()
        self.store.close()
        self.tmp.cleanup()

    def test_store_bulk_update_leaves_other_rows_and_fields_alone(self) -> None:
        rows = self.window.model.rows
        target_ids = [rows[0].id, rows[1].id]
        untouched_id = rows[2].id
        before = {row.id: row for row in self.store.ledger_rows(self.window.account_id)}

        self.store.update_transactions(
            target_ids, payee="Bulk", tags="shared", memo="batch"
        )

        after = {row.id: row for row in self.store.ledger_rows(self.window.account_id)}
        for transaction_id in target_ids:
            self.assertEqual(after[transaction_id].payee, "Bulk")
            self.assertEqual(after[transaction_id].tags, "shared")
            self.assertEqual(after[transaction_id].memo, "batch")
            self.assertEqual(after[transaction_id].amount, before[transaction_id].amount)
            self.assertEqual(
                after[transaction_id].category_id, before[transaction_id].category_id
            )
        self.assertEqual(after[untouched_id].payee, before[untouched_id].payee)
        self.assertEqual(after[untouched_id].tags, before[untouched_id].tags)
        self.assertEqual(after[untouched_id].memo, before[untouched_id].memo)

    def test_bulk_edit_dialog_only_returns_ticked_fields(self) -> None:
        dialog = BulkEditDialog(self.store, self.store.categories(), 2)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.changes(), {})

        dialog.category_check.setChecked(True)
        dialog.category_combo.setCurrentIndex(
            dialog.category_combo.findData(None)
        )
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.changes(), {"category_id": None})

        dialog.tags_check.setChecked(True)
        dialog.tags_combo.setEditText("shared")
        dialog.tags_mode.setCurrentIndex(dialog.tags_mode.findData("add"))
        self.assertEqual(
            dialog.changes(),
            {"category_id": None, "tags": "shared", "tags_mode": "add"},
        )

    def test_edit_with_multiple_rows_applies_bulk_changes(self) -> None:
        from contapy.widgets import ledger as ledger_module

        rows = self.window.model.rows
        selected_ids = [rows[0].id, rows[1].id]
        self.window._select_ids(selected_ids)

        class FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def changes(self) -> dict[str, object]:
                return {"payee": "Bulk", "tags": "batch", "tags_mode": "set"}

        with mock.patch.object(ledger_module, "BulkEditDialog", FakeDialog):
            self.window.edit_transaction()

        updated = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in selected_ids:
            self.assertEqual(updated[transaction_id].payee, "Bulk")
            self.assertEqual(updated[transaction_id].tags, "batch")

    def test_bulk_edit_can_append_tags(self) -> None:
        from contapy.widgets import ledger as ledger_module

        rows = self.window.model.rows
        selected_ids = [rows[0].id, rows[1].id]
        self.store.update_transactions(selected_ids, tags="existing")
        self.window.reload()
        self.window._select_ids(selected_ids)

        class FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def changes(self) -> dict[str, object]:
                return {"tags": "extra", "tags_mode": "add"}

        with mock.patch.object(ledger_module, "BulkEditDialog", FakeDialog):
            self.window.edit_transaction()

        updated = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in selected_ids:
            self.assertEqual(updated[transaction_id].tags, "existing extra")

    def test_ledger_has_no_tooltips(self) -> None:
        index = self.window.model.index(0, 0)
        self.assertIsNone(
            self.window.model.data(index, Qt.ItemDataRole.ToolTipRole)
        )
        self.assertEqual(self.window.table.toolTip(), "")
        self.assertEqual(self.window.clear_btn.toolTip(), "")
        self.assertEqual(self.window.reconcile_btn.toolTip(), "")

    def test_tags_column_shows_transaction_tags(self) -> None:
        self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.window.account_id,
                payee="Tagged",
                category_id=None,
                amount=-25,
                tags="home, tax",
            )
        )
        self.window.reload()

        tag_col = HEADERS.index("Tags")
        self.assertEqual(
            self.window.model.headerData(tag_col, Qt.Orientation.Horizontal),
            "Tags",
        )
        values = [
            self.window.model.data(self.window.model.index(index, tag_col))
            for index in range(self.window.model.rowCount())
        ]
        self.assertIn("home, tax", values)

    def test_ctrl_r_reconciles_the_selection(self) -> None:
        ids = [row.id for row in self.window.model.rows]
        self.window._select_ids(ids)
        self.window.changed.connect(self.window.reload)
        self.assertEqual(self.window.act_reconcile.shortcut().toString(), "Ctrl+R")

        self.window.act_reconcile.trigger()

        rows = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in ids:
            self.assertTrue(rows[transaction_id].cleared)
            self.assertTrue(rows[transaction_id].reconciled)
        self.assertEqual(self.window._selected_ids(), ids)
        current = self.window.table.currentIndex()
        self.assertTrue(current.isValid())
        self.assertIn(self.window.model.rows[current.row()].id, ids)
        self.assertIn("reconcile", self.window.act_undo.text())

        self.window.undo()
        restored = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in ids:
            self.assertFalse(restored[transaction_id].reconciled)

    def test_activity_messages_include_transaction_memos(self) -> None:
        from contapy.widgets import ledger as ledger_module

        transaction_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.window.account_id,
                payee="Coffee",
                category_id=None,
                amount=-25,
                memo="Oat milk",
            )
        )
        self.window.reload()
        self.window._select_ids([transaction_id])
        messages: list[str] = []
        self.window.activity.connect(messages.append)

        with mock.patch.object(
            ledger_module.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window.delete_transaction()

        self.assertTrue(
            any("memo: Oat milk" in message for message in messages)
        )

    def test_transfer_legs_display_as_transfer_category(self) -> None:
        destination = self.store.add_account("Savings", "Bank", 0)
        group = self.store.add_transfer(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.window.account_id,
                payee="Transfer",
                category_id=None,
                amount=-100,
            ),
            destination,
        )
        self.window.reload()
        transfer = next(
            row for row in self.window.model.rows if row.transfer_id == group
        )
        self.assertEqual(transfer.category_name, "Transfer")
        color = category_text_color(transfer, QColor("#ffffff"), False)
        self.assertEqual(color.name(), QColor(C.MUTED).name())

    def test_finish_edit_reveals_row_hidden_by_filters(self) -> None:
        target = self.window.model.rows[0]
        self.window.status_combo.setCurrentIndex(
            self.window.status_combo.findData("reconciled")
        )
        self.window._apply_filters()
        self.assertNotIn(
            target.id, [row.id for row in self.window.model.rows]
        )

        self.window._finish_selection_after_change([target.id])

        self.assertIsNone(self.window.status_combo.currentData())
        self.assertEqual(self.window._selected_ids(), [target.id])
        self.assertIn(target.id, [row.id for row in self.window.model.rows])

    def test_finish_edit_follows_transaction_to_another_account(self) -> None:
        destination = self.store.add_account("Savings", "Bank", 0)
        transaction_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=destination,
                payee="Moved",
                category_id=None,
                amount=-10,
            )
        )
        moved: list[tuple[int, int]] = []
        self.window.revealRequested.connect(
            lambda account_id, transaction: moved.append(
                (account_id, transaction)
            )
        )

        self.window._finish_selection_after_change([transaction_id])

        self.assertEqual(moved, [(destination, transaction_id)])

    def test_e_key_edits_the_selected_transaction(self) -> None:
        from contapy.widgets import ledger as ledger_module

        target = self.window.model.rows[0]
        self.window._select_ids([target.id])
        self.assertEqual(self.window.edit_key.key().toString(), "E")

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def draft(self) -> TransactionDraft:
                return TransactionDraft(
                    date=target.date,
                    account_id=target.account_id,
                    payee="Edited with E",
                    category_id=target.category_id,
                    amount=target.amount,
                )

        with mock.patch.object(ledger_module, "TransactionDialog", FakeDialog):
            self.window.edit_key.activated.emit()

        edited = self.store.transaction(target.id)
        assert edited is not None
        self.assertEqual(edited.payee, "Edited with E")
        self.assertEqual(self.window._selected_ids(), [target.id])

    def test_editing_keeps_the_saved_row_selected(self) -> None:
        from contapy.widgets import ledger as ledger_module

        target = self.window.model.rows[0]
        self.window._select_ids([target.id])
        self.window.changed.connect(self.window.reload)

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def draft(self) -> TransactionDraft:
                return TransactionDraft(
                    date=target.date,
                    account_id=target.account_id,
                    payee="Edited payee",
                    category_id=target.category_id,
                    amount=target.amount,
                )

        with mock.patch.object(ledger_module, "TransactionDialog", FakeDialog):
            self.window.edit_transaction()

        self.assertEqual(self.window._selected_ids(), [target.id])
        current = self.window.table.currentIndex()
        self.assertTrue(current.isValid())
        self.assertEqual(self.window.model.rows[current.row()].id, target.id)

    def test_editing_a_transfer_reselects_its_new_leg(self) -> None:
        from contapy.widgets import ledger as ledger_module

        destination = self.store.add_account("Savings", "Bank", 0)
        group = self.store.add_transfer(
            TransactionDraft(
                date=date(2020, 1, 1).isoformat(),
                account_id=self.window.account_id,
                payee="Transfer",
                category_id=None,
                amount=-100,
            ),
            destination,
        )
        account_id = self.window.account_id
        self.window.reload()
        leg = next(
            row
            for row in self.window.model.rows
            if row.transfer_id == group and row.account_id == account_id
        )
        self.window._select_ids([leg.id])
        self.window.changed.connect(self.window.reload)

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def draft(self) -> TransactionDraft:
                return TransactionDraft(
                    date=date(2020, 1, 1).isoformat(),
                    account_id=account_id,
                    payee="Transfer",
                    category_id=None,
                    amount=-150,
                    transfer_account_id=destination,
                    transfer_id=group,
                )

        with mock.patch.object(ledger_module, "TransactionDialog", FakeDialog):
            self.window.edit_transaction()

        selected = self.window._selected_rows()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].transfer_id, group)
        self.assertEqual(selected[0].account_id, self.window.account_id)
        self.assertAlmostEqual(selected[0].amount, -150)
        current = self.window.table.currentIndex()
        self.assertTrue(current.isValid())
        self.assertEqual(self.window.model.rows[current.row()].id, selected[0].id)

    def test_ledger_emits_activity_messages(self) -> None:
        messages: list[str] = []
        self.window.activity.connect(messages.append)
        ids = [row.id for row in self.window.model.rows]
        self.window._select_ids(ids)

        self.window._set_reconciled(True)
        self.assertIn(f"Reconciled {len(ids)} transaction(s)", messages)

        self.window.undo()
        self.assertTrue(any(message.startswith("Undid reconcile") for message in messages))

    def test_ledger_headers_sort_by_amount_and_keep_selection(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        self.window._select_ids([by_amount[-600.0]])
        header = self.window.table.horizontalHeader()
        self.assertTrue(header.sectionsClickable())
        self.assertTrue(header.isSortIndicatorShown())

        self.window._header_clicked(EXPENSE)
        self.assertEqual(
            [row.amount for row in self.window.model.rows],
            [-1_000.0, -600.0, -400.0],
        )
        self.assertEqual(self.window._selected_ids(), [by_amount[-600.0]])

        self.window._header_clicked(EXPENSE)
        self.assertEqual(
            [row.amount for row in self.window.model.rows],
            [-400.0, -600.0, -1_000.0],
        )
        self.assertEqual(self.window._selected_ids(), [by_amount[-600.0]])

    def test_copy_memo_uses_the_system_clipboard(self) -> None:
        target = self.window.model.rows[0]
        self.store.update_transaction(
            target.id,
            TransactionDraft(
                date=target.date,
                account_id=target.account_id,
                payee=target.payee,
                category_id=target.category_id,
                amount=target.amount,
                memo="Remember the receipt",
            ),
        )
        self.window.reload()
        self.window._select_ids([target.id])
        QApplication.clipboard().setText("")

        self.window.copy_memos()

        self.assertEqual(
            QApplication.clipboard().text(), "Remember the receipt"
        )

    def test_copy_amount_uses_thousands_separators(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        self.window._select_ids([by_amount[-1_000.0]])
        QApplication.clipboard().setText("")

        self.window.copy_amounts()

        self.assertEqual(QApplication.clipboard().text(), "-1,000.00")
        self.assertEqual(
            self.window.act_copy_amount.shortcut().toString(), "Ctrl+Shift+A"
        )

    def test_copy_and_paste_transaction_in_the_same_account(self) -> None:
        target = self.window.model.rows[0]
        before = {
            row.id for row in self.store.ledger_rows(self.window.account_id)
        }
        self.window._select_ids([target.id])

        self.window.copy_transactions()
        self.window.paste_transactions()

        after = {
            row.id for row in self.store.ledger_rows(self.window.account_id)
        }
        new_ids = after - before
        self.assertEqual(len(new_ids), 1)
        pasted = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }[next(iter(new_ids))]
        self.assertEqual(pasted.payee, target.payee)
        self.assertEqual(pasted.amount, target.amount)
        self.assertEqual(pasted.category_id, target.category_id)
        self.assertEqual(pasted.memo, target.memo)
        self.assertEqual(self.window._selected_ids(), list(new_ids))

    def test_copy_and_paste_transaction_into_another_account(self) -> None:
        other_account = self.store.add_account("Savings", "Bank", 0)
        other_window = LedgerWindow(self.store, other_account)
        self.addCleanup(other_window.close)
        target = self.window.model.rows[0]
        self.window._select_ids([target.id])

        self.window.copy_transactions()
        other_window.paste_transactions()

        rows = self.store.ledger_rows(other_account)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].payee, target.payee)
        self.assertEqual(rows[0].amount, target.amount)
        self.assertEqual(other_window._selected_ids(), [rows[0].id])

    def test_copy_and_paste_split_transaction_keeps_allocations(self) -> None:
        category_a = self.store.add_category("Copy A", "expense")
        category_b = self.store.add_category("Copy B", "expense")
        split_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.window.account_id,
                payee="Split copy",
                category_id=None,
                amount=-100,
                splits=[
                    SplitDraft(category_a, -60),
                    SplitDraft(category_b, -40),
                ],
            )
        )
        self.window.reload()
        self.window._select_ids([split_id])

        self.window.copy_transactions()
        self.window.paste_transactions()

        rows = [
            row
            for row in self.store.ledger_rows(self.window.account_id)
            if row.payee == "Split copy"
            and row.id != split_id
            and not row.is_split_child
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0].splits), 2)
        self.assertAlmostEqual(
            sum(split.amount for split in rows[0].splits), -100
        )

    def test_copy_shortcuts_are_ledger_scoped(self) -> None:
        self.assertEqual(self.window.act_copy.shortcut().toString(), "Ctrl+C")
        self.assertEqual(
            self.window.act_paste.shortcut().toString(), "Ctrl+V"
        )
        self.assertEqual(
            self.window.act_copy_memo.shortcut().toString(), "Ctrl+Shift+C"
        )
        self.assertIn(self.window.act_copy, self.window.table.actions())
        self.assertIn(self.window.act_paste, self.window.table.actions())
        self.assertIn(self.window.act_copy_memo, self.window.table.actions())

    def test_apply_rules_to_all_transactions_in_account(self) -> None:
        from contapy.widgets import ledger as ledger_module

        self.store.add_rule(
            Rule(
                name="Tag all test rows",
                search="Test",
                match_payee=True,
                assign_tags="all",
                tags_overwrite=True,
            )
        )

        with mock.patch.object(
            ledger_module.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window.apply_rules_to_all()

        rows = self.store.ledger_rows(self.window.account_id)
        self.assertTrue(rows)
        self.assertTrue(all(row.tags == "all" for row in rows))

    def test_apply_rules_to_selected_transactions_and_undo(self) -> None:
        from contapy.widgets import ledger as ledger_module

        self.store.add_rule(
            Rule(
                name="Tag test rows",
                search="Test",
                match_payee=True,
                assign_tags="auto",
                tags_overwrite=True,
            )
        )
        target = self.window.model.rows[0]
        self.window._select_ids([target.id])

        with mock.patch.object(
            ledger_module.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window.apply_rules_to_selected()

        row = self.store.transaction(target.id)
        assert row is not None
        self.assertEqual(row.tags, "auto")
        self.assertEqual(self.window._selected_ids(), [target.id])

        self.window.undo()
        restored = self.store.transaction(target.id)
        assert restored is not None
        self.assertEqual(restored.tags, "")

    def test_ctrl_z_undoes_a_flag_change(self) -> None:
        ids = [row.id for row in self.window.model.rows]
        self.window._select_ids(ids)

        self.window._set_cleared(False)
        changed = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in ids:
            self.assertFalse(changed[transaction_id].cleared)
        self.assertEqual(self.window.act_undo.text(), "Undo unclear")
        self.assertEqual(self.window.act_undo.shortcut().toString(), "Ctrl+Z")

        self.window.undo()

        restored = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in ids:
            self.assertTrue(restored[transaction_id].cleared)
        self.assertFalse(self.window.act_undo.isEnabled())

    def test_ctrl_z_undoes_a_deleted_transaction(self) -> None:
        from contapy.widgets import ledger as ledger_module

        target = self.window.model.rows[0]
        before = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }[target.id]
        self.window._select_ids([target.id])

        with mock.patch.object(
            ledger_module.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            self.window.delete_transaction()

        remaining = {
            row.id for row in self.store.ledger_rows(self.window.account_id)
        }
        self.assertNotIn(target.id, remaining)

        self.window.undo()

        restored = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }[target.id]
        self.assertEqual(restored.payee, before.payee)
        self.assertEqual(restored.amount, before.amount)
        self.assertEqual(restored.date, before.date)

    def test_ctrl_z_undoes_a_new_transaction(self) -> None:
        from contapy.widgets import ledger as ledger_module

        class FakeCombo:
            def findData(self, value) -> int:
                return -1

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, *args, **kwargs):
                self.account_combo = FakeCombo()

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def draft(self) -> TransactionDraft:
                return TransactionDraft(
                    date=date.today().isoformat(),
                    account_id=self.account_id,
                    payee="Undo me",
                    category_id=None,
                    amount=-12,
                )

        FakeDialog.account_id = self.window.account_id
        with mock.patch.object(ledger_module, "TransactionDialog", FakeDialog):
            self.window.add_transaction()

        created = [
            row
            for row in self.store.ledger_rows(self.window.account_id)
            if row.payee == "Undo me"
        ]
        self.assertEqual(len(created), 1)

        self.window.undo()

        remaining = [
            row
            for row in self.store.ledger_rows(self.window.account_id)
            if row.payee == "Undo me"
        ]
        self.assertEqual(remaining, [])

    def test_ctrl_z_undoes_a_bulk_edit(self) -> None:
        from contapy.widgets import ledger as ledger_module

        rows = self.window.model.rows
        selected_ids = [rows[0].id, rows[1].id]
        self.window._select_ids(selected_ids)
        original = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }

        class FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def changes(self) -> dict[str, object]:
                return {"payee": "Changed", "tags": "bulk"}

        with mock.patch.object(ledger_module, "BulkEditDialog", FakeDialog):
            self.window.edit_transaction()

        changed = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in selected_ids:
            self.assertEqual(changed[transaction_id].payee, "Changed")

        self.window.undo()

        restored = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in selected_ids:
            self.assertEqual(restored[transaction_id].payee, original[transaction_id].payee)
            self.assertEqual(restored[transaction_id].tags, original[transaction_id].tags)

    def test_undo_history_keeps_multiple_steps(self) -> None:
        ids = [row.id for row in self.window.model.rows]
        self.window._select_ids(ids)
        self.window._set_cleared(False)
        self.window.update()
        self.window._toggle_flag()

        self.assertIn("flag change", self.window.act_undo.text())
        self.window.undo()
        self.assertIn("unclear", self.window.act_undo.text())
        self.window.undo()
        self.assertFalse(self.window.act_undo.isEnabled())

    def test_alt_v_voids_highlighted_and_reconciles_selected(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        selected_ids = [by_amount[-400.0], by_amount[-600.0]]
        highlighted_id = by_amount[-1_000.0]
        self.window._select_ids(selected_ids)
        self.assertEqual(self.window._highlight_ids, {highlighted_id})

        self.window._void_highlighted()

        rows = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        self.assertTrue(rows[highlighted_id].voided)
        self.assertFalse(rows[highlighted_id].reconciled)
        for transaction_id in selected_ids:
            self.assertTrue(rows[transaction_id].cleared)
            self.assertTrue(rows[transaction_id].reconciled)
            self.assertFalse(rows[transaction_id].voided)

    def test_ctrl_z_undoes_alt_v(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        selected_ids = [by_amount[-400.0], by_amount[-600.0]]
        highlighted_id = by_amount[-1_000.0]
        self.window._select_ids(selected_ids)
        self.window._void_highlighted()

        self.window.undo()

        rows = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        self.assertFalse(rows[highlighted_id].voided)
        for transaction_id in selected_ids:
            self.assertFalse(rows[transaction_id].reconciled)
            self.assertTrue(rows[transaction_id].cleared)

    def test_hint_announces_alt_v_while_matches_are_highlighted(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        self.window._select_ids([by_amount[-400.0], by_amount[-600.0]])
        self.assertEqual(self.window._highlight_ids, {by_amount[-1_000.0]})
        hint = self.window.keyboard_hint.text()
        self.assertIn("Alt+V voids 1 highlighted row", hint)
        self.assertIn("reconciles 2 selected rows", hint)

        self.window.table.clearSelection()
        self.assertNotIn("Alt+V", self.window.keyboard_hint.text())

    def test_amount_search_filters_signed_amounts_and_ranges(self) -> None:
        self.window.search_edit.setText("amount:-400")
        self.assertEqual(
            [row.amount for row in self.window.model.rows], [-400.0]
        )

        self.window.search_edit.setText("amount:<-500")
        self.assertEqual(
            sorted(row.amount for row in self.window.model.rows),
            [-1_000.0, -600.0],
        )

        self.window.search_edit.setText("amount:-1000..-500")
        self.assertEqual(
            sorted(row.amount for row in self.window.model.rows),
            [-1_000.0, -600.0],
        )

        self.window.search_edit.setText("amount:<0 amount:>-1000")
        self.assertEqual(
            sorted(row.amount for row in self.window.model.rows),
            [-600.0, -400.0],
        )

        self.window.search_edit.setText("Test amount:<-500")
        self.assertEqual(
            sorted(row.amount for row in self.window.model.rows),
            [-1_000.0, -600.0],
        )

        self.window.search_edit.setText("Nope amount:<0")
        self.assertEqual(self.window.model.rows, [])

        self.window.search_edit.setText("amount:>")
        self.assertEqual(self.window.model.rows, [])

    def test_numeric_search_matches_magnitude_and_memo_text(self) -> None:
        for payee, amount, memo in (
            ("Income", 2_830.0, ""),
            ("Expense", -2_830.05, ""),
            ("Memo 2830", -50.0, "Amazon 2,830.05"),
            ("Large", -28_300.0, ""),
        ):
            self.store.add_transaction(
                TransactionDraft(
                    date=date.today().isoformat(),
                    account_id=self.window.account_id,
                    payee=payee,
                    category_id=None,
                    amount=amount,
                    memo=memo,
                )
            )
        self.window.reload()

        def visible_payees() -> set[str]:
            return {
                row.payee
                for row in self.window.model.rows
                if not row.is_split_child
            }

        self.window.search_edit.setText("2830")
        self.assertEqual(
            visible_payees(), {"Income", "Expense", "Memo 2830"}
        )

        self.window.search_edit.setText("-2830")
        self.assertEqual(
            visible_payees(), {"Income", "Expense", "Memo 2830"}
        )

        self.window.search_edit.setText("2830.05")
        self.assertEqual(visible_payees(), {"Expense", "Memo 2830"})

        self.window.search_edit.setText("28300")
        self.assertEqual(visible_payees(), {"Large"})

        self.window.search_edit.setText("2831")
        self.assertEqual(visible_payees(), set())

    def test_amount_search_includes_income_and_split_totals(self) -> None:
        self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.window.account_id,
                payee="Income",
                category_id=None,
                amount=2_500.0,
            )
        )
        category = self.store.ensure_category("Test : Split", "expense")
        split_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.window.account_id,
                payee="Split",
                category_id=None,
                amount=-100.0,
                splits=[
                    SplitDraft(category, -60.0),
                    SplitDraft(category, -40.0),
                ],
            )
        )
        self.window.reload()

        self.window.search_edit.setText("amount:>0")
        self.assertEqual(
            [row.amount for row in self.window.model.rows], [2_500.0]
        )

        self.window.search_edit.setText("amount:-100")
        parents = [
            row.id for row in self.window.model.rows if not row.is_split_child
        ]
        self.assertEqual(parents, [split_id])

    def test_apply_template_updates_selection_and_pushes_undo(self) -> None:
        self.assertFalse(self.window.act_apply_template.isEnabled())
        self.assertFalse(self.window.apply_template_btn.isEnabled())
        self.assertEqual(
            self.window.act_apply_template.shortcut().toString(), "Ctrl+T"
        )
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        selected_ids = [by_amount[-400.0], by_amount[-600.0]]
        untouched_id = by_amount[-1_000.0]
        self.window._select_ids(selected_ids)
        self.assertTrue(self.window.act_apply_template.isEnabled())
        self.assertTrue(self.window.apply_template_btn.isEnabled())

        template = Template(
            name="Batch",
            payee="Batch payee",
            payee_overwrite=True,
            tags="bulk",
            tags_overwrite=True,
            status="reconciled",
        )

        class FakeTemplateDialog:
            count = 0

            def __init__(self, store, parent=None, *, count=None) -> None:
                FakeTemplateDialog.count = count

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def template_values(self) -> Template:
                return template

        changed_emitted: list[bool] = []
        self.window.changed.connect(lambda: changed_emitted.append(True))
        with mock.patch(
            "contapy.widgets.ledger.TemplatesDialog", FakeTemplateDialog
        ):
            self.window.apply_template_to_selected()

        self.assertEqual(FakeTemplateDialog.count, 2)
        rows = {
            row.id: row for row in self.store.ledger_rows(self.window.account_id)
        }
        for transaction_id in selected_ids:
            self.assertEqual(rows[transaction_id].payee, "Batch payee")
            self.assertEqual(rows[transaction_id].tags, "bulk")
            self.assertTrue(rows[transaction_id].cleared)
            self.assertTrue(rows[transaction_id].reconciled)
        self.assertEqual(rows[untouched_id].payee, "Test")
        self.assertEqual(rows[untouched_id].tags, "")
        self.assertFalse(rows[untouched_id].reconciled)
        self.assertEqual(
            self.window.act_undo.text(), "Undo apply template"
        )
        self.assertEqual(set(self.window._selected_ids()), set(selected_ids))
        self.assertTrue(changed_emitted)


    def test_remembers_last_edited_transaction_when_reopening(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        edited_id = by_amount[-600.0]

        class FakeEditDialog:
            DialogCode = QDialog.DialogCode

            def __init__(
                self,
                store,
                accounts,
                categories,
                draft=None,
                title="",
                parent=None,
            ) -> None:
                self._draft = draft

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def draft(self):
                self._draft.memo = "Edited memo"
                return self._draft

        self.window._select_ids([edited_id])
        with mock.patch(
            "contapy.widgets.ledger.TransactionDialog", FakeEditDialog
        ):
            self.window.edit_transaction()

        key = f"ledger_last_transaction:{self.window.account_id}"
        self.assertEqual(self.store.get_setting(key), str(edited_id))

        reopened = LedgerWindow(self.store, self.window.account_id)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened._selected_ids(), [edited_id])

        reopened.status_combo.setCurrentIndex(
            reopened.status_combo.findData("voided")
        )
        self.assertEqual(reopened._selected_ids(), [])
        self.assertTrue(reopened._restore_last_transaction())
        self.assertIsNone(reopened.status_combo.currentData())
        self.assertEqual(reopened._selected_ids(), [edited_id])

        reopened.table.clearSelection()
        reopened.focus_table()
        self.assertEqual(reopened._selected_ids(), [edited_id])


class ExactAmountTests(unittest.TestCase):
    def test_picks_only_the_exact_match_not_a_near_amount(self) -> None:
        rows = [row(1, -400), row(2, -600), row(3, -1_000), row(4, -990), row(5, 50)]
        self.assertEqual(
            exact_amount_ids(rows, {1, 2}, -1_000),
            [3],
        )

    def test_returns_every_exact_match(self) -> None:
        rows = [row(1, -400), row(2, -600), row(3, -1_000), row(4, -1_000)]
        self.assertEqual(
            exact_amount_ids(rows, {1, 2}, -1_000),
            [3, 4],
        )

    def test_ignores_selected_voided_and_near_amounts(self) -> None:
        rows = [
            row(1, -400),
            row(2, -600),
            row(3, -1_000, voided=True),
            row(4, -1_000),
            row(5, -1_000),
            row(6, -999.99),
        ]
        self.assertEqual(
            exact_amount_ids(rows, {1, 2, 5}, -1_000),
            [4],
        )

    def test_no_exact_match_means_no_highlight(self) -> None:
        rows = [row(1, -400), row(2, -600), row(3, -999.99)]
        self.assertEqual(exact_amount_ids(rows, {1, 2}, -1_000), [])


if __name__ == "__main__":
    unittest.main()
