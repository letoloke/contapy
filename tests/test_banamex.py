"""Tests for the Banamex HTML statement conversion."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from contapy.banamex import (
    COLUMNS,
    _pdf_transactions,
    _statement_year,
    transform,
)
from contapy.csv_io import read_csv_plan, statuses_from_row


PDF_TEXT = """
Fecha: 28 octubre 2026
Número de cuenta: 503341066

Resumen de movimientos

Saldo al corte del periodo anterior (septiembre)     - $ 549.00
Compras                                                $ 4,381.07

Movimientos

MXN$

28/09    Saldo al corte del periodo anterior (septiembre)       - $ 549.00

05/03    Compra en MERPAGO*MERCADOLIBRE          8 de 9          $ 433.33

30/09    Pago del resumen del septiembre/2026                    - $ 4,000.00

30/09    Compra en HOME DEPOT I                  1 de 12       $ 1,062.12

02/10    Crédito                                                - $ 1,895.00

12/10    Compra en SUPER RIDES                                    $ 48.00

                                                          Subtotal - $ 1,000.00

Saldo a meses con o sin intereses

Movimiento            Monto total       Tasa anual       Mes       Monto mensual
merpago*MERCADOLIBRE  $ 2,899.00       0%               2 de 4    $ 724.75
"""


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
        self.assertEqual(rows[0]["Status"], "Remind")
        self.assertEqual(rows[1]["Fecha"], "2026-11-07")
        self.assertEqual(rows[1]["Importe"], "-170.00")
        self.assertEqual(rows[1]["Status"], "")
        self.assertEqual(
            rows[2]["Memo"],
            "Concepto de pago: Servicio | Servicio Referencia 123",
        )
        self.assertEqual(rows[2]["Importe"], "1200.50")
        self.assertEqual(rows[2]["Status"], "")

        plan = read_csv_plan(target)
        self.assertEqual(
            statuses_from_row(plan, plan.rows[0]),
            (True, False, True, False, False),
        )
        self.assertEqual(
            statuses_from_row(plan, plan.rows[1]),
            (True, False, False, False, False),
        )

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

    def test_converts_pdf_transactions_and_skips_the_opening_balance(self) -> None:
        year, reference_month = _statement_year(PDF_TEXT, "statement.pdf")

        rows, skipped = _pdf_transactions(
            PDF_TEXT, year, reference_month
        )

        self.assertEqual((year, reference_month), (2026, 10))
        self.assertEqual((len(rows), skipped), (5, 0))
        self.assertEqual(rows[0]["Fecha"], "2026-03-05")
        self.assertIn("MERPAGO*MERCADOLIBRE", rows[0]["Memo"])
        self.assertIn("8 de 9", rows[0]["Memo"])
        self.assertEqual(rows[0]["Importe"], "433.33")
        self.assertEqual(rows[1]["Fecha"], "2026-09-30")
        self.assertEqual(rows[1]["Importe"], "-4000.00")
        self.assertEqual(rows[2]["Importe"], "1062.12")
        self.assertEqual(rows[3]["Importe"], "-1895.00")
        self.assertEqual(rows[4]["Importe"], "48.00")
        self.assertTrue(all(row["Status"] == "" for row in rows))

    def test_pdf_dates_roll_december_into_the_previous_year(self) -> None:
        text = """
Fecha: 28 enero 2027
Número de cuenta: 503341066

Movimientos

28/12    Compra en YEAR END       $ 10.00
05/01    Compra en NEW YEAR       $ 20.00

Subtotal - $ 30.00
"""
        year, reference_month = _statement_year(text, "statement.pdf")

        rows, skipped = _pdf_transactions(text, year, reference_month)

        self.assertEqual((year, reference_month), (2027, 1))
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0]["Fecha"], "2026-12-28")
        self.assertEqual(rows[1]["Fecha"], "2027-01-05")

    def test_transform_dispatches_pdf_statements(self) -> None:
        source = self.folder / "statement.pdf"
        source.write_bytes(b"%PDF-1.4\n")
        target = self.folder / "out.csv"

        with mock.patch(
            "contapy.banamex._read_pdf_statement", return_value=PDF_TEXT
        ):
            written, skipped, year = transform(source, target)

        self.assertEqual((written, skipped, year), (5, 0, 2026))
        rows = self.read_output(target)
        self.assertEqual(list(rows[0]), COLUMNS)
        self.assertEqual(rows[0]["Fecha"], "2026-03-05")
        self.assertEqual(rows[1]["Importe"], "-4000.00")

    def test_rejects_a_non_banamex_file(self) -> None:
        path = self.folder / "other.html"
        path.write_text("<html><body>No table here</body></html>", encoding="utf-8")
        with self.assertRaises(ValueError):
            transform(path, self.folder / "out.csv")


if __name__ == "__main__":
    unittest.main()
