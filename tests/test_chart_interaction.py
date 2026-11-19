"""Tests for clickable chart drill-down."""

from __future__ import annotations

import math
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.main_window import MainWindow
from contapy.models import MonthFlow, Slice
from contapy.theme import apply_theme
from contapy.widgets.charts import DonutChart, SpendingRevenueChart
from contapy.widgets.reports import CategoryBarChart, ReportsWindow


class ChartSignalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_donut_slice_click_emits_index(self) -> None:
        chart = DonutChart()
        self.addCleanup(chart.deleteLater)
        chart.resize(420, 420)
        chart.show()
        chart.set_data(
            [
                Slice("First", 60, "#ff0000", 0.6),
                Slice("Second", 40, "#00ff00", 0.4),
            ],
            100,
        )
        QTest.qWait(50)
        clicked: list[int] = []
        chart.sliceActivated.connect(clicked.append)

        mid = (chart._radius + chart._inner) / 2
        angle = math.radians(45)
        point = QPoint(
            int(chart._center.x() + mid * math.cos(angle)),
            int(chart._center.y() - mid * math.sin(angle)),
        )
        QTest.mouseClick(chart, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicked, [0])

    def test_month_bar_click_emits_index(self) -> None:
        chart = SpendingRevenueChart()
        self.addCleanup(chart.deleteLater)
        chart.resize(640, 320)
        chart.show()
        chart.set_data(
            [
                MonthFlow(2026, 10, "Oct", 1_000, 500),
                MonthFlow(2026, 11, "Nov", 2_000, 800),
            ]
        )
        QTest.qWait(50)
        clicked: list[int] = []
        chart.monthActivated.connect(clicked.append)

        point = QPoint(
            int(chart._plot.left() + chart._slot * 0.5),
            int(chart._plot.center().y()),
        )
        QTest.mouseClick(chart, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicked, [0])

    def test_category_bar_click_emits_index(self) -> None:
        chart = CategoryBarChart()
        self.addCleanup(chart.deleteLater)
        chart.resize(520, 300)
        chart.show()
        chart.set_data(
            [("Food", 100, "#ff0000"), ("Rent", 200, "#00ff00")]
        )
        QTest.qWait(50)
        clicked: list[int] = []
        chart.barActivated.connect(clicked.append)

        top = 14.0
        bottom = chart.height() - 14.0
        row_h = (bottom - top) / 2
        point = QPoint(120, int(top + row_h * 0.5))
        QTest.mouseClick(chart, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicked, [0])


class ReportsChartInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "reports.db")
        self.window = ReportsWindow(self.store)

    def tearDown(self) -> None:
        self.window.close()
        self.store.close()
        self.tmp.cleanup()

    def test_category_chart_clicks_open_transaction_lists(self) -> None:
        self.window.set_view("pie")
        self.assertTrue(self.window._pie_labels)
        pie_label = self.window._pie_labels[0]

        with mock.patch(
            "contapy.widgets.reports.CategoryTransactionsDialog"
        ) as dialog:
            self.window._pie_slice_clicked(0)

        dialog.assert_called_once()
        pie_category = dialog.call_args.args[1]
        self.assertEqual(
            pie_category.name.casefold(), pie_label.casefold()
        )
        kwargs = dialog.call_args.kwargs
        self.assertEqual(kwargs["start"], self.window.range()[0])
        self.assertEqual(kwargs["end"], self.window.range()[1])

        self.window.set_view("bar")
        self.assertTrue(self.window._bar_labels)
        bar_label = self.window._bar_labels[0]

        with mock.patch(
            "contapy.widgets.reports.CategoryTransactionsDialog"
        ) as dialog:
            self.window._bar_clicked(0)

        dialog.assert_called_once()
        bar_category = dialog.call_args.args[1]
        self.assertEqual(
            bar_category.name.casefold(), bar_label.casefold()
        )

    def test_non_category_chart_click_selects_the_table_row(self) -> None:
        index = self.window.group_combo.findData("payee")
        self.window.group_combo.setCurrentIndex(index)
        self.window.set_view("bar")
        self.assertTrue(self.window._bar_labels)
        label = self.window._bar_labels[0]

        self.window._bar_clicked(0)

        self.assertEqual(self.window._view, "table")
        self.assertEqual(
            self.window.table.item(self.window.table.currentRow(), 0).text(),
            label,
        )

    def test_focus_period_switches_to_a_single_month(self) -> None:
        self.window.focus_period(
            date(2026, 10, 1), date(2026, 10, 31), mode="time"
        )

        self.assertEqual(self.window.mode(), "time")
        self.assertEqual(
            self.window.range(), (date(2026, 10, 1), date(2026, 10, 31))
        )
        self.assertEqual(self.window._view, "table")


class DashboardChartInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "dashboard.db")
        self.window = MainWindow(self.store)

    def tearDown(self) -> None:
        self.window.close()
        self.store.close()
        self.tmp.cleanup()

    def test_donut_slice_opens_category_transactions(self) -> None:
        index = next(
            index
            for index, item in enumerate(self.window.donut.slices)
            if item.name != "Other"
        )
        name = self.window.donut.slices[index].name

        with mock.patch(
            "contapy.main_window.CategoryTransactionsDialog"
        ) as dialog:
            self.window._open_donut_slice(index)

        dialog.assert_called_once()
        category = dialog.call_args.args[1]
        self.assertEqual(category.name.casefold(), name.casefold())

    def test_month_bar_opens_that_month_in_reports(self) -> None:
        self.assertTrue(self.window.bars.flows)
        flow = self.window.bars.flows[0]
        fake = mock.Mock()

        def open_reports() -> None:
            self.window.reports_window = fake

        with mock.patch.object(
            self.window, "open_reports", side_effect=open_reports
        ):
            self.window._open_bar_month(0)

        fake.focus_period.assert_called_once()
        args = fake.focus_period.call_args
        self.assertEqual(args.args[0], date(flow.year, flow.month, 1))
        self.assertEqual(args.kwargs["mode"], "time")
