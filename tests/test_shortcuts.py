"""Tests for the Ctrl+K keyboard shortcut list."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.main_window import MainWindow
from contapy.widgets.dialogs import ShortcutsDialog


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


class ShortcutsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = app()

    def test_lists_shortcuts_and_includes_ctrl_k(self) -> None:
        dialog = ShortcutsDialog()
        self.addCleanup(dialog.deleteLater)
        self.assertGreater(dialog.table.rowCount(), 25)
        shortcuts = [
            dialog.table.item(row, 1).text()
            for row in range(dialog.table.rowCount())
        ]
        self.assertIn("Ctrl+K", shortcuts)
        self.assertEqual(dialog.visible_rows(), dialog.table.rowCount())

    def test_search_filters_by_key_or_context(self) -> None:
        dialog = ShortcutsDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.search_edit.setText("Alt+V")
        self.assertEqual(dialog.visible_rows(), 1)
        visible = [
            row
            for row in range(dialog.table.rowCount())
            if not dialog.table.isRowHidden(row)
        ]
        self.assertIn("void", dialog.table.item(visible[0], 2).text().lower())

        dialog.search_edit.setText("categories")
        self.assertEqual(dialog.visible_rows(), 2)

    def test_ledger_alt_v_and_undo_are_documented(self) -> None:
        dialog = ShortcutsDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.search_edit.setText("highlighted")
        self.assertEqual(dialog.visible_rows(), 1)
        dialog.search_edit.setText("Ctrl+Z")
        self.assertEqual(dialog.visible_rows(), 1)


class MainWindowShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = app()

    def test_ctrl_k_opens_the_list_anywhere_in_the_app(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "shortcuts.db", seed=False)
        self.addCleanup(store.close)
        window = MainWindow(store)
        self.addCleanup(window.close)

        self.assertEqual(window.act_shortcuts.shortcut().toString(), "Ctrl+K")
        self.assertEqual(
            window.act_shortcuts.shortcutContext(),
            Qt.ShortcutContext.ApplicationShortcut,
        )
        self.assertEqual(window.act_shortcuts.text(), "Keyboard Shortcuts")
