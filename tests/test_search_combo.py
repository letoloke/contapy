"""Regression tests for editable completion fields keeping typed text."""

from __future__ import annotations

import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from contapy.theme import apply_theme
from contapy.widgets.dialogs import SearchCombo


class SearchComboSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def combo(self, *, keep_text_unselected: bool = True) -> SearchCombo:
        widget = SearchCombo(
            "Type a payee", keep_text_unselected=keep_text_unselected
        )
        widget.set_choices(
            [("Coffee Shop", "Coffee Shop")], select_first=False
        )
        widget.show()
        widget.activateWindow()
        self.addCleanup(widget.close)
        self.addCleanup(widget.deleteLater)
        return widget

    def test_keyboard_focus_places_cursor_at_end_without_selecting(self) -> None:
        combo = self.combo()
        combo.setEditText("Coff")
        combo.clearFocus()
        combo.lineEdit().setFocus(Qt.FocusReason.TabFocusReason)
        QTest.qWait(10)

        self.assertEqual(combo.lineEdit().selectedText(), "")
        self.assertEqual(
            combo.lineEdit().cursorPosition(), len("Coff")
        )

    def test_typing_an_unknown_value_keeps_appending(self) -> None:
        combo = self.combo()
        combo.lineEdit().setFocus()
        QTest.qWait(10)

        QTest.keyClicks(combo.lineEdit(), "Zzz")
        self.assertEqual(combo.currentText(), "Zzz")
        self.assertEqual(combo.lineEdit().selectedText(), "")
        self.assertEqual(combo.lineEdit().cursorPosition(), 3)

        QTest.keyClicks(combo.lineEdit(), " more")
        self.assertEqual(combo.currentText(), "Zzz more")
        self.assertEqual(combo.lineEdit().selectedText(), "")
        self.assertEqual(combo.lineEdit().cursorPosition(), len("Zzz more"))

    def test_leaving_a_custom_value_does_not_steal_focus_back(self) -> None:
        container = QWidget()
        self.addCleanup(container.close)
        self.addCleanup(container.deleteLater)
        layout = QVBoxLayout(container)
        combo = SearchCombo("Type a payee")
        other = QLineEdit()
        layout.addWidget(combo)
        layout.addWidget(other)
        container.show()
        container.raise_()
        container.activateWindow()
        QTest.qWait(20)
        combo.setEditText("Custom payee")
        combo.lineEdit().setFocus()
        QTest.qWait(20)

        other.setFocus()
        QTest.qWait(20)

        self.assertIs(container.focusWidget(), other)
        self.assertEqual(combo.currentText(), "Custom payee")
