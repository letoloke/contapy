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
import re
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


FONT_WEIGHT_ROLES = ("body", "heading", "emphasis")


def font_weights_choice(
    environ: dict[str, str] | None = None,
) -> dict[str, int]:
    """Per-role UI font weights. Missing roles fall back to the theme."""
    data = _read(environ)
    weights: dict[str, int] = {}
    stored = data.get("font_weights")
    if isinstance(stored, dict):
        for role in FONT_WEIGHT_ROLES:
            try:
                value = int(stored.get(role, 0))
            except (TypeError, ValueError):
                continue
            if 100 <= value <= 900:
                weights[role] = value
    # Older configs stored one weight for every role.
    try:
        legacy = int(data.get("font_weight"))
    except (TypeError, ValueError):
        legacy = 0
    if 100 <= legacy <= 900:
        for role in FONT_WEIGHT_ROLES:
            weights.setdefault(role, legacy)
    return weights


def font_weight_choice(
    environ: dict[str, str] | None = None, role: str = "body"
) -> int:
    """The saved weight for one role, or 0 for the theme default."""
    return font_weights_choice(environ).get(role, 0)


def remember_font_weights(
    weights: dict[str, int], environ: dict[str, str] | None = None
) -> None:
    """Persist the per-role UI font weights."""
    data = _read(environ)
    stored: dict[str, int] = {}
    for role in FONT_WEIGHT_ROLES:
        try:
            value = int(weights.get(role, 0))
        except (TypeError, ValueError):
            continue
        if 100 <= value <= 900:
            stored[role] = value
    if stored:
        data["font_weights"] = stored
    else:
        data.pop("font_weights", None)
    data.pop("font_weight", None)
    _write(data, environ)


def remember_font_weight(
    weight: int,
    environ: dict[str, str] | None = None,
    role: str = "body",
) -> None:
    """Persist the weight for one role (0 clears it)."""
    weights = font_weights_choice(environ)
    value = int(weight or 0)
    if 100 <= value <= 900:
        weights[role] = value
    else:
        weights.pop(role, None)
    remember_font_weights(weights, environ)


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


# ---------------------------------------------------------------- frame colors
FRAME_PANEL_KEYS = ("accounts", "spending", "revenue", "scheduled", "budgets")
FRAME_MODES = ("theme", "single", "custom")

# Built-in per-panel outline colors ("theme" mode).
DEFAULT_FRAME_COLORS: dict[str, str] = {
    "accounts": "#ba72cf",
    "spending": "#d2666e",
    "revenue": "#d2666e",
    "scheduled": "#579bd2",
    "budgets": "#58c98a",
}

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{6})$")


def _valid_color(value) -> str:
    if isinstance(value, str):
        text = value.strip()
        if _HEX_COLOR.fullmatch(text):
            return text.lower()
    return ""


def frame_color_settings(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    """The saved panel-frame color preference."""
    raw = _read(environ).get("frame_colors")
    mode = "theme"
    single = ""
    panels: dict[str, str] = {}
    if isinstance(raw, dict):
        candidate = raw.get("mode")
        if candidate in FRAME_MODES:
            mode = candidate
        single = _valid_color(raw.get("single"))
        stored = raw.get("panels")
        if isinstance(stored, dict):
            for key in FRAME_PANEL_KEYS:
                color = _valid_color(stored.get(key))
                if color:
                    panels[key] = color
    return {"mode": mode, "single": single, "panels": panels}


def remember_frame_colors(
    settings: dict[str, object], environ: dict[str, str] | None = None
) -> None:
    """Persist the panel-frame color preference."""
    mode = settings.get("mode")
    if mode not in FRAME_MODES:
        mode = "theme"
    stored_panels: dict[str, str] = {}
    raw_panels = settings.get("panels")
    if isinstance(raw_panels, dict):
        for key in FRAME_PANEL_KEYS:
            color = _valid_color(raw_panels.get(key))
            if color:
                stored_panels[key] = color
    data = _read(environ)
    data["frame_colors"] = {
        "mode": mode,
        "single": _valid_color(settings.get("single")),
        "panels": stored_panels,
    }
    _write(data, environ)


def resolved_frame_colors(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """The effective outline color for every dashboard panel."""
    settings = frame_color_settings(environ)
    if settings["mode"] == "single" and settings["single"]:
        return {key: settings["single"] for key in FRAME_PANEL_KEYS}
    if settings["mode"] == "custom":
        merged = dict(DEFAULT_FRAME_COLORS)
        merged.update(settings["panels"])
        return merged
    return dict(DEFAULT_FRAME_COLORS)


# ---------------------------------------------------------------- chart style
CHART_STYLES = ("donut", "pie", "bars")


def chart_style_choice(environ: dict[str, str] | None = None) -> str:
    """The saved Top Spending chart style."""
    value = _read(environ).get("chart_style")
    if isinstance(value, str) and value.strip().lower() in CHART_STYLES:
        return value.strip().lower()
    return "donut"


def remember_chart_style(
    style: str, environ: dict[str, str] | None = None
) -> None:
    value = style.strip().lower()
    if value not in CHART_STYLES:
        value = "donut"
    data = _read(environ)
    data["chart_style"] = value
    _write(data, environ)


def _write(data: dict, environ: dict[str, str] | None = None) -> None:
    config = config_path(environ)
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(config)
