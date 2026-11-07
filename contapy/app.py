"""Application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from . import __version__
from .db import DataStore
from .main_window import MainWindow
from .theme import C, DONUT_COLORS, apply_theme


def build_app_icon() -> QIcon:
    size = 128
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(C.PANEL))
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), 26, 26)
    colors = DONUT_COLORS or [C.ACCENT, C.GREEN, C.ORANGE, C.INFO]
    rect = QRectF(18, 18, size - 36, size - 36)
    angle = 90.0
    span = 360.0 / len(colors)
    for color in colors:
        p.setBrush(QColor(color))
        p.drawPie(rect, int(round(angle * 16)), int(round(-span * 16)))
        angle -= span
    p.setBrush(QColor(C.PANEL))
    p.drawEllipse(QPointF(size / 2, size / 2), size * 0.185, size * 0.185)
    p.end()
    return QIcon(pixmap)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ContaPy — a local-first finance dashboard")
    parser.add_argument("--db", help="Path to the SQLite database")
    parser.add_argument("--screenshot", help="Render the window to a PNG and exit")
    parser.add_argument("--size", default="1850x835", help="Window size for --screenshot")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.screenshot:
        # Always render offscreen so the capture is deterministic and does not
        # depend on the compositor's window rules.
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_SCALE_FACTOR"] = "1"

    app = QApplication(sys.argv[:1])
    app.setApplicationName("ContaPy")
    app.setApplicationDisplayName("ContaPy")
    app.setOrganizationName("ContaPy")
    app.setApplicationVersion(__version__)
    apply_theme(app)
    app.setWindowIcon(build_app_icon())

    store = DataStore(args.db)
    window = MainWindow(store)
    window.setWindowIcon(build_app_icon())

    if args.screenshot:
        try:
            width, height = (int(part) for part in args.size.lower().split("x"))
        except ValueError:
            width, height = 1850, 835
        window.resize(width, height)
        window.show()
        for _ in range(4):
            app.processEvents()
        output = Path(args.screenshot).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)

        def capture() -> None:
            pixmap = window.grab()
            pixmap.save(str(output), "PNG")
            print(f"wrote {output} ({pixmap.width()}x{pixmap.height()})")
            window.close()
            app.quit()

        QTimer.singleShot(450, capture)
        return app.exec()

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
