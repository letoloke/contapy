"""Persistent app settings that live outside any one database.

ContaPy remembers the last database opened from the File menu so the next
launch reopens it.  The database itself cannot hold that pointer (it is the
thing being opened), so it lives in a small JSON file under the XDG config
directory:

    ~/.config/contapy/config.json

Set ``XDG_CONFIG_HOME`` to relocate it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .dates import DATE_FORMATS, DEFAULT_DATE_FORMAT
from .omarchy import DEFAULT_THEME

DEFAULT_LEDGER_STATUS = "any"
LEDGER_STATUSES = (
    "any",
    "unreconciled",
    "cleared",
    "reconciled",
    "remind",
    "flagged",
    "voided",
)


def config_path(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "contapy" / "config.json"


def _read(environ: dict[str, str] | None = None) -> dict:
    try:
        data = json.loads(config_path(environ).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def last_database(environ: dict[str, str] | None = None) -> Path | None:
    """Return the remembered database path, if one was saved."""
    value = _read(environ).get("database")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def remember_database(path: str | Path, environ: dict[str, str] | None = None) -> None:
    """Persist ``path`` as the database to reopen on the next launch."""
    target = Path(path).expanduser().resolve()
    data = _read(environ)
    data["database"] = str(target)
    _write(data, environ)


def theme_choice(environ: dict[str, str] | None = None) -> str:
    """The saved theme slug, defaulting to One Dark."""
    value = _read(environ).get("theme")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return DEFAULT_THEME


def remember_theme(choice: str, environ: dict[str, str] | None = None) -> None:
    """Persist the selected theme for the next launch."""
    data = _read(environ)
    data["theme"] = choice.strip()
    _write(data, environ)


def date_format_choice(environ: dict[str, str] | None = None) -> str:
    """The saved date display format, defaulting to ``yyyy/mmm/dd``."""
    value = _read(environ).get("date_format")
    keys = {item.key for item in DATE_FORMATS}
    if isinstance(value, str) and value in keys:
        return value
    return DEFAULT_DATE_FORMAT


def remember_date_format(key: str, environ: dict[str, str] | None = None) -> None:
    data = _read(environ)
    data["date_format"] = key.strip()
    _write(data, environ)


def ledger_status_choice(environ: dict[str, str] | None = None) -> str:
    """The status filter applied when an account ledger opens."""
    value = _read(environ).get("ledger_status")
    if isinstance(value, str) and value in LEDGER_STATUSES:
        return value
    return DEFAULT_LEDGER_STATUS


def remember_ledger_status(status: str, environ: dict[str, str] | None = None) -> None:
    data = _read(environ)
    data["ledger_status"] = status.strip()
    _write(data, environ)


def _write(data: dict, environ: dict[str, str] | None = None) -> None:
    config = config_path(environ)
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config)
