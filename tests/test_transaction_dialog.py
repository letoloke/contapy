"""Tests for transaction-dialog transfer direction and account handling."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.widgets.dialogs import TransactionDialog


class TransactionDialogTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(Path(self.tmp.name) / "dialog.db", seed=False)
        self.addCleanup(self.store.close)
        self.checking = self.store.add_account("Checking", "Bank", 0)
        self.savings = self.store.add_account("Savings", "Bank", 0)
        self.dialog = TransactionDialog(
            self.store, self.store.accounts(), self.store.categories()
        )
        self.addCleanup(self.dialog.deleteLater)

    def select_account(self, account_id: int) -> None:
        index = self.dialog.account_combo.findData(account_id)
        self.dialog.account_combo.setCurrentIndex(index)

    def test_income_to_transfer_makes_the_income_account_receive(self) -> None:
        self.dialog._set_type("income")
        self.select_account(self.checking)
        self.dialog.amount_spin.setValue(250.0)

        self.dialog._set_type("transfer")

        self.assertEqual(
            self.dialog.account_combo.currentData(), self.savings
        )
        self.assertEqual(
            self.dialog.to_account_combo.currentData(), self.checking
        )

        self.dialog._save()
        draft = self.dialog.draft()
        assert draft is not None
        self.assertEqual(draft.account_id, self.savings)
        self.assertEqual(draft.transfer_account_id, self.checking)

        group = self.store.add_transfer(draft, draft.transfer_account_id)
        legs = self.store.transfer_legs(group)
        checking_leg = next(
            row for row in legs if row.account_id == self.checking
        )
        savings_leg = next(
            row for row in legs if row.account_id == self.savings
        )
        self.assertEqual(checking_leg.amount, 250.0)
        self.assertEqual(savings_leg.amount, -250.0)

    def test_expense_to_transfer_keeps_the_expense_account_as_source(self) -> None:
        self.dialog._set_type("expense")
        self.select_account(self.checking)
        self.dialog.amount_spin.setValue(250.0)

        self.dialog._set_type("transfer")

        self.assertEqual(
            self.dialog.account_combo.currentData(), self.checking
        )
        self.assertEqual(
            self.dialog.to_account_combo.currentData(), self.savings
        )

        self.dialog._save()
        draft = self.dialog.draft()
        assert draft is not None
        self.assertEqual(draft.account_id, self.checking)
        self.assertEqual(draft.transfer_account_id, self.savings)
        self.assertEqual(draft.amount, -250.0)

    def test_leaving_transfer_restores_the_original_income_account(self) -> None:
        self.dialog._set_type("income")
        self.select_account(self.checking)
        self.dialog.amount_spin.setValue(250.0)
        self.dialog._set_type("transfer")

        self.dialog._set_type("income")

        self.assertEqual(
            self.dialog.account_combo.currentData(), self.checking
        )
        self.assertTrue(self.dialog.to_account_row.isHidden())


if __name__ == "__main__":
    unittest.main()
