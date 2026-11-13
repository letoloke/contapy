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

    def test_preview_sorts_by_amount_and_keeps_selection(self) -> None:
        target = self.write_csv(
            "sort.csv",
            [
                "2031-01-01,-10,Small,",
                "2031-01-02,300,Large,",
                "2031-01-03,50,Medium,",
            ],
        )
        dialog = self.dialog(target)
        dialog.preview.item(1, 0).setCheckState(Qt.CheckState.Unchecked)

        dialog._header_clicked(4)
        self.assertEqual(
            [
                dialog.preview.item(row, 2).text()
                for row in range(dialog.preview.rowCount())
            ],
            ["Large", "Medium", "Small"],
        )
        self.assertEqual(dialog.skip_row_indexes(), {1})

        dialog._header_clicked(4)
        self.assertEqual(
            [
                dialog.preview.item(row, 2).text()
                for row in range(dialog.preview.rowCount())
            ],
            ["Small", "Medium", "Large"],
        )
        self.assertEqual(dialog.skip_row_indexes(), {1})
        dialog.deleteLater()

    def test_preview_sorts_dates_chronologically(self) -> None:
        target = self.write_csv(
            "dates.csv",
            [
                "2031-01-01,10,Oldest,",
                "2031-03-01,20,Newest,",
                "2031-02-01,30,Middle,",
            ],
        )
        dialog = self.dialog(target)
        dialog._header_clicked(1)
        self.assertEqual(
            [
                dialog.preview.item(row, 2).text()
                for row in range(dialog.preview.rowCount())
            ],
            ["Newest", "Middle", "Oldest"],
        )
        dialog.deleteLater()

    def test_automatic_rules_apply_by_default_and_can_be_disabled(self) -> None:
        target = self.write_csv("target.csv", ["2031-03-01,20,Fresh row,"])
        dialog = self.dialog(target)
        self.assertTrue(dialog.apply_rules())
        self.assertIn("assignment rules", dialog.rules_check.text().lower())

        dialog.rules_check.setChecked(False)
        self.assertFalse(dialog.apply_rules())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
