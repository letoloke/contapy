"""Markdown activity history for user actions."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .money import money


def activity_log_path(db_path: str | Path) -> Path:
    """The activity log lives beside the active database."""
    return Path(db_path).expanduser().parent / "activity-history.md"


def transaction_detail(payee: str, amount: float, memo: str = "") -> str:
    """Format a transaction for the history, including its memo when present."""
    detail = f"{payee} · {money(amount)}"
    memo = str(memo).strip()
    if memo:
        detail += f" · memo: {memo}"
    return detail


class ActivityLog:
    """Append-only Markdown history with a small in-memory write buffer.

    Actions are buffered and flushed by the application every five minutes,
    when the history is viewed or saved, and when the window closes.
    Existing history is preserved between sessions.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._pending: list[tuple[datetime, str]] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @staticmethod
    def _clean(text: str) -> str:
        return (
            " ".join(str(text).split())
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def record(self, action: str, detail: str = "") -> None:
        message = self._clean(action)
        detail = self._clean(detail)
        if detail:
            message = f"{message}: {detail}"
        self._pending.append((datetime.now(), message))

    def flush(self) -> Path:
        """Write buffered entries, creating the Markdown header if needed."""
        new_file = not self.path.exists()
        if not self._pending and not new_file:
            return self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            if new_file:
                handle.write("# LetoBank activity history\n\n")
                handle.write(
                    "This file records actions taken in the desktop app. "
                    "Entries are added in chronological order.\n\n"
                )
            for when, message in self._pending:
                handle.write(f"- **{when:%Y-%m-%d %H:%M:%S}** — {message}\n")
        self._pending.clear()
        return self.path

    def save_as(self, target: str | Path) -> Path:
        """Flush and copy the complete history to ``target``."""
        target = Path(target).expanduser()
        if not target.suffix:
            target = target.with_suffix(".md")
        self.flush()
        if target.resolve() != self.path.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, target)
        return target
