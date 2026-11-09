"""Tests for the Banamex HTML statement conversion."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from contapy.banamex import COLUMNS, transform


class BanamexTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_statement(self, header: str, rows: list[str]) -> Path:
        path = self.folder / "statement.html"
        path.write_text(
            "<html><body>"
            f"<label>{header}</label>"
            "<table><tr><th>Fecha</th><th>Descripción</th><th>Movimientos</th></tr>"
            + "".join(
                "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    *row.split("|", 2)
                )
                for row in rows
            )
            + "</table></body></html>",
            encoding="windows-1252",
        )
        return path

    def read_output(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_converts_rows_and_amounts(self) -> None:
        source = self.write_statement(
            "Domingo 8 de Noviembre de 2026, 19:40:13",
            [
                "08 Nov CEP|PAGO INTERBANCARIO AUT 0807593|$ 560.00 En proceso",
                "07 Nov|MERPAGO*AMADOHELADO|- $ 170.00",
                "|Ignored empty row|",
                "06 Nov|Concepto de pago: Servicio Referencia 123|$ 1,200.50",
            ],
        )
        target = self.folder / "out.csv"

        written, skipped, year = transform(source, target)

        self.assertEqual((written, skipped, year), (3, 0, 2026))
        rows = self.read_output(target)
        self.assertEqual(list(rows[0]), COLUMNS)
        self.assertEqual(rows[0]["Fecha"], "2026-11-08")
        self.assertEqual(rows[0]["Memo"], "PAGO INTERBANCARIO AUT 0807593")
        self.assertEqual(rows[0]["Importe"], "560.00")
        self.assertEqual(rows[1]["Fecha"], "2026-11-07")
        self.assertEqual(rows[1]["Importe"], "-170.00")
        self.assertEqual(
            rows[2]["Memo"],
            "Concepto de pago: Servicio | Servicio Referencia 123",
        )
        self.assertEqual(rows[2]["Importe"], "1200.50")

    def test_rolls_december_into_the_previous_year(self) -> None:
        source = self.write_statement(
            "Lunes 5 de Enero de 2027, 08:00:00",
            [
                "31 Dic|YEAR END|$ 10.00",
                "05 Ene|NEW YEAR|$ 20.00",
            ],
        )
        target = self.folder / "out.csv"

        transform(source, target)

        rows = self.read_output(target)
        self.assertEqual(rows[0]["Fecha"], "2026-12-31")
        self.assertEqual(rows[1]["Fecha"], "2027-01-05")

    def test_rejects_a_non_banamex_file(self) -> None:
        path = self.folder / "other.html"
        path.write_text("<html><body>No table here</body></html>", encoding="utf-8")
        with self.assertRaises(ValueError):
            transform(path, self.folder / "out.csv")


if __name__ == "__main__":
    unittest.main()
