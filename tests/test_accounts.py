"""Tests for the responsive account-sidebar columns."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.widgets.accounts import (
    NAME_LEFT,
    RIGHT_PAD,
    VALUE_WIDTH,
    AccountRow,
    _required_name_width,
    _visible_value_columns,
)


def rows(*names: str) -> list[AccountRow]:
    return [AccountRow(kind="account", name=name) for name in names]


class AccountColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def assert_names_fit(self, width: int, account_rows: list[AccountRow]) -> None:
        columns = _visible_value_columns(width, account_rows)
        room = width - NAME_LEFT - RIGHT_PAD - len(columns) * VALUE_WIDTH
        self.assertGreaterEqual(room, _required_name_width(account_rows))

    def test_short_names_keep_all_balance_columns(self) -> None:
        account_rows = rows("Checking", "Savings", "Cash", "Credit card")
        columns = _visible_value_columns(615, account_rows)
        self.assertEqual(columns, [0, 1, 2, 3])
        self.assert_names_fit(615, account_rows)

    def test_long_names_drop_columns_instead_of_eliding(self) -> None:
        account_rows = rows("Banco Nacional de México Cuenta de Nómina")
        columns = _visible_value_columns(615, account_rows)
        self.assertLess(len(columns), 4)
        self.assert_names_fit(615, account_rows)

    def test_narrow_panel_uses_the_whole_width_for_names(self) -> None:
        account_rows = rows("Checking", "Savings")
        columns = _visible_value_columns(300, account_rows)
        self.assertEqual(columns, [])
        self.assert_names_fit(300, account_rows)

    def test_today_and_cleared_survive_longest(self) -> None:
        account_rows = rows("Checking", "Savings")
        self.assertEqual(_visible_value_columns(450, account_rows), [1, 2])
