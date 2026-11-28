"""Tests for the Scheduled / Future / Remind tab ordering."""

from __future__ import annotations

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from contapy.theme import apply_theme
from contapy.widgets.scheduled import ScheduledPanel


class ScheduledTabOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_remind_is_first_by_default(self) -> None:
        panel = ScheduledPanel(tab_order=["Remind", "Scheduled", "Future"])
        try:
            self.assertEqual(panel.tabs.active, "Remind")
            self.assertEqual(
                panel.tabs.order, ["Remind", "Scheduled", "Future"]
            )
        finally:
            panel.deleteLater()

    def test_custom_order_selects_its_first_tab(self) -> None:
        panel = ScheduledPanel(tab_order=["Future", "Remind", "Scheduled"])
        try:
            self.assertEqual(panel.tabs.active, "Future")
            self.assertEqual(
                panel.tabs.order, ["Future", "Remind", "Scheduled"]
            )
        finally:
            panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
