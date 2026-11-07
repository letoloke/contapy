"""Headless tests for Omarchy palette loading and token derivation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contapy.omarchy import (
    FALLBACK_TOKENS,
    contrast,
    load_palette,
    parse_colors,
    read_colors,
    theme_path,
    tokens_from_colors,
)

DARK = """
mode = "dark"
accent = "#61afef"
selection = "#3e4451"
background = "#282c34"
dark_background = "#21252b"
darker_background = "#1b1e24"
lighter_background = "#333842"
foreground = "#abb2bf"
dark_foreground = "#5c6370"
light_foreground = "#c5cbd6"
bright_foreground = "#dcdfe4"
red = "#e06c75"
yellow = "#e5c07b"
orange = "#d19a66"
green = "#98c379"
cyan = "#56b6c2"
blue = "#61afef"
magenta = "#c678dd"
brown = "#be5046"
"""

LIGHT = """
mode = "light"
accent = "#1e66f5"
selection = "#ccd0da"
background = "#eff1f5"
dark_background = "#e3e4e8"
darker_background = "#d7d8dc"
lighter_background = "#dce0e8"
foreground = "#4c4f69"
light_foreground = "#5c5f77"
bright_foreground = "#4c4f69"
red = "#d20f39"
yellow = "#df8e1d"
orange = "#d84e2b"
green = "#40a02b"
cyan = "#179299"
blue = "#1e66f5"
magenta = "#ea76cb"
brown = "#6c2715"
"""


class PaletteParsingTests(unittest.TestCase):
    def test_parse_colors_reads_toml(self) -> None:
        colors = parse_colors(DARK)
        self.assertEqual(colors["background"], "#282c34")
        self.assertEqual(colors["mode"], "dark")

    def test_parse_colors_falls_back_for_malformed_toml(self) -> None:
        colors = parse_colors(
            'mode: "light"\nbackground: "#eff1f5"\nforeground: "#4c4f69"\n'
        )
        self.assertEqual(colors["mode"], "light")
        self.assertEqual(colors["background"], "#eff1f5")

    def test_read_colors_normalizes_short_hex_and_rejects_missing_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "colors.toml"
            path.write_text('background = "#abc"\nforeground = "#123456"\n')
            colors = read_colors(path)
            self.assertEqual(colors["background"], "#aabbcc")
            self.assertEqual(colors["foreground"], "#123456")

            path.write_text('foreground = "#123456"\n')
            self.assertIsNone(read_colors(path))

    def test_theme_path_honours_xdg_state_home(self) -> None:
        path = theme_path({"XDG_STATE_HOME": "/tmp/state"})
        self.assertEqual(
            path, Path("/tmp/state/omarchy/current/theme/colors.toml")
        )

    def test_theme_path_honours_explicit_file(self) -> None:
        path = theme_path({"CONTAPY_THEME_FILE": "/tmp/my-theme/colors.toml"})
        self.assertEqual(path, Path("/tmp/my-theme/colors.toml"))


class PaletteTokenTests(unittest.TestCase):
    def test_dark_tokens_come_from_omarchy(self) -> None:
        tokens = tokens_from_colors(parse_colors(DARK))
        self.assertEqual(tokens["BG"], "#282c34")
        self.assertEqual(tokens["PANEL"], "#21252b")
        self.assertEqual(tokens["ACCENT"], "#61afef")
        self.assertEqual(tokens["GREEN"], "#98c379")
        self.assertEqual(tokens["ORANGE"], "#d19a66")
        self.assertGreaterEqual(contrast(tokens["TEXT"], tokens["BG"]), 4.5)
        self.assertGreaterEqual(contrast(tokens["ROW_SELECTED_TEXT"], tokens["ROW_SELECTED"]), 4.5)
        self.assertGreaterEqual(contrast(tokens["ON_ACCENT"], tokens["ACCENT"]), 4.5)

    def test_light_theme_is_detected_and_readable(self) -> None:
        tokens = tokens_from_colors(parse_colors(LIGHT))
        self.assertEqual(tokens["BG"], "#eff1f5")
        self.assertEqual(tokens["PANEL"], "#e3e4e8")
        # A light theme must not keep white-on-light selection text.
        self.assertGreaterEqual(contrast(tokens["TEXT"], tokens["BG"]), 4.5)
        self.assertGreaterEqual(contrast(tokens["ROW_SELECTED_TEXT"], tokens["ROW_SELECTED"]), 4.5)
        self.assertGreaterEqual(contrast(tokens["ON_ACCENT"], tokens["ACCENT"]), 4.5)

    def test_mode_can_be_inferred_without_a_mode_key(self) -> None:
        light = parse_colors(LIGHT)
        light.pop("mode")
        self.assertEqual(tokens_from_colors(light)["BG"], "#eff1f5")
        dark = parse_colors(DARK)
        dark.pop("mode")
        self.assertEqual(tokens_from_colors(dark)["BG"], "#282c34")

    def test_load_palette_uses_builtin_without_omarchy(self) -> None:
        palette = load_palette(
            {"CONTAPY_THEME_FILE": "/nonexistent/colors.toml"}
        )
        self.assertIn("built-in", palette.source)
        self.assertEqual(palette.tokens["BG"], FALLBACK_TOKENS["BG"])

    def test_load_palette_can_force_builtin(self) -> None:
        palette = load_palette({"CONTAPY_THEME": "builtin"})
        self.assertEqual(palette.source, "built-in")
        self.assertEqual(palette.tokens["ACCENT"], FALLBACK_TOKENS["ACCENT"])

    def test_load_palette_reads_an_explicit_theme_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "colors.toml"
            path.write_text(DARK)
            palette = load_palette({"CONTAPY_THEME_FILE": str(path)})
            self.assertEqual(palette.mode, "dark")
            self.assertEqual(palette.tokens["BG"], "#282c34")
            self.assertEqual(palette.category_colors["renta"], "#61afef")
            self.assertIn("#61afef", palette.donut_colors)

    def test_light_theme_bright_roles_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "colors.toml"
            path.write_text(LIGHT)
            palette = load_palette({"CONTAPY_THEME_FILE": str(path)})
            self.assertNotEqual(
                palette.category_colors["manto"],
                palette.category_colors["comision"],
            )
            self.assertGreaterEqual(len(palette.donut_colors), 8)


if __name__ == "__main__":
    unittest.main()
