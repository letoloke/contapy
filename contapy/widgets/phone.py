"""QR-code pairing dialog for the LetoBank GO Android companion."""

from __future__ import annotations

import io
from urllib.parse import urlencode

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..branding import APP_NAME
from ..theme import C, font


def pairing_uri(url: str, token: str) -> str:
    """The deep link encoded in the pairing QR code."""
    query = urlencode({"url": url.strip(), "token": token.strip()})
    return f"letobankgo://connect?{query}"


def qr_pixmap(text: str, size: int = 280) -> QPixmap | None:
    """Render ``text`` as a QR pixmap, or ``None`` if segno is unavailable."""
    try:
        import segno
    except ImportError:
        return None
    qr = segno.make(text, error="m")
    buffer = io.BytesIO()
    qr.save(
        buffer,
        kind="png",
        scale=8,
        border=2,
        light="white",
        dark="black",
    )
    pixmap = QPixmap()
    if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
        return None
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class ConnectPhoneDialog(QDialog):
    """Show a QR code and the manual address/token fallback."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        running: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.url = url.strip()
        self.token = token.strip()
        self.running = running
        self.payload = pairing_uri(self.url, self.token)
        self.setWindowTitle("Connect LetoBank GO")
        self.setModal(True)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)

        heading = QLabel("Connect LetoBank GO")
        heading.setFont(font(18, 600))
        root.addWidget(heading)

        subtitle = QLabel(
            "Open LetoBank GO → Settings → Scan QR code and point the phone "
            "at this code. Both devices must be on the same network."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(font(13, 400))
        subtitle.setStyleSheet(f"color:{C.MUTED};")
        root.addWidget(subtitle)

        qr = qr_pixmap(self.payload)
        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_label.setFixedSize(296, 296)
        qr_label.setStyleSheet(
            "background:white; border-radius:8px; padding:8px;"
        )
        if qr is None:
            qr_label.setText("QR code unavailable\nInstall the segno package.")
            qr_label.setWordWrap(True)
            qr_label.setStyleSheet(
                f"color:{C.MUTED_DARK}; background:{C.PANEL};"
                f" border:1px solid {C.BORDER}; border-radius:8px;"
            )
        else:
            qr_label.setPixmap(qr)
        root.addWidget(qr_label, alignment=Qt.AlignmentFlag.AlignCenter)

        details = QGridLayout()
        details.setHorizontalSpacing(8)
        details.setVerticalSpacing(6)
        self._row(details, 0, "Server", self.url)
        self._row(details, 1, "Token", self.token)
        root.addLayout(details)

        if not running:
            warning = QLabel(
                f"LAN sync is not running in this {APP_NAME} session. "
                "Restart LetoBank or check that the sync port is free."
            )
            warning.setWordWrap(True)
            warning.setFont(font(12, 400))
            warning.setStyleSheet(
                f"color:{C.ORANGE}; background:{C.PANEL};"
                f" border:1px solid {C.BORDER}; border-radius:5px;"
                " padding:8px;"
            )
            root.addWidget(warning)

        buttons = QHBoxLayout()
        copy_link = QPushButton("Copy pairing link")
        copy_link.setAutoDefault(False)
        copy_link.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_link.clicked.connect(
            lambda: QApplication.clipboard().setText(self.payload)
        )
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        buttons.addWidget(copy_link)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _row(self, grid: QGridLayout, row: int, label: str, value: str) -> None:
        name = QLabel(label)
        name.setFont(font(12, 500))
        name.setStyleSheet(f"color:{C.MUTED};")
        grid.addWidget(name, row, 0)

        edit = QLineEdit(value)
        edit.setReadOnly(True)
        edit.setFont(font(12, 400))
        edit.setCursorPosition(0)
        grid.addWidget(edit, row, 1)

        copy = QPushButton("Copy")
        copy.setAutoDefault(False)
        copy.setCursor(Qt.CursorShape.PointingHandCursor)
        copy.setFont(font(12, 400))
        copy.clicked.connect(
            lambda _checked=False, text=value: QApplication.clipboard().setText(
                text
            )
        )
        grid.addWidget(copy, row, 2)
