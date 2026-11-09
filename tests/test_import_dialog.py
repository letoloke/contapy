"""Headless tests for the per-row import selection."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.theme import apply_theme
from contapy.widgets.import_dialog import CsvImportDialog


class ImportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.store = DataStore(self.folder / "test.db")
        self.account = self.store.accounts()[0]

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def write_csv(self, name: str, rows: list[str]) -> Path:
        path = self.folder / name
        path.write_text(
            "Fecha,Importe,Memo,Beneficiario\n" + "\n".join(rows) + "\n",
            encoding="utf-8",
        )
        return path

    def dialog(self, path: Path) -> CsvImportDialog:
        return CsvImportDialog(
            self.store,
            self.store.accounts(),
            path,
            self.account.id,
        )

    def test_duplicates_start_unchecked_and_can_be_selected(self) -> None:
        seed = self.write_csv("seed.csv", ["2031-01-01,10,Existing payment,"])
        self.store.import_csv(seed, account_id=self.account.id)
        target = self.write_csv(
            "target.csv",
            [
                "2031-01-01,10,Existing payment,",
                "2031-01-02,20,Fresh payment,Guest",
            ],
        )
        dialog = self.dialog(target)

        duplicate = dialog.preview.item(0, 0)
        fresh = dialog.preview.item(1, 0)
        self.assertEqual(duplicate.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(fresh.checkState(), Qt.CheckState.Checked)
        self.assertEqual(dialog.skip_row_indexes(), {0})
        self.assertIn("1 duplicate(s) not selected", dialog.status_label.text())

        duplicate.setCheckState(Qt.CheckState.Checked)
        self.assertEqual(dialog.skip_row_indexes(), set())
        self.assertIn("1 duplicate(s) included", dialog.status_label.text())

        for row in range(dialog.preview.rowCount()):
            dialog.preview.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.skip_row_indexes(), {0, 1})
        self.assertFalse(dialog.import_button.isEnabled())
        dialog.deleteLater()

    def test_unreadable_rows_are_not_marked_as_skipped(self) -> None:
        target = self.write_csv(
            "target.csv",
            [
                "not-a-date,10,Bad date,",
                "2031-02-01,20,Good row,",
            ],
        )
        dialog = self.dialog(target)

        self.assertEqual(dialog.preview.rowCount(), 1)
        self.assertEqual(dialog.skip_row_indexes(), set())
        self.assertIn("1 unreadable row(s)", dialog.status_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
