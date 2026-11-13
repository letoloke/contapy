"""Tests for the Markdown activity history and its File menu actions."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.activity import ActivityLog, transaction_detail
from contapy.db import DataStore
from contapy.main_window import MainWindow
from contapy.theme import apply_theme


class ActivityLogTests(unittest.TestCase):
    def test_transaction_detail_includes_memo_when_present(self) -> None:
        self.assertEqual(
            transaction_detail("Coffee", -25.0, "Oat milk"),
            "Coffee · $ -25.00 · memo: Oat milk",
        )
        self.assertEqual(
            transaction_detail("Coffee", -25.0),
            "Coffee · $ -25.00",
        )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "activity-history.md"

    def test_flush_creates_markdown_and_appends_entries(self) -> None:
        log = ActivityLog(self.path)
        log.record("New transaction", "Coffee · $ -25.00")
        log.flush()

        text = self.path.read_text(encoding="utf-8")
        self.assertIn("# LetoBank activity history", text)
        self.assertIn("New transaction: Coffee · $ -25.00", text)
        self.assertRegex(text, r"\*\*\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\*\*")

        log.record("Reconciled 3 transaction(s)")
        log.flush()
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("Reconciled 3 transaction(s)", text)
        self.assertLess(
            text.index("New transaction"),
            text.index("Reconciled 3 transaction(s)"),
        )

    def test_flush_is_idempotent_without_pending_entries(self) -> None:
        log = ActivityLog(self.path)
        log.record("Application opened", "test.db")
        log.flush()
        first = self.path.read_text(encoding="utf-8")
        log.flush()
        self.assertEqual(first, self.path.read_text(encoding="utf-8"))

    def test_save_as_copies_the_complete_history(self) -> None:
        log = ActivityLog(self.path)
        log.record("Exported transactions", "12 · export.csv")
        target = Path(self.tmp.name) / "saved-history"
        result = log.save_as(target)

        self.assertEqual(result.suffix, ".md")
        self.assertTrue(result.exists())
        self.assertIn(
            "Exported transactions: 12 · export.csv",
            result.read_text(encoding="utf-8"),
        )


class ActivityMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_history_actions_timer_and_markdown_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        store = DataStore(folder / "main.db", seed=False)
        window = MainWindow(store)
        try:
            self.assertEqual(
                window.act_save_activity.shortcut().toString(), "Ctrl+Shift+S"
            )
            self.assertEqual(
                window.act_save_database.shortcut().toString(), "Ctrl+Alt+S"
            )
            self.assertEqual(window.act_view_activity.text(), "View Activity History")
            self.assertEqual(window._activity_timer.interval(), 5 * 60 * 1000)
            self.assertTrue(window._activity_timer.isActive())

            path = folder / "activity-history.md"
            self.assertTrue(path.exists())
            self.assertIn("Application opened", path.read_text(encoding="utf-8"))

            window._record_activity("Test action", "details")
            window._flush_activity()
            self.assertIn(
                "Test action: details", path.read_text(encoding="utf-8")
            )

            target = folder / "saved-activity.md"
            with mock.patch(
                "contapy.main_window.QFileDialog.getSaveFileName",
                return_value=(str(target), "Markdown files (*.md)"),
            ):
                window.save_activity_history_as()
            self.assertTrue(target.exists())
            self.assertIn("Test action: details", target.read_text(encoding="utf-8"))

            with mock.patch(
                "contapy.main_window.QDesktopServices.openUrl"
            ) as open_url:
                window.view_activity_history()
            open_url.assert_called_once()
            self.assertIn(
                "Viewed activity history", path.read_text(encoding="utf-8")
            )
        finally:
            window.close()
