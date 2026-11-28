"""Tests for payee registration, CRUD and safe deletion."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QDialog

from contapy.db import DataStore
from contapy.models import TransactionDraft
from contapy.theme import apply_theme
from contapy.widgets.payees import (
    PayeeEditDialog,
    PayeeReassignDialog,
    PayeesDialog,
)


class PayeeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(Path(self.tmp.name) / "payees.db", seed=False)
        self.addCleanup(self.store.close)
        self.account = self.store.add_account("Checking", "Bank", 0)

    def add_transaction(self, payee: str, amount: float = -10) -> int:
        return self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.account,
                payee=payee,
                category_id=None,
                amount=amount,
            )
        )

    def test_existing_transaction_payees_are_registered(self) -> None:
        self.add_transaction("Coffee Shop")
        self.store.add_scheduled(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.account,
                payee="Landlord",
                category_id=None,
                amount=-500,
            )
        )

        names = self.store.payees()
        self.assertIn("Coffee Shop", names)
        self.assertIn("Landlord", names)
        records = {payee.name: payee for payee in self.store.payee_records()}
        self.assertEqual(records["Coffee Shop"].transaction_count, 1)
        self.assertEqual(records["Landlord"].transaction_count, 1)

    def test_add_and_update_payee_with_notes(self) -> None:
        payee_id = self.store.add_payee("Cafe", "Morning coffee")
        payee = self.store.payee(payee_id)
        assert payee is not None
        self.assertEqual(payee.notes, "Morning coffee")

        self.store.update_payee(payee_id, "Coffee Shop", "Updated note")
        payee = self.store.payee(payee_id)
        assert payee is not None
        self.assertEqual(payee.name, "Coffee Shop")
        self.assertEqual(payee.notes, "Updated note")

    def test_names_are_unique_case_insensitively(self) -> None:
        self.store.add_payee("Cafe")
        with self.assertRaises(ValueError):
            self.store.add_payee("cafe")

    def test_renaming_updates_transactions_and_scheduled_items(self) -> None:
        payee_id = self.store.add_payee("Old Name")
        self.add_transaction("Old Name")
        self.store.add_scheduled(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.account,
                payee="Old Name",
                category_id=None,
                amount=-100,
            )
        )

        self.store.update_payee(payee_id, "New Name")

        self.assertEqual(self.store.payees(), ["New Name"])
        self.assertEqual(
            [row.payee for row in self.store.ledger_rows(self.account)],
            ["New Name"],
        )
        self.assertEqual(
            [item.payee for item in self.store.scheduled_items()],
            ["New Name"],
        )

    def test_delete_without_transactions_is_direct(self) -> None:
        payee_id = self.store.add_payee("Temporary")
        self.assertEqual(self.store.delete_payee(payee_id), 0)
        self.assertIsNone(self.store.payee(payee_id))

    def test_delete_with_transactions_requires_replacement(self) -> None:
        payee_id = self.store.add_payee("Old Payee")
        self.add_transaction("Old Payee")
        with self.assertRaises(ValueError):
            self.store.delete_payee(payee_id)

    def test_delete_reassigns_transactions_and_scheduled_items(self) -> None:
        old_id = self.store.add_payee("Old Payee")
        replacement_id = self.store.add_payee("New Payee")
        self.add_transaction("Old Payee")
        self.store.add_scheduled(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.account,
                payee="Old Payee",
                category_id=None,
                amount=-100,
            )
        )

        usage = self.store.delete_payee(old_id, replacement_id)

        self.assertEqual(usage, 2)
        self.assertIsNone(self.store.payee(old_id))
        self.assertEqual(
            [row.payee for row in self.store.ledger_rows(self.account)],
            ["New Payee"],
        )
        self.assertEqual(
            [item.payee for item in self.store.scheduled_items()],
            ["New Payee"],
        )
        replacement = self.store.payee(replacement_id)
        assert replacement is not None
        self.assertEqual(replacement.transaction_count, 2)


class PayeesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(Path(self.tmp.name) / "dialog.db", seed=False)
        self.addCleanup(self.store.close)
        self.account = self.store.add_account("Checking", "Bank", 0)
        self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=self.account,
                payee="Coffee Shop",
                category_id=None,
                amount=-10,
            )
        )
        self.store.add_payee("Empty Payee", "No transactions")

    def test_dialog_lists_payees_and_counts(self) -> None:
        dialog = PayeesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        rows = {
            dialog.table.item(row, 0).text(): dialog.table.item(row, 2).text()
            for row in range(dialog.table.rowCount())
        }
        self.assertEqual(rows["Coffee Shop"], "1")
        self.assertEqual(rows["Empty Payee"], "0")

    def test_edit_dialog_prefills_values(self) -> None:
        payee = self.store.payee_by_name("Empty Payee")
        assert payee is not None
        dialog = PayeeEditDialog(self.store, payee)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.name_edit.text(), "Empty Payee")
        self.assertEqual(dialog.notes_edit.text(), "No transactions")
        self.assertEqual(dialog.values(), ("Empty Payee", "No transactions"))

    def test_dialog_delete_reassigns_through_the_prompt(self) -> None:
        payee = self.store.payee_by_name("Coffee Shop")
        replacement = self.store.payee_by_name("Empty Payee")
        assert payee is not None and replacement is not None
        dialog = PayeesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        for row in range(dialog.table.rowCount()):
            if dialog.table.item(row, 0).text() == "Coffee Shop":
                dialog.table.selectRow(row)
                break

        class FakeReassignDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                return QDialog.DialogCode.Accepted

            def replacement_id(self):
                return replacement.id

        with mock.patch(
            "contapy.widgets.payees.PayeeReassignDialog",
            FakeReassignDialog,
        ):
            dialog.delete_payee()

        self.assertIsNone(self.store.payee_by_name("Coffee Shop"))
        rows = self.store.ledger_rows(self.account)
        self.assertEqual([row.payee for row in rows], ["Empty Payee"])
        self.assertEqual(
            self.store.payee_by_name("Empty Payee").transaction_count, 1
        )

    def test_reassign_dialog_lists_other_payees(self) -> None:
        payee = self.store.payee_by_name("Coffee Shop")
        assert payee is not None
        replacements = [
            candidate
            for candidate in self.store.payee_records()
            if candidate.id != payee.id
        ]
        dialog = PayeeReassignDialog(payee, replacements)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(
            [dialog.replacement_combo.itemText(index)
             for index in range(dialog.replacement_combo.count())],
            ["Empty Payee"],
        )
        self.assertEqual(dialog.replacement_id(), replacements[0].id)
