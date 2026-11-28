"""Tests for the small config file that remembers the last database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contapy.config import (
    DEFAULT_LEDGER_STATUS,
    config_path,
    date_format_choice,
    font_family_choice,
    font_weight_choice,
    font_weights_choice,
    last_database,
    ledger_status_choice,
    remember_database,
    remember_date_format,
    remember_font_family,
    remember_font_weight,
    remember_font_weights,
    remember_ledger_status,
    remember_theme,
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
