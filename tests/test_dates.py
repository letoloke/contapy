"""Tests for the user-selectable date display format."""

from __future__ import annotations

import unittest
from datetime import date

from contapy.dates import (
    DATE_FORMATS,
    DEFAULT_DATE_FORMAT,
    current_date_format,
    format_date,
    qt_date_format,
    set_date_format,
)


class DateFormatTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_date_format(DEFAULT_DATE_FORMAT)

    def test_default_format_is_year_slash_month_slash_day(self) -> None:
        set_date_format(DEFAULT_DATE_FORMAT)
        self.assertEqual(current_date_format(), "yyyy/mmm/dd")
        self.assertEqual(format_date("2026-02-14"), "2026/feb/14")
        self.assertEqual(format_date(date(2026, 2, 14)), "2026/feb/14")

    def test_every_format_round_trips_a_known_date(self) -> None:
        expected = {
            "yyyy/mmm/dd": "2026/feb/14",
            "yyyy-mm-dd": "2026-02-14",
            "dd/mm/yyyy": "14/02/2026",
            "mm/dd/yyyy": "02/14/2026",
            "dd mmm yyyy": "14 feb 2026",
            "mmm dd, yyyy": "feb 14, 2026",
            "dd-mmm-yyyy": "14-feb-2026",
            "yyyy.mm.dd": "2026.02.14",
        }
        self.assertEqual(set(expected), {item.key for item in DATE_FORMATS})
        for key, text in expected.items():
            with self.subTest(key=key):
                set_date_format(key)
                self.assertEqual(format_date("2026-02-14"), text)

    def test_qt_pattern_matches_the_selected_format(self) -> None:
        set_date_format("dd/mm/yyyy")
        self.assertEqual(qt_date_format(), "dd/MM/yyyy")

    def test_unknown_format_falls_back_to_the_default(self) -> None:
        set_date_format("not-a-format")
        self.assertEqual(current_date_format(), DEFAULT_DATE_FORMAT)


if __name__ == "__main__":
    unittest.main()
