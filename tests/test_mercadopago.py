"""Tests for the Mercado Pago PDF statement conversion."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from contapy.mercadopago import (
    COLUMNS,
    _statement_year,
    _transactions,
    transform,
)


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


class MercadoPagoTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def read_output(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_converts_transactions_and_skips_the_opening_balance(self) -> None:
        year, reference_month = _statement_year(PDF_TEXT, "statement.pdf")

        rows, skipped = _transactions(PDF_TEXT, year, reference_month)

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

    def test_dates_roll_december_into_the_previous_year(self) -> None:
        text = """
Fecha: 28 enero 2027
Número de cuenta: 503341066

Movimientos

28/12    Compra en YEAR END       $ 10.00
05/01    Compra en NEW YEAR       $ 20.00

Subtotal - $ 30.00
"""
        year, reference_month = _statement_year(text, "statement.pdf")

        rows, skipped = _transactions(text, year, reference_month)

        self.assertEqual((year, reference_month), (2027, 1))
        self.assertEqual(skipped, 0)
        self.assertEqual(rows[0]["Fecha"], "2026-12-28")
        self.assertEqual(rows[1]["Fecha"], "2027-01-05")

    def test_transform_dispatches_pdf_statements(self) -> None:
        source = self.folder / "statement.pdf"
        source.write_bytes(b"%PDF-1.4\n")
        target = self.folder / "out.csv"

        with mock.patch(
            "contapy.mercadopago._read_pdf_statement", return_value=PDF_TEXT
        ):
            written, skipped, year = transform(source, target)

        self.assertEqual((written, skipped, year), (5, 0, 2026))
        rows = self.read_output(target)
        self.assertEqual(list(rows[0]), COLUMNS)
        self.assertEqual(rows[0]["Fecha"], "2026-03-05")
        self.assertEqual(rows[1]["Importe"], "-4000.00")

    def test_rejects_a_non_pdf_file(self) -> None:
        source = self.folder / "statement.csv"
        source.write_text("Fecha,Importe\n2026-10-01,10.00\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            transform(source, self.folder / "out.csv")


if __name__ == "__main__":
    unittest.main()
