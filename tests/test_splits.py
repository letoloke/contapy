"""Tests for split transactions across storage, reports and the ledger."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from contapy.db import DataStore
from contapy.models import SplitDraft, TransactionDraft
from contapy.widgets.dialogs import SplitDialog, TransactionDialog
from contapy.widgets.ledger import LedgerWindow


class SplitStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(Path(self.tmp.name) / "splits.db", seed=False)
        self.addCleanup(self.store.close)
        self.account = self.store.add_account("Checking", "Bank", 0)
        self.electronics = self.store.add_category("Electronics", "expense")
        self.home = self.store.add_category("Home", "expense")
        self.taxes = self.store.add_category("Taxes", "expense")
        self.today = date.today().isoformat()

    def add_split(
        self,
        amount: float = -1_000.0,
        splits: list[SplitDraft] | None = None,
    ) -> int:
        return self.store.add_transaction(
            TransactionDraft(
                date=self.today,
                account_id=self.account,
                payee="Amazon",
                category_id=None,
                amount=amount,
                memo="Order",
                tags="online",
                splits=splits
                or [
                    SplitDraft(self.electronics, -600, "Dock", "work"),
                    SplitDraft(self.home, -400, "Lamp", "home"),
                ],
            )
        )

    def test_add_split_creates_parent_and_allocation_rows(self) -> None:
        transaction_id = self.add_split()

        parent = self.store.transaction(transaction_id)
        self.assertIsNotNone(parent)
        assert parent is not None
        self.assertIsNone(parent.category_id)
        self.assertEqual(parent.category_name, "Split · 2 parts")
        self.assertEqual(parent.split_count, 2)
        self.assertEqual(
            [split.category_name for split in parent.splits],
            ["Electronics", "Home"],
        )

        rows = self.store.ledger_rows(self.account)
        self.assertEqual(len(rows), 3)
        self.assertFalse(rows[0].is_split_child)
        self.assertEqual(rows[0].amount, -1_000)
        self.assertEqual(rows[0].splits[0].category_id, self.electronics)
        children = [row for row in rows if row.is_split_child]
        self.assertEqual([child.category_name for child in children], ["Electronics", "Home"])
        self.assertEqual([child.split_parent_id for child in children], [transaction_id, transaction_id])
        self.assertAlmostEqual(sum(child.amount for child in children), -1_000)
        self.assertAlmostEqual(
            self.store.balances()[self.account].today, -1_000
        )

    def test_update_replaces_split_allocations(self) -> None:
        transaction_id = self.add_split()
        self.store.update_transaction(
            transaction_id,
            TransactionDraft(
                date=self.today,
                account_id=self.account,
                payee="Amazon",
                category_id=None,
                amount=-1_000,
                splits=[
                    SplitDraft(self.taxes, -250, "IVA"),
                    SplitDraft(self.electronics, -750, "Dock"),
                ],
            ),
        )

        splits = self.store.splits_for(transaction_id)
        self.assertEqual(len(splits), 2)
        self.assertEqual(splits[0].category_id, self.taxes)
        self.assertEqual(splits[1].category_id, self.electronics)
        self.assertAlmostEqual(sum(split.amount for split in splits), -1_000)

    def test_delete_removes_split_allocations(self) -> None:
        transaction_id = self.add_split()
        self.store.delete_transaction(transaction_id)
        self.assertEqual(self.store.splits_for(transaction_id), [])
        self.assertEqual(self.store.ledger_rows(self.account), [])

    def test_reports_budgets_and_bars_use_split_lines(self) -> None:
        self.add_split()
        self.store.add_transaction(
            TransactionDraft(
                date=self.today,
                account_id=self.account,
                payee="Cables",
                category_id=self.electronics,
                amount=-100,
            )
        )
        self.store.set_budget(self.electronics, 1_000)
        self.store.set_budget(self.home, 500)

        start = end = date.today()
        report = {row.label: row for row in self.store.report_rows(start, end)}
        self.assertEqual(report["Electronics"].expense, -700)
        self.assertEqual(report["Home"].expense, -400)
        self.assertNotIn("Split · 2 parts", report)

        budgets = {
            status.category_name: status
            for status in self.store.budget_report(start)
        }
        self.assertEqual(budgets["Electronics"].spent, 700)
        self.assertEqual(budgets["Home"].spent, 400)

        slices, total = self.store.spend_by_category(start, end)
        amounts = {item.name: item.amount for item in slices}
        self.assertEqual(amounts, {"Electronics": 700, "Home": 400})
        self.assertEqual(total, 1_100)

        cashflow = self.store.monthly_cashflow(1)
        self.assertEqual(cashflow[-1].expense, 1_100)

        category_rows = self.store.category_transactions(self.electronics)
        self.assertEqual(len(category_rows), 2)
        self.assertAlmostEqual(
            sum(row.amount for row in category_rows), -700
        )

    def test_income_split_rolls_up_as_income(self) -> None:
        salary = self.store.add_category("Salary", "income")
        bonus = self.store.add_category("Bonus", "income")
        self.store.add_transaction(
            TransactionDraft(
                date=self.today,
                account_id=self.account,
                payee="Employer",
                category_id=None,
                amount=1_000,
                splits=[
                    SplitDraft(salary, 600),
                    SplitDraft(bonus, 400),
                ],
            )
        )

        start = end = date.today()
        report = {
            row.label: row for row in self.store.report_rows(start, end, kind="income")
        }
        self.assertEqual(report["Salary"].income, 600)
        self.assertEqual(report["Bonus"].income, 400)
        self.assertNotIn("Split · 2 parts", report)

        slices, total = self.store.category_slices(start, end, kind="income")
        self.assertEqual({item.name: item.amount for item in slices}, {"Salary": 600, "Bonus": 400})
        self.assertEqual(total, 1_000)

        cashflow = self.store.monthly_cashflow(1)
        self.assertEqual(cashflow[-1].income, 1_000)

    def test_snapshot_restores_splits(self) -> None:
        transaction_id = self.add_split()
        before = self.store.snapshot_transactions([transaction_id])
        splits_before = self.store.snapshot_splits([transaction_id])

        self.store.update_transaction(
            transaction_id,
            TransactionDraft(
                date=self.today,
                account_id=self.account,
                payee="Amazon",
                category_id=None,
                amount=-1_000,
                splits=[SplitDraft(self.taxes, -1_000, "IVA")],
            ),
        )
        self.assertEqual(len(self.store.splits_for(transaction_id)), 1)

        self.store.restore_transactions(
            before, [transaction_id], splits_before
        )

        restored = self.store.splits_for(transaction_id)
        self.assertEqual(len(restored), 2)
        self.assertEqual(restored[0].category_id, self.electronics)
        self.assertEqual(restored[1].category_id, self.home)


class SplitDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(Path(self.tmp.name) / "dialog.db", seed=False)
        self.addCleanup(self.store.close)
        self.account = self.store.add_account("Checking", "Bank", 0)
        self.electronics = self.store.add_category("Electronics", "expense")
        self.home = self.store.add_category("Home", "expense")
        self.categories = self.store.categories()

    def test_split_dialog_requires_a_balanced_category_allocation(self) -> None:
        dialog = SplitDialog(
            self.store,
            self.categories,
            1_000,
            [
                SplitDraft(self.electronics, 600),
                SplitDraft(self.home, 400),
            ],
        )
        self.addCleanup(dialog.deleteLater)
        self.assertIsNone(dialog._validation_error())

        dialog.rows[0].amount_spin.setValue(500)
        self.assertIn("split total", dialog._validation_error())

        dialog.rows[0].amount_spin.setValue(600)
        dialog.accept()
        self.assertEqual(
            [split.category_id for split in dialog.splits()],
            [self.electronics, self.home],
        )

    def test_split_dialog_adds_removes_and_distributes(self) -> None:
        dialog = SplitDialog(self.store, self.categories, 1_000)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(len(dialog.rows), 2)

        row = dialog.add_row()
        self.assertEqual(len(dialog.rows), 3)
        dialog.remove_row(row)
        self.assertEqual(len(dialog.rows), 2)

        dialog.rows[0].amount_spin.setValue(500)
        dialog._distribute_remainder()
        self.assertAlmostEqual(
            sum(item.amount_spin.value() for item in dialog.rows), 1_000
        )

    def test_transaction_dialog_returns_signed_split_draft(self) -> None:
        draft = TransactionDraft(
            date=date.today().isoformat(),
            account_id=self.account,
            payee="Amazon",
            category_id=None,
            amount=-1_000,
            splits=[
                SplitDraft(self.electronics, -600, "Dock", "work"),
                SplitDraft(self.home, -400, "Lamp", "home"),
            ],
        )
        dialog = TransactionDialog(
            self.store, self.store.accounts(), self.categories, draft
        )
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(len(dialog._splits), 2)
        self.assertFalse(dialog.category_combo.isEnabled())
        self.assertIn("2 parts", dialog.split_summary.text())

        dialog._save()
        saved = dialog.draft()
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertIsNone(saved.category_id)
        self.assertEqual(len(saved.splits), 2)
        self.assertEqual(
            [split.amount for split in saved.splits], [-600, -400]
        )

        transaction_id = self.store.add_transaction(saved)
        self.assertEqual(len(self.store.splits_for(transaction_id)), 2)


class SplitLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_ledger_shows_parent_and_child_rows_and_selects_parent(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "ledger.db", seed=False)
        self.addCleanup(store.close)
        account = store.add_account("Checking", "Bank", 0)
        electronics = store.add_category("Electronics", "expense")
        home = store.add_category("Home", "expense")
        transaction_id = store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account,
                payee="Amazon",
                category_id=None,
                amount=-1_000,
                splits=[
                    SplitDraft(electronics, -600),
                    SplitDraft(home, -400),
                ],
            )
        )

        window = LedgerWindow(store, account)
        self.addCleanup(window.close)
        self.assertEqual(len(window.model.rows), 3)
        self.assertEqual(window.model.rows[0].split_count, 2)
        self.assertTrue(window.model.rows[1].is_split_child)

        child_index = next(
            index
            for index, row in enumerate(window.model.rows)
            if row.is_split_child
        )
        window.table.selectRow(child_index)
        selected = window._selected_rows()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].id, transaction_id)
        self.assertEqual(window.selected_label.text(), "1 selected")

    def test_search_matching_a_child_keeps_the_parent_group(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "search.db", seed=False)
        self.addCleanup(store.close)
        account = store.add_account("Checking", "Bank", 0)
        electronics = store.add_category("Electronics", "expense")
        home = store.add_category("Home", "expense")
        store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account,
                payee="Amazon",
                category_id=None,
                amount=-1_000,
                splits=[
                    SplitDraft(electronics, -600),
                    SplitDraft(home, -400),
                ],
            )
        )

        window = LedgerWindow(store, account)
        self.addCleanup(window.close)
        window.search_edit.setText("Home")
        self.assertEqual(len(window.model.rows), 3)
        self.assertFalse(window.model.rows[0].is_split_child)
        self.assertEqual(window.model.rows[0].split_count, 2)

        window.search_edit.setText("no such category")
        self.assertEqual(window.model.rows, [])

    def test_editing_and_deleting_a_split_can_be_undone(self) -> None:
        from contapy.widgets import ledger as ledger_module

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "undo.db", seed=False)
        self.addCleanup(store.close)
        account = store.add_account("Checking", "Bank", 0)
        electronics = store.add_category("Electronics", "expense")
        home = store.add_category("Home", "expense")
        taxes = store.add_category("Taxes", "expense")
        transaction_id = store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account,
                payee="Amazon",
                category_id=None,
                amount=-1_000,
                splits=[
                    SplitDraft(electronics, -600),
                    SplitDraft(home, -400),
                ],
            )
        )
        window = LedgerWindow(store, account)
        self.addCleanup(window.close)
        window._select_ids([transaction_id])

        class FakeDialog:
            DialogCode = QDialog.DialogCode

            def __init__(self, *args, **kwargs):
                pass

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def draft(self) -> TransactionDraft:
                return TransactionDraft(
                    date=date.today().isoformat(),
                    account_id=account,
                    payee="Amazon",
                    category_id=None,
                    amount=-1_000,
                    splits=[SplitDraft(taxes, -1_000)],
                )

        with mock.patch.object(ledger_module, "TransactionDialog", FakeDialog):
            window.edit_transaction()
        self.assertEqual(len(store.splits_for(transaction_id)), 1)

        window.undo()
        self.assertEqual(len(store.splits_for(transaction_id)), 2)

        window._select_ids([transaction_id])
        with mock.patch.object(
            ledger_module.QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            window.delete_transaction()
        self.assertEqual(store.splits_for(transaction_id), [])

        window.undo()
        self.assertEqual(len(store.splits_for(transaction_id)), 2)
