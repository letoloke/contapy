"""Tests for the small config file that remembers the last database."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contapy.config import config_path, last_database, remember_database


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


if __name__ == "__main__":
    unittest.main()
