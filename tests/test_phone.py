"""Tests for the LetoBank GO QR pairing dialog."""

from __future__ import annotations

import os
import unittest
from urllib.parse import parse_qs, urlparse

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from contapy.theme import apply_theme
from contapy.widgets.phone import ConnectPhoneDialog, pairing_uri, qr_pixmap


class PairingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def test_pairing_uri_round_trips_url_and_token(self) -> None:
        uri = pairing_uri("http://192.168.1.5:8787", "secret token")
        parsed = urlparse(uri)

        self.assertEqual(parsed.scheme, "letobankgo")
        self.assertEqual(parsed.netloc, "connect")
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "url": ["http://192.168.1.5:8787"],
                "token": ["secret token"],
            },
        )

    def test_qr_pixmap_renders(self) -> None:
        pixmap = qr_pixmap(
            pairing_uri("http://192.168.1.5:8787", "secret")
        )
        self.assertIsNotNone(pixmap)
        assert pixmap is not None
        self.assertEqual(pixmap.width(), 280)

    def test_dialog_exposes_the_pairing_payload(self) -> None:
        dialog = ConnectPhoneDialog(
            "http://192.168.1.5:8787",
            "secret",
            running=False,
        )
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(
            dialog.payload,
            pairing_uri("http://192.168.1.5:8787", "secret"),
        )
        self.assertFalse(dialog.running)


if __name__ == "__main__":
    unittest.main()
