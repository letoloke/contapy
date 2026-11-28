"""Tests for the small config file that remembers the last database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contapy.config import (
    CHART_STYLES,
    DEFAULT_FRAME_COLORS,
    DEFAULT_LEDGER_STATUS,
    DEFAULT_STRIP_ORDER,
    FRAME_PANEL_KEYS,
    STRIP_TABS,
    category_color_overrides,
    chart_style_choice,
    config_path,
    date_format_choice,
    font_family_choice,
    font_weight_choice,
    font_weights_choice,
    frame_color_settings,
    last_database,
    ledger_status_choice,
    remember_category_colors,
    remember_chart_style,
    remember_database,
    remember_date_format,
    remember_font_family,
    remember_font_weight,
    remember_font_weights,
    remember_frame_colors,
    remember_ledger_status,
    remember_strip_tab_order,
    remember_theme,
    resolved_frame_colors,
    strip_tab_order,
    theme_choice,
)
from contapy.dates import DEFAULT_DATE_FORMAT
from contapy.omarchy import DEFAULT_THEME


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {"XDG_CONFIG_HOME": str(self.root / "config")}

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_config_path_honours_xdg_config_home(self) -> None:
        self.assertEqual(
            config_path(self.env),
            self.root / "config" / "contapy" / "config.json",
        )

    def test_missing_config_returns_none(self) -> None:
        self.assertIsNone(last_database(self.env))

    def test_remember_and_read_back(self) -> None:
        database = self.root / "books" / "mi contapy.db"
        remember_database(database, self.env)
        self.assertEqual(last_database(self.env), database.resolve())
        self.assertEqual(
            config_path(self.env).read_text(encoding="utf-8"),
            '{\n  "database": "%s"\n}\n' % database.resolve(),
        )

    def test_remember_overwrites_previous_choice(self) -> None:
        first = self.root / "first.db"
        second = self.root / "second.db"
        remember_database(first, self.env)
        remember_database(second, self.env)
        self.assertEqual(last_database(self.env), second.resolve())

    def test_font_family_and_weight_round_trip(self) -> None:
        self.assertEqual(font_family_choice(self.env), "")
        self.assertEqual(font_weight_choice(self.env), 0)
        remember_font_family("JetBrains Mono", self.env)
        remember_font_weight(300, self.env)
        self.assertEqual(font_family_choice(self.env), "JetBrains Mono")
        self.assertEqual(font_weight_choice(self.env), 300)
        remember_font_family("", self.env)
        remember_font_weight(0, self.env)
        self.assertEqual(font_family_choice(self.env), "")
        self.assertEqual(font_weight_choice(self.env), 0)

    def test_font_weight_outside_range_falls_back_to_default(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"font_weight": 1200}', encoding="utf-8")
        self.assertEqual(font_weight_choice(self.env), 0)
        config.write_text('{"font_weight": "heavy"}', encoding="utf-8")
        self.assertEqual(font_weight_choice(self.env), 0)

    def test_font_weights_are_stored_per_role(self) -> None:
        remember_font_weights(
            {"body": 300, "heading": 500, "emphasis": 700}, self.env
        )
        self.assertEqual(
            font_weights_choice(self.env),
            {"body": 300, "heading": 500, "emphasis": 700},
        )
        self.assertEqual(font_weight_choice(self.env, "heading"), 500)
        remember_font_weight(400, self.env, role="heading")
        self.assertEqual(font_weight_choice(self.env, "heading"), 400)
        self.assertEqual(font_weight_choice(self.env, "body"), 300)

    def test_legacy_single_weight_applies_to_every_role(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"font_weight": 300}', encoding="utf-8")
        self.assertEqual(
            font_weights_choice(self.env),
            {"body": 300, "heading": 300, "emphasis": 300},
        )

    def test_frame_colors_default_to_theme_colors(self) -> None:
        self.assertEqual(resolved_frame_colors(self.env), DEFAULT_FRAME_COLORS)
        self.assertEqual(DEFAULT_FRAME_COLORS["spending"], "#d2666e")
        self.assertEqual(DEFAULT_FRAME_COLORS["revenue"], "#d2666e")

    def test_single_frame_color_applies_to_every_panel(self) -> None:
        remember_frame_colors(
            {"mode": "single", "single": "#123456", "panels": {}}, self.env
        )
        expected = {key: "#123456" for key in FRAME_PANEL_KEYS}
        self.assertEqual(resolved_frame_colors(self.env), expected)

    def test_custom_frame_colors_merge_with_defaults(self) -> None:
        remember_frame_colors(
            {
                "mode": "custom",
                "single": "",
                "panels": {"accounts": "#ABCDEF"},
            },
            self.env,
        )
        colors = resolved_frame_colors(self.env)
        self.assertEqual(colors["accounts"], "#abcdef")
        self.assertEqual(colors["budgets"], DEFAULT_FRAME_COLORS["budgets"])

    def test_invalid_frame_colors_are_ignored(self) -> None:
        remember_frame_colors(
            {
                "mode": "custom",
                "single": "red",
                "panels": {"accounts": "nope"},
            },
            self.env,
        )
        self.assertEqual(frame_color_settings(self.env)["mode"], "custom")
        self.assertEqual(
            resolved_frame_colors(self.env)["accounts"],
            DEFAULT_FRAME_COLORS["accounts"],
        )

    def test_chart_style_defaults_and_round_trips(self) -> None:
        self.assertEqual(chart_style_choice(self.env), "donut")
        for style in CHART_STYLES:
            remember_chart_style(style, self.env)
            self.assertEqual(chart_style_choice(self.env), style)
        remember_chart_style("treemap", self.env)
        self.assertEqual(chart_style_choice(self.env), "donut")

    def test_category_color_overrides_round_trip(self) -> None:
        self.assertEqual(category_color_overrides(self.env), {})
        remember_category_colors(
            {"renta": "#ABCDEF", "bad": "not-a-color"}, self.env
        )
        self.assertEqual(
            category_color_overrides(self.env), {"renta": "#abcdef"}
        )
        remember_category_colors({}, self.env)
        self.assertEqual(category_color_overrides(self.env), {})

    def test_strip_tab_order_defaults_to_remind_first(self) -> None:
        self.assertEqual(strip_tab_order(self.env), list(DEFAULT_STRIP_ORDER))
        remember_strip_tab_order(
            ["Future", "Remind", "Scheduled"], self.env
        )
        self.assertEqual(
            strip_tab_order(self.env), ["Future", "Remind", "Scheduled"]
        )
        remember_strip_tab_order(["Remind", "Remind", "Bogus"], self.env)
        order = strip_tab_order(self.env)
        self.assertEqual(order[0], "Remind")
        self.assertEqual(set(order), set(STRIP_TABS))

    def test_corrupt_config_returns_none(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text("not json", encoding="utf-8")
        self.assertIsNone(last_database(self.env))

    def test_non_database_json_returns_none(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"database": 42}', encoding="utf-8")
        self.assertIsNone(last_database(self.env))

    def test_blank_database_returns_none(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"database": "   "}', encoding="utf-8")
        self.assertIsNone(last_database(self.env))

    def test_theme_defaults_to_the_branch_default(self) -> None:
        self.assertEqual(theme_choice(self.env), DEFAULT_THEME)

    def test_remember_theme_round_trip(self) -> None:
        remember_theme("tokyo-night", self.env)
        self.assertEqual(theme_choice(self.env), "tokyo-night")

    def test_blank_saved_theme_falls_back_to_the_default(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"theme": "  "}', encoding="utf-8")
        self.assertEqual(theme_choice(self.env), DEFAULT_THEME)

    def test_date_format_defaults_to_year_slash_month_slash_day(self) -> None:
        self.assertEqual(date_format_choice(self.env), DEFAULT_DATE_FORMAT)
        self.assertEqual(date_format_choice(self.env), "yyyy/mmm/dd")

    def test_remember_date_format_round_trip(self) -> None:
        remember_date_format("dd/mm/yyyy", self.env)
        self.assertEqual(date_format_choice(self.env), "dd/mm/yyyy")

    def test_invalid_saved_date_format_falls_back_to_default(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"date_format": "sideways"}', encoding="utf-8")
        self.assertEqual(date_format_choice(self.env), DEFAULT_DATE_FORMAT)

    def test_ledger_status_defaults_to_any(self) -> None:
        self.assertEqual(ledger_status_choice(self.env), DEFAULT_LEDGER_STATUS)
        self.assertEqual(ledger_status_choice(self.env), "any")

    def test_remember_ledger_status_round_trip(self) -> None:
        remember_ledger_status("unreconciled", self.env)
        self.assertEqual(ledger_status_choice(self.env), "unreconciled")

    def test_invalid_saved_ledger_status_falls_back_to_any(self) -> None:
        config = config_path(self.env)
        config.parent.mkdir(parents=True)
        config.write_text('{"ledger_status": "exploded"}', encoding="utf-8")
        self.assertEqual(ledger_status_choice(self.env), "any")


if __name__ == "__main__":
    unittest.main()
