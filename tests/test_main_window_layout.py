"""Dashboard layout regressions for narrow windows."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.main_window import MainWindow
from contapy.theme import apply_theme


class MainWindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_spending_revenue_stays_visible_in_a_narrow_window(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "layout.db", seed=True)
        window = MainWindow(store)
        try:
            window.show()
            self.app.processEvents()
            window.setFixedSize(900, 700)
            for _ in range(5):
                self.app.processEvents()

            self.assertTrue(window.bar_card.isVisible())
            left = window.bar_card.mapTo(window, QPoint(0, 0)).x()
            self.assertLessEqual(left + window.bar_card.width(), window.width())
            self.assertGreater(window.bar_card.width(), 0)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
