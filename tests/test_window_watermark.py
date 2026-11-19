"""Tests for the app-wide window-name watermark."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow

from contapy.theme import apply_theme
from contapy.window_watermark import install_window_watermarks


class WindowWatermarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.manager = install_window_watermarks(self.app)
        self.addCleanup(self.app.removeEventFilter, self.manager)
        self.addCleanup(
            lambda: setattr(self.app, "_letobank_watermark_manager", None)
        )

    def test_dialog_gets_a_named_top_right_badge(self) -> None:
        dialog = QDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.setWindowTitle("Test Dialog")
        dialog.resize(420, 240)
        dialog.show()
        QTest.qWait(20)

        mark = dialog._letobank_watermark
        self.assertEqual(mark.text(), "Test Dialog")
        self.assertTrue(mark.isVisible())
        self.assertFalse(
            mark.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )
        self.assertLessEqual(mark.x() + mark.width(), dialog.width())
        self.assertLess(mark.y(), 20)

        QApplication.clipboard().clear()
        QTest.mouseClick(mark, Qt.MouseButton.LeftButton)
        self.assertEqual(QApplication.clipboard().text(), "Test Dialog")

        dialog.setWindowTitle("Renamed Dialog")
        QTest.qWait(20)
        self.assertEqual(mark.text(), "Renamed Dialog")

        dialog.resize(640, 320)
        QTest.qWait(20)
        self.assertLessEqual(mark.x() + mark.width(), dialog.width())

    def test_main_window_uses_its_title(self) -> None:
        window = QMainWindow()
        self.addCleanup(window.deleteLater)
        window.setWindowTitle("Main Test")
        window.resize(500, 300)
        window.show()
        QTest.qWait(20)

        self.assertEqual(window._letobank_watermark.text(), "Main Test")
