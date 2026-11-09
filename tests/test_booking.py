"""Tests for the Booking + Sabee consolidation."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from contapy.booking import COLUMNS, NO_ROOM, transform

BOOKING_HEADER = [
    "Type",
    "Booking number",
    "Check-in",
    "Checkout",
    "Guest name",
    "Payment status",
    "Amount",
    "Commission",
    "Withholding of VAT and income tax ",
    "VAT for online platform services",
    "Payments Service Fee",
]

SABEE_HEADER = ["Notes", "Channel ID", "Room name"]


class BookingTransformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_booking(self, rows: list[list[str]]) -> Path:
        path = self.folder / "booking.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(BOOKING_HEADER)
            writer.writerows(rows)
        return path

    def write_sabee(self, rows: list[list[str]]) -> Path:
        path = self.folder / "sabee.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(SABEE_HEADER)
            writer.writerows(rows)
        return path

    def read_output(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_unpivots_amounts_and_merges_the_room(self) -> None:
        booking = self.write_booking(
            [
                [
                    "Reservation",
                    "6987653796",
                    "30 Sept 2026",
                    "4 Oct 2026",
                    "cintia arguello",
                    "by_booking",
                    "5245.96",
                    "-650.33",
                    "-520.26",
                    "-130.07",
                    "-162.62",
                ]
            ]
        )
        sabee = self.write_sabee([["", "6987653796.0", "AN6"]])
        target = self.folder / "out.csv"

        written, missing = transform(booking, sabee, target)

        self.assertEqual((written, missing), (5, 0))
        rows = self.read_output(target)
        self.assertEqual(list(rows[0]), COLUMNS)
        self.assertEqual(rows[0]["Fecha"], "2026-10-04")
        self.assertEqual(rows[0]["Importe"], "5245.96")
        self.assertEqual(
            rows[0]["Memo"],
            "6987653796 | cintia arguello | by_booking | Amount | AN6",
        )
        self.assertEqual(
            [row["Memo"].rsplit(" | ", 2)[-2] for row in rows],
            [
                "Amount",
                "Commission",
                "Payments Service Fee",
                "VAT for online platform services",
                "Withholding of VAT and income tax",
            ],
        )
        self.assertEqual(rows[1]["Importe"], "-650.33")

    def test_sorts_by_date_then_memo_and_falls_back_when_room_is_missing(self) -> None:
        booking = self.write_booking(
            [
                [
                    "Reservation",
                    "222",
                    "1 Nov 2026",
                    "2 Nov 2026",
                    "Later Guest",
                    "ok",
                    "20.00",
                    "-2.00",
                    "",
                    "",
                    "",
                ],
                [
                    "Reservation",
                    "111",
                    "30 Sept 2026",
                    "1 Oct 2026",
                    "Earlier Guest",
                    "ok",
                    "10.00",
                    "-1.00",
                    "",
                    "",
                    "",
                ],
            ]
        )
        sabee = self.write_sabee([["", "111", "AN1"]])
        target = self.folder / "out.csv"

        written, missing = transform(booking, sabee, target)

        self.assertEqual((written, missing), (4, 1))
        rows = self.read_output(target)
        self.assertEqual(
            [row["Fecha"] for row in rows],
            ["2026-10-01", "2026-10-01", "2026-11-02", "2026-11-02"],
        )
        self.assertEqual(rows[0]["Memo"], "111 | Earlier Guest | ok | Amount | AN1")
        self.assertEqual(
            rows[2]["Memo"], f"222 | Later Guest | ok | Amount | {NO_ROOM}"
        )

    def test_accepts_alternate_column_names(self) -> None:
        path = self.folder / "booking_alt.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "Reservation number",
                    "Departure",
                    "Guest name",
                    "Status",
                    "Final amount",
                    "Commission amount",
                ]
            )
            writer.writerow(
                ["987.0", "7 Nov 2026", "Alt Guest", "confirmed", "300.00", "-30.00"]
            )
        sabee = self.write_sabee([["", "987", "AN5"]])
        target = self.folder / "out.csv"

        transform(path, sabee, target)

        rows = self.read_output(target)
        self.assertEqual([row["Importe"] for row in rows], ["-30.0", "300.0"])
        self.assertEqual(rows[0]["Fecha"], "2026-11-07")
        self.assertEqual(
            rows[0]["Memo"], "987 | Alt Guest | confirmed | Commission amount | AN5"
        )

    def test_rejects_files_that_are_not_booking_and_sabee(self) -> None:
        other = self.folder / "other.csv"
        other.write_text("Date,Amount\n2026-01-01,10\n", encoding="utf-8")
        sabee = self.write_sabee([["", "1", "AN1"]])
        with self.assertRaises(ValueError):
            transform(other, sabee, self.folder / "out.csv")

        booking = self.write_booking(
            [["Reservation", "1", "1 Nov 2026", "2 Nov 2026", "G", "ok", "1"]]
        )
        with self.assertRaises(ValueError):
            transform(booking, other, self.folder / "out.csv")


if __name__ == "__main__":
    unittest.main()
