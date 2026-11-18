"""Tests for the alternative Airbnb transaction converter."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from contapy.airbnb_transactions import COLUMNS, transform


class AirbnbTransactionTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_source(self, rows: list[list[str]]) -> Path:
        path = self.folder / "airbnb_transactions.csv"
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
                    "Ingresos brutos",
                    "Tarifa de limpieza",
                    "Tarifa de servicio",
                ]
            )
            writer.writerows(rows)
        return path

    def read_output(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_splits_reservations_and_excludes_payouts(self) -> None:
        source = self.write_source(
            [
                ["06/11/2026", "Payout", "", "", "", "", "", "", "", ""],
                [
                    "06/11/2026",
                    "Reservación",
                    "ABC",
                    "06/11/2026",
                    "Guest One",
                    "Fitz-Mar Quince, Habitación 1",
                    "3260.09",
                    "3260.09",
                    "500",
                    "120",
                ],
                [
                    "06/11/2026",
                    "Impuestos",
                    "ABC",
                    "06/11/2026",
                    "",
                    "",
                    "-320.21",
                    "",
                    "",
                    "",
                ],
                [
                    "25/12/2026",
                    "Reservación",
                    "XYZ",
                    "25/12/2026",
                    "Guest Two",
                    "Casa Azul, Depto",
                    "1000",
                    "1000",
                    "200",
                    "50",
                ],
                [
                    "25/12/2026",
                    "Limpieza extra",
                    "XYZ",
                    "25/12/2026",
                    "",
                    "",
                    "-30",
                    "",
                    "",
                    "",
                ],
            ]
        )
        target = self.folder / "out.csv"

        written, excluded = transform(source, target)

        self.assertEqual((written, excluded), (8, 1))
        rows = self.read_output(target)
        self.assertEqual(list(rows[0]), COLUMNS)
        self.assertEqual(
            [row["memo"] for row in rows],
            [
                "XYZ - Casa Azul - Reservación - Guest Two",
                "XYZ - Casa Azul - Tarifa de limpieza - Guest Two",
                "XYZ - Casa Azul - Tarifa de servicio - Guest Two",
                "XYZ - Casa Azul - Limpieza extra - Guest Two",
                "ABC - Fitz-Mar Quince - Reservación - Guest One",
                "ABC - Fitz-Mar Quince - Tarifa de limpieza - Guest One",
                "ABC - Fitz-Mar Quince - Tarifa de servicio - Guest One",
                "ABC - Fitz-Mar Quince - Impuestos - Guest One",
            ],
        )
        self.assertEqual(
            [row["amount"] for row in rows],
            [
                "800.00",
                "200.00",
                "-50.00",
                "-30.00",
                "2760.09",
                "500.00",
                "-120.00",
                "-320.21",
            ],
        )
        self.assertEqual(
            [row["date"] for row in rows],
            [
                "2026-12-25",
                "2026-12-25",
                "2026-12-25",
                "2026-12-25",
                "2026-11-06",
                "2026-11-06",
                "2026-11-06",
                "2026-11-06",
            ],
        )

    def test_rejects_a_file_without_the_airbnb_columns(self) -> None:
        path = self.folder / "other.csv"
        path.write_text("date,amount\n2026-01-01,10\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            transform(path, self.folder / "out.csv")

    def test_rejects_an_invalid_date(self) -> None:
        source = self.write_source(
            [
                [
                    "99/99/2026",
                    "Reservación",
                    "ABC",
                    "99/99/2026",
                    "",
                    "",
                    "10",
                    "10",
                    "0",
                    "0",
                ]
            ]
        )

        with self.assertRaises(ValueError):
            transform(source, self.folder / "out.csv")


if __name__ == "__main__":
    unittest.main()
