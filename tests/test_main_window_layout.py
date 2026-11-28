"""Dashboard layout regressions for narrow windows."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.main_window import MainWindow
from contapy.theme import apply_theme


class MainWindowLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_spending_revenue_hides_and_returns_with_width(self) -> None:
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
            self.assertTrue(window.bar_card.isHidden())

            window.setFixedSize(1500, 800)
            for _ in range(5):
                self.app.processEvents()
            self.assertFalse(window.bar_card.isHidden())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
