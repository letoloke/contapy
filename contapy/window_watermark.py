"""Small top-right window-name watermark, installed app-wide."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolTip,
    QWidget,
)

from .theme import C, font


def _window_name(widget: QWidget) -> str:
    cls = type(widget).__name__
    if cls == "MainWindow":
        return "Dashboard"
    if cls == "ReportsWindow":
        return "Reports"
    if cls == "BudgetWindow":
        return "Budgets"
    if cls == "LedgerWindow":
        title = widget.windowTitle().strip()
        suffix = " — Account"
        account = title[: -len(suffix)] if title.endswith(suffix) else ""
        return (
            f"Account Ledger · {account}"
            if account
            else (title or "Account Ledger")
        )
    return widget.windowTitle().strip() or cls


class WindowWatermark(QLabel):
    """Read-only badge painted over the top-right corner of its window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to copy the window name")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(font(9, 600))
        self.refresh_style()
        self.reposition()

    def refresh_style(self) -> None:
        self.setStyleSheet(
            f"color:{C.MUTED}; background:{C.PANEL_RAISED}; "
            f"border:1px solid {C.BORDER}; border-radius:4px; "
            f"padding:1px 5px;"
        )

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setText(_window_name(parent))
        self.setMaximumWidth(max(120, parent.width() - 20))
        self.adjustSize()
        self.move(
            max(0, parent.width() - self.width() - 8),
            2,
        )
        self.raise_()
        self.show()

    def _flash_copied(self) -> None:
        self.setStyleSheet(
            f"color:#ffffff; background:{C.ACCENT}; "
            f"border:1px solid {C.ACCENT}; border-radius:4px; "
            f"padding:1px 5px;"
        )
        QTimer.singleShot(700, self._restore_style)

    def _restore_style(self) -> None:
        try:
            self.refresh_style()
        except RuntimeError:
            pass

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            name = self.text()
            QApplication.clipboard().setText(name)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"Copied “{name}”",
                self,
            )
            self._flash_copied()
        super().mousePressEvent(event)


class WindowWatermarkManager(QObject):
    """Application event filter that attaches a name badge to each window."""

    def __init__(self, app: QApplication):
        super().__init__(app)
        self.app = app
        app.installEventFilter(self)

    @staticmethod
    def _eligible(widget: QObject) -> bool:
        return (
            isinstance(widget, (QMainWindow, QDialog))
            and not isinstance(widget, (QMessageBox, QFileDialog))
            and widget.isWindow()
        )

    def _attach(self, window: QWidget) -> WindowWatermark:
        mark = getattr(window, "_letobank_watermark", None)
        if mark is None:
            mark = WindowWatermark(window)
            window._letobank_watermark = mark
        return mark

    @staticmethod
    def _safe_reposition(mark: WindowWatermark) -> None:
        try:
            mark.reposition()
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() not in (
            QEvent.Type.Show,
            QEvent.Type.Resize,
            QEvent.Type.WindowTitleChange,
            QEvent.Type.PaletteChange,
        ):
            return False
        if not self._eligible(obj):
            return False
        if event.type() == QEvent.Type.Show:
            mark = self._attach(obj)
            mark.reposition()
            QTimer.singleShot(0, lambda: self._safe_reposition(mark))
        else:
            mark = getattr(obj, "_letobank_watermark", None)
            if mark is not None:
                if event.type() == QEvent.Type.PaletteChange:
                    mark.refresh_style()
                self._safe_reposition(mark)
        return False


def install_window_watermarks(
    app: QApplication,
) -> WindowWatermarkManager:
    """Install the watermark manager once and keep it alive on the app."""
    manager = getattr(app, "_letobank_watermark_manager", None)
    if manager is None:
        manager = WindowWatermarkManager(app)
        app._letobank_watermark_manager = manager
    return manager
