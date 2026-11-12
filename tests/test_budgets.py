"""Tests for monthly budgets, reports and budget widgets."""

from __future__ import annotations

import calendar
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.db import DataStore, _shift_month_start
from contapy.models import BudgetStatus
from contapy.widgets.budgets import (
    BudgetProgress,
    BudgetRow,
    BudgetWindow,
    BudgetsPanel,
)


def insert_category(
    store: DataStore, name: str, kind: str = "expense", color: str = "#123456"
) -> int:
    cur = store.conn.execute(
        "INSERT INTO categories(name, kind, color, sort_order) VALUES (?,?,?,0)",
        (name, kind, color),
    )
    store.conn.commit()
    return int(cur.lastrowid)


def insert_transaction(
    store: DataStore,
    account_id: int,
    category_id: int,
    day: str,
    amount: float,
    *,
    voided: bool = False,
) -> None:
    store.conn.execute(
        "INSERT INTO transactions(account_id, date, payee, category_id, amount, "
        "cleared, reconciled, remind, flagged, voided) VALUES (?,?,?,?,?,1,0,0,0,?)",
        (account_id, day, "Test", category_id, amount, 1 if voided else 0),
    )
    store.conn.commit()


class BudgetStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "budgets.db", seed=False)
        cur = self.store.conn.execute(
            "INSERT INTO accounts(name, kind, opening, sort_order) VALUES ('Bank','Bank',0,0)"
        )
        self.account_id = int(cur.lastrowid)
        self.renta = insert_category(self.store, "renta")
        self.food = insert_category(self.store, "food")
        self.income = insert_category(self.store, "salary", kind="income")
        self.store.conn.commit()

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_set_budget_round_trips_and_zero_removes_it(self) -> None:
        self.store.set_budget(self.renta, 12_500.456)
        self.assertEqual(self.store.budget_amount(self.renta), 12_500.46)
        self.assertEqual(self.store.budgets(), {self.renta: 12_500.46})

        self.store.set_budget(self.renta, 0)
        self.assertEqual(self.store.budget_amount(self.renta), 0.0)
        self.assertEqual(self.store.budgets(), {})

    def test_report_only_includes_budgeted_expense_categories(self) -> None:
        self.store.set_budget(self.renta, 10_000)
        self.store.set_budget(self.income, 5_000)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-03", -2_500)
        insert_transaction(self.store, self.account_id, self.income, "2026-02-04", 8_000)

        report = self.store.budget_report(date(2026, 2, 14))
        self.assertEqual([status.category_name for status in report], ["renta"])

    def test_report_sums_current_month_and_excludes_voided(self) -> None:
        self.store.set_budget(self.renta, 10_000)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-01", -1_000)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-28", -2_500.5)
        insert_transaction(
            self.store, self.account_id, self.renta, "2026-02-15", -9_999, voided=True
        )
        insert_transaction(self.store, self.account_id, self.renta, "2026-01-31", -700)

        status = self.store.budget_report(date(2026, 2, 1))[0]
        self.assertAlmostEqual(status.spent, 3_500.50, places=2)
        self.assertAlmostEqual(status.remaining, 6_499.50, places=2)
        self.assertFalse(status.over)

    def test_trend_covers_six_months_ending_with_the_selected_month(self) -> None:
        self.store.set_budget(self.renta, 10_000)
        insert_transaction(self.store, self.account_id, self.renta, "2026-01-15", -100)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-15", -200)

        status = self.store.budget_report(date(2026, 2, 10))[0]
        self.assertEqual(
            [label for label, _ in status.trend],
            ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb"],
        )
        self.assertEqual(
            [spent for _, spent in status.trend],
            [0.0, 0.0, 0.0, 0.0, 100.0, 200.0],
        )

    def test_reports_follow_month_boundaries_across_years(self) -> None:
        self.store.set_budget(self.renta, 10_000)
        insert_transaction(self.store, self.account_id, self.renta, "2025-12-31", -500)
        insert_transaction(self.store, self.account_id, self.renta, "2026-01-01", -600)

        december = self.store.budget_report(date(2025, 12, 20))[0]
        january = self.store.budget_report(date(2026, 1, 20))[0]
        self.assertAlmostEqual(december.spent, 500, places=2)
        self.assertAlmostEqual(january.spent, 600, places=2)
        self.assertEqual(january.trend[-2], ("Dec", 500.0))

    def test_over_budget_status(self) -> None:
        self.store.set_budget(self.renta, 1_000)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-15", -1_200)
        status = self.store.budget_report(date(2026, 2, 1))[0]
        self.assertTrue(status.over)
        self.assertAlmostEqual(status.ratio, 1.2, places=4)
        self.assertAlmostEqual(status.remaining, -200, places=2)

    def test_shift_month_start_handles_year_boundaries(self) -> None:
        self.assertEqual(_shift_month_start(date(2026, 1, 31), -1), date(2025, 12, 1))
        self.assertEqual(_shift_month_start(date(2025, 12, 15), 1), date(2026, 1, 1))

    def test_budget_start_day_defaults_to_one_and_clamps(self) -> None:
        self.assertEqual(self.store.budget_start_day(), 1)
        self.store.set_budget_start_day(15)
        self.assertEqual(self.store.budget_start_day(), 15)
        self.store.set_budget_start_day(0)
        self.assertEqual(self.store.budget_start_day(), 1)
        self.store.set_budget_start_day(99)
        self.assertEqual(self.store.budget_start_day(), 31)
        self.store.set_setting("budget_start_day", "not a day")
        self.assertEqual(self.store.budget_start_day(), 1)

    def test_budget_periods_follow_the_configured_start_day(self) -> None:
        self.store.set_budget_start_day(15)
        self.assertEqual(
            self.store.budget_period(date(2026, 2, 1)),
            (date(2026, 2, 15), date(2026, 3, 14)),
        )
        # Day 31 is clamped to the last day of short months.
        self.store.set_budget_start_day(31)
        self.assertEqual(
            self.store.budget_period(date(2026, 2, 1)),
            (date(2026, 2, 28), date(2026, 3, 30)),
        )

    def test_current_budget_period_uses_todays_place_in_the_cycle(self) -> None:
        self.store.set_budget_start_day(15)
        self.assertEqual(
            self.store.current_budget_period(date(2026, 2, 14)), date(2026, 1, 1)
        )
        self.assertEqual(
            self.store.current_budget_period(date(2026, 2, 15)), date(2026, 2, 1)
        )
        self.assertEqual(
            self.store.current_budget_period(date(2026, 3, 1)), date(2026, 2, 1)
        )

    def test_report_counts_only_dates_inside_the_budget_period(self) -> None:
        self.store.set_budget(self.renta, 1_000)
        self.store.set_budget_start_day(15)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-14", -100)
        insert_transaction(self.store, self.account_id, self.renta, "2026-02-15", -200)
        insert_transaction(self.store, self.account_id, self.renta, "2026-03-14", -300)
        insert_transaction(self.store, self.account_id, self.renta, "2026-03-15", -400)

        february = self.store.budget_report(date(2026, 2, 20))[0]
        self.assertAlmostEqual(february.spent, 500.0, places=2)
        self.assertEqual(february.trend[-1], ("Feb", 500.0))

        january = self.store.budget_report(date(2026, 1, 20))[0]
        self.assertAlmostEqual(january.spent, 100.0, places=2)

        march = self.store.budget_report(date(2026, 3, 20))[0]
        self.assertAlmostEqual(march.spent, 400.0, places=2)


class BudgetWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_progress_bar_clamps_full_when_over_budget(self) -> None:
        bar = BudgetProgress()
        bar.set_values(1_500, 1_000)
        self.assertEqual(bar.spent, 1_500)
        self.assertEqual(bar.budget, 1_000)
        bar.deleteLater()

    def test_row_reports_over_budget_without_raising(self) -> None:
        status = BudgetStatus(
            category_id=1,
            category_name="renta",
            color="#ff8800",
            budget=1_000,
            spent=1_250,
            trend=[("Jan", 900.0), ("Feb", 1_250.0)],
        )
        row = BudgetRow(status)
        self.assertIn("Over by", row.remaining.text())
        self.assertEqual(row.percent.text(), "125%")
        row.deleteLater()

    def test_settings_dialog_saves_and_clears_budgets(self) -> None:
        from contapy.widgets.budgets import BudgetSettingsDialog

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "settings.db", seed=False)
        self.addCleanup(store.close)
        category_id = insert_category(store, "renta")
        other_id = insert_category(store, "food")
        store.set_budget(other_id, 500)

        dialog = BudgetSettingsDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.spins[category_id].setValue(2_500)
        dialog.spins[other_id].setValue(0)
        dialog._save()

        self.assertTrue(dialog.changed)
        self.assertEqual(store.budget_amount(category_id), 2_500)
        self.assertEqual(store.budget_amount(other_id), 0.0)

    def test_window_navigates_months_and_renders_budget_rows(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "window.db", seed=False)
        self.addCleanup(store.close)
        cur = store.conn.execute(
            "INSERT INTO accounts(name, kind, opening, sort_order) VALUES ('Bank','Bank',0,0)"
        )
        account_id = int(cur.lastrowid)
        category_id = insert_category(store, "renta")
        store.conn.commit()
        store.set_budget(category_id, 1_000)
        today = date.today()
        insert_transaction(
            store, account_id, category_id, today.replace(day=1).isoformat(), -250
        )

        window = BudgetWindow(store)
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.month, today.replace(day=1))
        expected = (
            f"{calendar.month_name[today.month]} {today.year} · monthly budgets"
        )
        self.assertEqual(window.span_label.text(), expected)
        self.assertTrue(window.month_title.text())

        window._shift_month(-1)
        self.assertEqual(window.month, _shift_month_start(today.replace(day=1), -1))
        window._show_this_month()
        self.assertEqual(window.month, today.replace(day=1))
        window.reload()

    def test_window_start_day_selector_persists_and_reloads(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "start_day.db", seed=False)
        self.addCleanup(store.close)
        category_id = insert_category(store, "renta")
        store.set_budget(category_id, 1_000)

        window = BudgetWindow(store)
        self.addCleanup(window.deleteLater)
        self.assertEqual(window.start_combo.currentData(), 1)

        window.start_combo.setCurrentIndex(window.start_combo.findData(15))
        self.assertEqual(store.budget_start_day(), 15)
        self.assertEqual(window.month, store.current_budget_period())
        self.assertIn("–", window.span_label.text())

        window._show_this_month()
        self.assertEqual(window.month, store.current_budget_period())

    def test_embedded_budgets_panel_renders_rows_and_navigates(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "panel.db", seed=False)
        self.addCleanup(store.close)
        cur = store.conn.execute(
            "INSERT INTO accounts(name, kind, opening, sort_order) VALUES ('Bank','Bank',0,0)"
        )
        account_id = int(cur.lastrowid)
        category_id = insert_category(store, "renta")
        store.conn.commit()
        store.set_budget(category_id, 1_000)
        today = date.today()
        insert_transaction(
            store, account_id, category_id, today.replace(day=1).isoformat(), -250
        )

        panel = BudgetsPanel(store)
        self.addCleanup(panel.deleteLater)
        self.assertEqual(panel.month, today.replace(day=1))
        self.assertTrue(panel.month_label.text())
        self.assertNotEqual(panel.budgeted_block.value.text(), "—")
        rows = [
            panel.content_layout.itemAt(index).widget()
            for index in range(panel.content_layout.count())
        ]
        self.assertTrue(any(isinstance(row, BudgetRow) for row in rows))

        panel._shift_month(-1)
        self.assertEqual(panel.month, _shift_month_start(today.replace(day=1), -1))
        panel._show_this_month()
        self.assertEqual(panel.month, today.replace(day=1))

    def test_main_window_puts_budgets_beside_the_scheduled_strip(self) -> None:
        from contapy.main_window import MainWindow

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "main.db", seed=False)
        self.addCleanup(store.close)
        window = MainWindow(store)
        self.addCleanup(window.close)

        self.assertEqual(window.bottom_split.count(), 2)
        self.assertIs(window.bottom_split.widget(0), window.scheduled_panel)
        self.assertIs(window.bottom_split.widget(1), window.budgets_panel)
        self.assertTrue(window.act_toggle_budgets.isChecked())

        window.act_toggle_budgets.setChecked(False)
        self.assertTrue(window.budgets_panel.isHidden())
        window.act_toggle_budgets.setChecked(True)
        self.assertFalse(window.budgets_panel.isHidden())


if __name__ == "__main__":
    unittest.main()
