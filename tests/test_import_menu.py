"""Tests for the Ctrl+I import-source menu."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from contapy.db import DataStore, import_backup_dir
from contapy.main_window import MainWindow
from contapy.models import TransactionDraft
from contapy.theme import apply_theme


class ImportMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_ctrl_i_opens_the_import_source_menu(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "menu.db", seed=False)
        window = MainWindow(store)
        try:
            self.assertEqual(window.act_import.shortcut().toString(), "Ctrl+I")
            self.assertEqual(
                [
                    action.text()
                    for action in window.import_menu.actions()
                    if not action.isSeparator()
                ],
                [
                    "Import CSV…",
                    "From Airbnb…",
                    "From Airbnb (transactions)…",
                    "From Booking…",
                    "From Banamex…",
                    "Revert Last Import…",
                ],
            )
            self.assertFalse(window.act_revert_import.isEnabled())

            file_menu = next(
                action.menu()
                for action in window.menuBar().actions()
                if action.text() == "File"
            )
            self.assertIn(
                window.import_menu,
                [action.menu() for action in file_menu.actions()],
            )

            with mock.patch.object(window.import_menu, "popup") as popup:
                window.act_import.trigger()
            popup.assert_called_once()
        finally:
            window.close()

    def test_import_writes_a_backup_and_records_the_last_import(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "import.db", seed=False)
        account = store.add_account("Checking", "Bank", 0)
        source = Path(tmp.name) / "statement.csv"
        source.write_text(
            "Fecha,Importe,Memo\n2026-11-18,10.00,Test import\n",
            encoding="utf-8",
        )
        window = MainWindow(store)

        class FakeImportDialog:
            def __init__(
                self,
                store,
                accounts,
                path,
                default_account_id=None,
                parent=None,
            ) -> None:
                self._account_id = accounts[0].id

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.DialogCode.Accepted

            def account_id(self):
                return self._account_id

            def memo_as_payee(self):
                return False

            def current_mapping(self):
                return None

            def skip_row_indexes(self):
                return set()

            def apply_rules(self):
                return False

        try:
            with mock.patch(
                "contapy.main_window.CsvImportDialog", FakeImportDialog
            ):
                window._import_csv_path(source)

            backups = list(import_backup_dir(store.path).glob("*.db"))
            self.assertEqual(len(backups), 1)
            record = store.last_import()
            assert record is not None
            self.assertEqual(record["backup"], str(backups[0]))
            self.assertEqual(len(record["ids"]), 1)
            imported_id = record["ids"][0]
            row = store.transaction(imported_id)
            assert row is not None
            self.assertEqual(row.account_id, account)

            with mock.patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                window.revert_last_import()
            self.assertIsNone(store.transaction(imported_id))
            self.assertIsNone(store.last_import())
            self.assertEqual(
                len(list(import_backup_dir(store.path).glob("*.db"))), 2
            )
        finally:
            window.close()

    def test_revert_last_import_action_is_enabled_and_removes_rows(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "revert.db", seed=False)
        account = store.add_account("Checking", "Bank", 0)
        transaction_id = store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account,
                payee="Imported",
                category_id=None,
                amount=-10.0,
            )
        )
        store.record_last_import("statement.csv", [transaction_id])
        window = MainWindow(store)
        try:
            self.assertTrue(window.act_revert_import.isEnabled())
            with mock.patch.object(
                QMessageBox,
                "question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                window.revert_last_import()

            self.assertIsNone(store.transaction(transaction_id))
            self.assertIsNone(store.last_import())
            self.assertFalse(window.act_revert_import.isEnabled())
            self.assertEqual(
                len(list(import_backup_dir(store.path).glob("*.db"))), 1
            )
        finally:
            window.close()
