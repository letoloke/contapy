"""Tests for the ledger's date filters and amount highlighting."""

from __future__ import annotations

import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.models import TransactionRow
from contapy.widgets.dialogs import DateRangeDialog
from contapy.widgets.ledger import CUSTOM_RANGE, closest_amount_ids, date_bounds


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
