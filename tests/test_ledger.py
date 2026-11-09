"""Tests for the ledger's date filters."""

from __future__ import annotations

import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.widgets.dialogs import DateRangeDialog
from contapy.widgets.ledger import CUSTOM_RANGE, date_bounds


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


if __name__ == "__main__":
    unittest.main()
