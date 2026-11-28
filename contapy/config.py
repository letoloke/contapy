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
import secrets
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
    "no_tags",
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


def font_family_choice(environ: dict[str, str] | None = None) -> str:
    """The saved UI font family, or an empty string for the theme default."""
    value = _read(environ).get("font_family")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def remember_font_family(
    family: str, environ: dict[str, str] | None = None
) -> None:
    """Persist the selected UI font family."""
    data = _read(environ)
    if family.strip():
        data["font_family"] = family.strip()
    else:
        data.pop("font_family", None)
    _write(data, environ)


def font_weight_choice(environ: dict[str, str] | None = None) -> int:
    """The saved UI font weight, or 0 for the theme default."""
    value = _read(environ).get("font_weight")
    try:
        weight = int(value)
    except (TypeError, ValueError):
        return 0
    return weight if 100 <= weight <= 900 else 0


def remember_font_weight(
    weight: int, environ: dict[str, str] | None = None
) -> None:
    """Persist the selected UI font weight (0 clears the override)."""
    data = _read(environ)
    if weight:
        data["font_weight"] = int(weight)
    else:
        data.pop("font_weight", None)
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


DEFAULT_SYNC_PORT = 8787


def sync_enabled(environ: dict[str, str] | None = None) -> bool:
    """Whether the LAN sync endpoint should start with the app."""
    value = _read(environ).get("sync_enabled")
    if isinstance(value, bool):
        return value
    return True


def remember_sync_enabled(enabled: bool, environ: dict[str, str] | None = None) -> None:
    data = _read(environ)
    data["sync_enabled"] = bool(enabled)
    _write(data, environ)


def sync_port(environ: dict[str, str] | None = None) -> int:
    """The port the phone companion connects to, defaulting to 8787."""
    value = _read(environ).get("sync_port")
    try:
        port = int(value)
    except (TypeError, ValueError):
        return DEFAULT_SYNC_PORT
    return port if 1 <= port <= 65535 else DEFAULT_SYNC_PORT


def remember_sync_port(port: int, environ: dict[str, str] | None = None) -> None:
    data = _read(environ)
    data["sync_port"] = int(port)
    _write(data, environ)


def sync_token(environ: dict[str, str] | None = None) -> str:
    """Return the shared LAN token, generating and saving one on first use."""
    data = _read(environ)
    value = data.get("sync_token")
    if isinstance(value, str) and len(value.strip()) >= 16:
        return value.strip()
    token = secrets.token_urlsafe(24)
    data["sync_token"] = token
    _write(data, environ)
    return token


def remember_sync_token(token: str, environ: dict[str, str] | None = None) -> None:
    data = _read(environ)
    data["sync_token"] = token.strip()
    _write(data, environ)


def _write(data: dict, environ: dict[str, str] | None = None) -> None:
    config = config_path(environ)
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config)
