"""Tests for the Airbnb export conversion."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from contapy.airbnb import COLUMNS, transform


class AirbnbTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_source(self, rows: list[list[str]]) -> Path:
        path = self.folder / "airbnb.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "Fecha",
                    "Tipo",
                    "Código de confirmación",
                    "Fecha de inicio",
                    "Huésped",
                    "Espacio",
                    "Monto",
                ]
            )
            writer.writerows(rows)
        return path

    def read_output(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_excludes_payout_and_builds_memo(self) -> None:
        source = self.write_source(
            [
                ["11/07/2026", "Payout", "", "", "", "", ""],
                [
                    "11/07/2026",
                    "Reservación",
                    "HM3N4R3ERW",
                    "11/06/2026",
                    "Saul Stone",
                    "Fitz-Mar Quince",
                    "3260.09",
                ],
                ["11/07/2026", "Impuestos", "ABC", "11/06/2026", "", "", "-320.21"],
            ]
        )
        target = self.folder / "out.csv"

        written, excluded = transform(source, target)

        self.assertEqual((written, excluded), (2, 1))
        rows = self.read_output(target)
        self.assertEqual(list(rows[0]), COLUMNS)
        self.assertEqual(rows[0]["Fecha"], "2026-11-06")
        self.assertEqual(
            rows[0]["Memo"], "HM3N4R3ERW - Reservación - Fitz-Mar Quince - Saul Stone"
        )
        self.assertEqual(rows[0]["Importe"], "3260.09")
        self.assertEqual(rows[1]["Memo"], "ABC - Impuestos")
        self.assertEqual(rows[1]["Importe"], "-320.21")

    def test_detects_day_first_dates(self) -> None:
        source = self.write_source(
            [["25/12/2026", "Reservación", "X", "25/12/2026", "Guest", "Room", "10"]]
        )
        target = self.folder / "out.csv"

        transform(source, target)

        self.assertEqual(self.read_output(target)[0]["Fecha"], "2026-12-25")

    def test_rejects_a_non_airbnb_file(self) -> None:
        path = self.folder / "other.csv"
        path.write_text("Date,Amount\n2026-01-01,10\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            transform(path, self.folder / "out.csv")


if __name__ == "__main__":
    unittest.main()
