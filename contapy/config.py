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
    config = config_path(environ)
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config)
