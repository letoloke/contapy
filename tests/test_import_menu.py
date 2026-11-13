"""Tests for the Ctrl+I import-source menu."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.main_window import MainWindow
from contapy.theme import apply_theme


class ImportMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_ctrl_i_opens_the_import_source_menu(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "menu.db", seed=False)
        window = MainWindow(store)
        try:
            self.assertEqual(window.act_import.shortcut().toString(), "Ctrl+I")
            self.assertEqual(
                [action.text() for action in window.import_menu.actions()],
                [
                    "Import CSV…",
                    "From Airbnb…",
                    "From Booking…",
                    "From Banamex…",
                ],
            )

            file_menu = next(
                action.menu()
                for action in window.menuBar().actions()
                if action.text() == "File"
            )
            self.assertIn(
                window.import_menu,
                [action.menu() for action in file_menu.actions()],
            )

            with mock.patch.object(window.import_menu, "popup") as popup:
                window.act_import.trigger()
            popup.assert_called_once()
        finally:
            window.close()
