"""Read the active Omarchy colour scheme.

ContaPy follows the desktop's current Omarchy theme by reading
``~/.local/state/omarchy/current/theme/colors.toml`` at startup.  The palette
covers both dark and light themes; when Omarchy (or that file) is absent the
app falls back to its original built-in palette.

Environment overrides:

``CONTAPY_THEME=builtin``
    Ignore Omarchy and always use the built-in palette.
``CONTAPY_THEME_FILE=/path/to/colors.toml``
    Read a specific Omarchy palette file (useful for testing themes).

This module deliberately has no Qt imports so the database and seed layers can
use it too.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older Pythons
    tomllib = None  # type: ignore[assignment]


# --------------------------------------------------------------- palette data
# The original ContaPy palette.  Used verbatim when Omarchy is unavailable.
FALLBACK_TOKENS: dict[str, str] = {
    "BG": "#333333",
    "PANEL": "#2b2b2b",
    "PANEL_RAISED": "#303030",
    "HEADER": "#2b2b2b",
    "BORDER": "#1b1b1b",
    "BORDER_SOFT": "#3b3b3b",
    "GRID": "#3a3a3a",
    "GRID_ZERO": "#4d4d4d",
    "TEXT": "#efefef",
    "TEXT_SOFT": "#d8d8d8",
    "MUTED": "#9c9c9c",
    "MUTED_DARK": "#7c7c7c",
    "TITLE": "#dedede",
    "ACCENT": "#24518d",
    "ACCENT_LIGHT": "#2e5f9e",
    "ACCENT_HOVER": "#2c5f9f",
    "GREEN": "#4e9f3f",
    "GREEN_BAR": "#5c9736",
    "ORANGE": "#d9822b",
    "RED_BAR": "#b0292b",
    "WARNING": "#e5a93f",
    "INFO": "#3f7fbf",
    "ROW_HOVER": "#363636",
    "ROW_SELECTED": "#24518d",
    "ROW_SELECTED_TEXT": "#ffffff",
    "TOTAL_ROW": "#2e2e2e",
    "ALT_ROW": "#2e2e2e",
    "INPUT_BG": "#242424",
    "INPUT_TEXT": "#ededed",
    "INPUT_BORDER": "#4a4a4a",
    "FOCUS_BORDER": "#4a7fc4",
    "BUTTON_BG": "#363636",
    "BUTTON_BG_HOVER": "#3f3f3f",
    "BUTTON_BG_PRESSED": "#474747",
    "BUTTON_TEXT": "#e7e7e7",
    "BUTTON_BORDER": "#4b4b4b",
    "BUTTON_PRIMARY_BORDER": "#3a6cae",
    "ACTION_BG": "#343434",
    "ACTION_BG_HOVER": "#3e3e3e",
    "ACTION_BORDER": "#505050",
    "ACTION_TEXT": "#d6d6d6",
    "MENU_BG": "#2b2b2b",
    "MENU_BORDER": "#474747",
    "MENU_TEXT": "#e6e6e6",
    "MENU_SELECTED": "#24518d",
    "MENU_SELECTED_TEXT": "#ffffff",
    "MENU_SEPARATOR": "#3d3d3d",
    "MENUBAR_HOVER": "#414141",
    "TOOLTIP_BG": "#1f1f1f",
    "TOOLTIP_TEXT": "#f0f0f0",
    "TOOLTIP_BORDER": "#454545",
    "SELECTION": "#24518d",
    "SELECTION_TEXT": "#ffffff",
    "ON_ACCENT": "#ffffff",
    "ON_GREEN": "#ffffff",
    "ON_RECONCILED": "#ffffff",
    "SEPARATOR": "#454545",
    "DISABLED": "#6f6f6f",
    "DISABLED_BG": "#303030",
    "DISABLED_BORDER": "#3e3e3e",
    "SCROLL_HANDLE": "#4a4a4a",
    "SCROLL_HANDLE_HOVER": "#575757",
    "CHECK_BG": "#242424",
    "CHECK_BORDER": "#555555",
    "CHECK_HOVER": "#6d6d6d",
    "LIST_BG": "#242424",
    "LIST_BORDER": "#444444",
    "POPUP_BG": "#2b2b2b",
    "POPUP_BORDER": "#4a4a4a",
    "POPUP_TEXT": "#e8e8e8",
    "TAB_HOVER": "#414141",
    "TAB_ACTIVE_BG": "#1e1e1e",
    "CATEGORY_TEXT": "#b8b8b8",
    "CATEGORY_MUTED": "#7f7f7f",
    "RECONCILED": "#3f8f7a",
    "FUTURE": "#6aa2d8",
    "CALENDAR_FG": "#e8f2df",
    "AMOUNT": "#c9c9c9",
    "WARNING_TEXT": "#2b2b2b",
}

FALLBACK_CATEGORY_COLORS: dict[str, str] = {
    "renta": "#4571a6",
    "nomina": "#acbdce",
    "Retiro de efectivo": "#d87921",
    "Impuestos": "#e4b276",
    "suscripciones": "#5c9736",
    "alimentos": "#aecf96",
    "manto": "#b0292b",
    "comision": "#dc9193",
    "servicios": "#7d64ac",
    "bebes": "#b5a6cb",
    "Other": "#77544d",
    "Ingresos": "#5c9736",
}

FALLBACK_DONUT_COLORS: list[str] = [
    "#4571a6",
    "#acbdce",
    "#d87921",
    "#e4b276",
    "#5c9736",
    "#aecf96",
    "#b0292b",
    "#dc9193",
    "#7d64ac",
    "#b5a6cb",
    "#77544d",
]

# Seed category -> Omarchy colour role.
CATEGORY_KEYS: dict[str, str] = {
    "renta": "blue",
    "nomina": "cyan",
    "Retiro de efectivo": "orange",
    "Impuestos": "yellow",
    "suscripciones": "green",
    "alimentos": "bright_green",
    "manto": "red",
    "comision": "bright_red",
    "servicios": "magenta",
    "bebes": "bright_magenta",
    "Other": "brown",
    "Ingresos": "green",
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_HEX_PAIR_RE = re.compile(
    r"""^\s*["']?([A-Za-z_][\w-]*)["']?\s*[=:]\s*["']?(#[0-9a-fA-F]{3,8})["']?\s*(?:#.*)?$"""
)


@dataclass(frozen=True)
class Palette:
    """The resolved colour tokens for one theme."""

    mode: str
    source: str
    tokens: dict[str, str] = field(default_factory=dict)
    category_colors: dict[str, str] = field(default_factory=dict)
    donut_colors: list[str] = field(default_factory=list)

    @property
    def is_light(self) -> bool:
        return self.mode == "light"


# --------------------------------------------------------------- colour maths
def normalize_hex(value: str) -> str | None:
    """Return a lowercase ``#rrggbb`` value, expanding short hex, or ``None``."""
    value = value.strip()
    if not _HEX_RE.match(value):
        return None
    value = value.lower()
    if len(value) == 4:
        value = "#" + "".join(char * 2 for char in value[1:])
    return value


def rgb(value: str) -> tuple[int, int, int]:
    value = normalize_hex(value) or "#000000"
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def hexcolor(red: float, green: float, blue: float) -> str:
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(red)))),
        max(0, min(255, int(round(green)))),
        max(0, min(255, int(round(blue)))),
    )


def mix(first: str, second: str, amount: float) -> str:
    """Blend ``first`` toward ``second``; ``amount`` is clamped to 0..1."""
    amount = max(0.0, min(1.0, amount))
    a, b = rgb(first), rgb(second)
    return hexcolor(
        a[0] + (b[0] - a[0]) * amount,
        a[1] + (b[1] - a[1]) * amount,
        a[2] + (b[2] - a[2]) * amount,
    )


def luminance(value: str) -> float:
    """Relative luminance (WCAG) of a hex colour."""
    channels = []
    for channel in rgb(value):
        channel /= 255.0
        channels.append(
            channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    hi, lo = sorted((luminance(first), luminance(second)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def best_text(background: str, candidates: list[str]) -> str:
    """Pick the candidate with the highest contrast against ``background``."""
    return max(candidates, key=lambda color: contrast(background, color))


def text_on(background: str, preferred: str, candidates: list[str]) -> str:
    """Use ``preferred`` when it is readable, otherwise the best alternative."""
    if contrast(background, preferred) >= 4.5:
        return preferred
    return best_text(background, [preferred, *candidates])


def _mode(colors: dict[str, str]) -> str:
    declared = (colors.get("mode") or "").strip().lower()
    if declared in ("dark", "light"):
        return declared
    return "light" if luminance(colors.get("background", "#000000")) > 0.5 else "dark"


# ----------------------------------------------------------------- file input
def parse_colors(text: str) -> dict[str, str]:
    """Parse an Omarchy ``colors.toml`` payload.

    Uses ``tomllib`` where available and a small line parser as a fallback so
    a slightly malformed theme still yields usable colours.
    """
    parsed: dict[str, str] = {}
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
            for key, value in data.items():
                if isinstance(value, str):
                    parsed[key] = value
            if parsed:
                return parsed
        except Exception:
            parsed.clear()

    for line in text.splitlines():
        match = _HEX_PAIR_RE.match(line)
        if match:
            parsed[match.group(1)] = match.group(2)
        elif "=" in line or ":" in line:
            separator = "=" if "=" in line else ":"
            key, _, value = line.partition(separator)
            value = value.strip().strip("\"'")
            if value.lower() in ("dark", "light"):
                parsed[key.strip().strip("\"'")] = value.lower()
    return parsed


def read_colors(path: str | Path) -> dict[str, str] | None:
    """Read a palette file, returning normalized colours or ``None``."""
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    raw = parse_colors(text)
    colors: dict[str, str] = {}
    for key, value in raw.items():
        if key == "mode":
            if value.lower() in ("dark", "light"):
                colors[key] = value.lower()
            continue
        normalized = normalize_hex(value)
        if normalized:
            colors[key] = normalized
    if not colors.get("background"):
        return None
    return colors


def theme_path(environ: dict[str, str] | None = None) -> Path:
    """Location of the active Omarchy ``colors.toml``."""
    env = os.environ if environ is None else environ
    override = env.get("CONTAPY_THEME_FILE")
    if override:
        path = Path(override).expanduser()
        return path / "colors.toml" if path.is_dir() else path
    state_home = env.get("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return base / "omarchy" / "current" / "theme" / "colors.toml"


# ------------------------------------------------------------- token builder
def _pick(colors: dict[str, str], key: str) -> str | None:
    return colors.get(key) or colors.get(key.replace("bright_", ""))


def tokens_from_colors(colors: dict[str, str]) -> dict[str, str]:
    """Translate an Omarchy palette into ContaPy's semantic tokens."""
    mode = _mode(colors)
    is_dark = mode == "dark"
    toward = "#ffffff" if is_dark else "#000000"

    fallback_bg = FALLBACK_TOKENS["BG"]
    bg = colors.get("background", fallback_bg)
    panel = colors.get("dark_background") or mix(bg, toward, 0.05)
    darker = colors.get("darker_background") or mix(panel, toward, 0.05)
    lighter = colors.get("lighter_background") or mix(bg, toward, 0.07)

    text = colors.get("foreground", FALLBACK_TOKENS["TEXT"])
    text_soft = colors.get("light_foreground") or text
    bright = colors.get("bright_foreground") or text_soft
    accent = colors.get("accent", FALLBACK_TOKENS["ACCENT"])
    selection = colors.get("selection") or mix(panel, accent, 0.35)
    green = _pick(colors, "green") or FALLBACK_TOKENS["GREEN"]
    orange = _pick(colors, "orange") or FALLBACK_TOKENS["ORANGE"]
    red = _pick(colors, "red") or FALLBACK_TOKENS["RED_BAR"]
    yellow = _pick(colors, "yellow") or FALLBACK_TOKENS["WARNING"]
    blue = _pick(colors, "blue") or accent
    cyan = _pick(colors, "cyan") or green

    muted = mix(text, bg, 0.26)
    muted_dark = mix(text, bg, 0.44)
    border = darker
    border_soft = mix(bg, text, 0.16)
    button_border = mix(bg, text, 0.24)
    row_hover = lighter
    total_row = mix(panel, bg, 0.45)
    alt_row = mix(panel, lighter, 0.35)
    input_bg = darker
    tooltip_bg = darker
    disabled = mix(muted, bg, 0.42)
    disabled_bg = mix(panel, bg, 0.30)
    disabled_border = mix(border, bg, 0.35)
    scroll_handle = mix(text, bg, 0.70)
    scroll_hover = mix(text, bg, 0.58)
    reconciled = mix(green, cyan, 0.55)
    on_accent = text_on(accent, "#ffffff", [bg, "#000000"])
    on_green = text_on(green, "#ffffff", [bg, "#000000"])
    on_reconciled = text_on(reconciled, "#ffffff", [bg, "#000000"])
    selection_text = text_on(selection, text, [bright, bg, "#ffffff", "#000000"])

    accent_light = mix(accent, toward, 0.18)
    accent_hover = mix(accent, toward, 0.10)
    button_bg = lighter
    button_hover = mix(button_bg, toward, 0.10)
    button_pressed = mix(button_bg, toward, 0.18)
    action_bg = mix(panel, bg, 0.45)
    action_hover = mix(action_bg, toward, 0.08)

    return {
        "BG": bg,
        "PANEL": panel,
        "PANEL_RAISED": lighter,
        "HEADER": panel,
        "BORDER": border,
        "BORDER_SOFT": border_soft,
        "GRID": mix(bg, text, 0.18),
        "GRID_ZERO": mix(bg, text, 0.32),
        "TEXT": text,
        "TEXT_SOFT": text_soft,
        "MUTED": muted,
        "MUTED_DARK": muted_dark,
        "TITLE": bright,
        "ACCENT": accent,
        "ACCENT_LIGHT": accent_light,
        "ACCENT_HOVER": accent_hover,
        "GREEN": green,
        "GREEN_BAR": green,
        "ORANGE": orange,
        "RED_BAR": red,
        "WARNING": yellow,
        "INFO": blue,
        "ROW_HOVER": row_hover,
        "ROW_SELECTED": selection,
        "ROW_SELECTED_TEXT": selection_text,
        "TOTAL_ROW": total_row,
        "ALT_ROW": alt_row,
        "INPUT_BG": input_bg,
        "INPUT_TEXT": text,
        "INPUT_BORDER": button_border,
        "FOCUS_BORDER": accent,
        "BUTTON_BG": button_bg,
        "BUTTON_BG_HOVER": button_hover,
        "BUTTON_BG_PRESSED": button_pressed,
        "BUTTON_TEXT": text,
        "BUTTON_BORDER": button_border,
        "BUTTON_PRIMARY_BORDER": accent_light,
        "ACTION_BG": action_bg,
        "ACTION_BG_HOVER": action_hover,
        "ACTION_BORDER": button_border,
        "ACTION_TEXT": text_soft,
        "MENU_BG": panel,
        "MENU_BORDER": border_soft,
        "MENU_TEXT": text,
        "MENU_SELECTED": accent,
        "MENU_SELECTED_TEXT": on_accent,
        "MENU_SEPARATOR": border_soft,
        "MENUBAR_HOVER": row_hover,
        "TOOLTIP_BG": tooltip_bg,
        "TOOLTIP_TEXT": bright,
        "TOOLTIP_BORDER": border_soft,
        "SELECTION": selection,
        "SELECTION_TEXT": selection_text,
        "ON_ACCENT": on_accent,
        "ON_GREEN": on_green,
        "ON_RECONCILED": on_reconciled,
        "SEPARATOR": border_soft,
        "DISABLED": disabled,
        "DISABLED_BG": disabled_bg,
        "DISABLED_BORDER": disabled_border,
        "SCROLL_HANDLE": scroll_handle,
        "SCROLL_HANDLE_HOVER": scroll_hover,
        "CHECK_BG": input_bg,
        "CHECK_BORDER": button_border,
        "CHECK_HOVER": mix(button_border, text, 0.22),
        "LIST_BG": input_bg,
        "LIST_BORDER": button_border,
        "POPUP_BG": panel,
        "POPUP_BORDER": button_border,
        "POPUP_TEXT": text,
        "TAB_HOVER": row_hover,
        "TAB_ACTIVE_BG": input_bg,
        "CATEGORY_TEXT": text_soft,
        "CATEGORY_MUTED": muted_dark,
        "RECONCILED": reconciled,
        "FUTURE": blue,
        "CALENDAR_FG": on_green,
        "AMOUNT": text_soft,
        "WARNING_TEXT": text_on(yellow, bg, ["#000000", "#ffffff"]),
    }


def categories_from_colors(colors: dict[str, str], tokens: dict[str, str]) -> dict[str, str]:
    """Map the seeded categories to roles in the active Omarchy palette."""
    result: dict[str, str] = {}
    for name, key in CATEGORY_KEYS.items():
        value = colors.get(key)
        if value is None and key.startswith("bright_"):
            base = colors.get(key.removeprefix("bright_"))
            if base:
                value = mix(base, tokens["BG"], 0.25)
        if value is None:
            value = _pick(colors, key)
        if value is None:
            value = tokens.get("TEXT_SOFT", FALLBACK_TOKENS["TEXT_SOFT"])
        result[name] = value
    # Keep unknown-but-known names stable if Omarchy omits a specific role.
    for name, value in FALLBACK_CATEGORY_COLORS.items():
        result.setdefault(name, value)
    return result


def donut_from_categories(category_colors: dict[str, str]) -> list[str]:
    ordered = [
        category_colors[name]
        for name in FALLBACK_CATEGORY_COLORS
        if name in category_colors
    ]
    seen: list[str] = []
    for color in ordered:
        if color not in seen:
            seen.append(color)
    return seen


# ------------------------------------------------------------- public loading
def _resolve(environ: dict[str, str]) -> Palette:
    choice = (environ.get("CONTAPY_THEME") or "omarchy").strip().lower()
    if choice in ("builtin", "default", "none", "off"):
        return Palette(
            "dark",
            "built-in",
            dict(FALLBACK_TOKENS),
            dict(FALLBACK_CATEGORY_COLORS),
            list(FALLBACK_DONUT_COLORS),
        )

    path = theme_path(environ)
    colors = read_colors(path)
    if colors is None:
        return Palette(
            "dark",
            "built-in (Omarchy theme not found)",
            dict(FALLBACK_TOKENS),
            dict(FALLBACK_CATEGORY_COLORS),
            list(FALLBACK_DONUT_COLORS),
        )

    tokens = tokens_from_colors(colors)
    categories = categories_from_colors(colors, tokens)
    return Palette(
        _mode(colors),
        str(path),
        tokens,
        categories,
        donut_from_categories(categories),
    )


_cached: Palette | None = None


def load_palette(environ: dict[str, str] | None = None) -> Palette:
    """Resolve the palette once for the process (or for a supplied environment)."""
    global _cached
    if environ is not None:
        return _resolve(environ)
    if _cached is None:
        _cached = _resolve(os.environ)
    return _cached


def reset_cache() -> None:
    """Forget the cached palette (used by tests)."""
    global _cached
    _cached = None


def theme_category_color(name: str, stored: str | None = None) -> str:
    """Colour for a category, preferring the active theme for known names."""
    palette = load_palette()
    known = palette.category_colors.get(name)
    if known:
        return known
    return stored or palette.tokens["MUTED"]
