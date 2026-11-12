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
from contapy.models import TransactionDraft, TransactionRow
from contapy.theme import C
from contapy.widgets.dialogs import BulkEditDialog, DateRangeDialog
from contapy.widgets.ledger import (
    CUSTOM_RANGE,
    HEADERS,
    LedgerWindow,
    category_text_color,
    closest_amount_ids,
    date_bounds,
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


class LedgerHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
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


class ClosestAmountTests(unittest.TestCase):
    def test_picks_the_unselected_amount_closest_to_the_total(self) -> None:
        rows = [row(1, -400), row(2, -600), row(3, -1_000), row(4, -990), row(5, 50)]
        self.assertEqual(
            closest_amount_ids(rows, {1, 2}, -1_000),
            [3],
        )

    def test_returns_every_tie_at_the_closest_distance(self) -> None:
        rows = [row(1, -400), row(2, -600), row(3, -1_000), row(4, -1_000)]
        self.assertEqual(
            closest_amount_ids(rows, {1, 2}, -1_000),
            [3, 4],
        )

    def test_ignores_selected_and_voided_rows(self) -> None:
        rows = [
            row(1, -400),
            row(2, -600),
            row(3, -1_000, voided=True),
            row(4, -900),
        ]
        self.assertEqual(closest_amount_ids(rows, {1, 2}, -1_000), [4])

    def test_no_candidates_means_no_highlight(self) -> None:
        rows = [row(1, -400, voided=True), row(2, -600)]
        self.assertEqual(closest_amount_ids(rows, {2}, -600), [])


if __name__ == "__main__":
    unittest.main()
