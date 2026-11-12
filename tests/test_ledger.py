"""Tests for the ledger's date filters and amount highlighting."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.models import TransactionDraft, TransactionRow
from contapy.widgets.dialogs import DateRangeDialog
from contapy.widgets.ledger import (
    CUSTOM_RANGE,
    HEADERS,
    LedgerWindow,
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

    def test_hint_announces_alt_v_while_matches_are_highlighted(self) -> None:
        by_amount = {row.amount: row.id for row in self.window.model.rows}
        self.window._select_ids([by_amount[-400.0], by_amount[-600.0]])
        self.assertEqual(self.window._highlight_ids, {by_amount[-1_000.0]})
        self.assertIn("Alt+V voids 1 highlighted row", self.window.keyboard_hint.text())

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
