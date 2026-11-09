"""Consolidate Booking payouts with Sabee reservations into ContaPy's CSV format.

Booking's finance export has one row per reservation with several amount
columns (revenue, commission, fees, taxes). ContaPy needs one row per amount,
so the amounts are unpivoted into separate rows and tagged with the room name
taken from the matching Sabee reservation.

This mirrors the original ``tui_consolidator.py`` script but uses only the
standard library.
"""

from __future__ import annotations

import csv
from pathlib import Path

COLUMNS = [
    "Fecha",
    "Pago",
    "Número",
    "Beneficiario",
    "Memo",
    "Importe",
    "Categoría",
    "Etiquetas",
]

VALUE_COLUMNS = [
    "Final amount",
    "Amount",
    "Commission amount",
    "Commission",
    "Payment fee",
    "Payments Service Fee",
    "Withholding of VAT and income tax",
    "VAT for online platform services",
]

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

NO_ROOM = "Sin habitación"


def _read_csv(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [column.strip() for column in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            rows.append(
                {
                    (key or "").strip(): (value or "").strip()
                    for key, value in raw.items()
                }
            )
        return headers, rows


def _pick(headers: list[str], *names: str, required: bool = True) -> str:
    for name in names:
        if name in headers:
            return name
    if required:
        raise ValueError(
            "This does not look like a Booking export. "
            f"Expected one of: {', '.join(names)}."
        )
    return ""


def _normalise_id(value: str) -> str:
    text = (value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _iso_date(value: str) -> str:
    parts = (value or "").strip().split()
    if len(parts) != 3:
        return ""
    day, month_name, year = parts
    month = MONTHS.get(month_name.lower().rstrip("."))
    if month is None or not day.isdigit():
        return ""
    return f"{year}-{month:02d}-{int(day):02d}"


def _amount_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        return repr(float(text))
    except ValueError:
        return ""


def transform(
    booking_path: str | Path, sabee_path: str | Path, dst: str | Path
) -> tuple[int, int]:
    """Write the consolidated CSV and return ``(rows_written, rooms_missing)``."""
    booking_headers, booking_rows = _read_csv(booking_path)
    sabee_headers, sabee_rows = _read_csv(sabee_path)

    reservation_column = _pick(
        booking_headers, "Reservation number", "Booking number"
    )
    checkout_column = _pick(booking_headers, "Departure", "Checkout")
    status_column = _pick(booking_headers, "Status", "Payment status")
    guest_column = _pick(booking_headers, "Guest name")
    value_columns = [name for name in VALUE_COLUMNS if name in booking_headers]
    if not value_columns:
        raise ValueError(
            "No Booking amount columns were found in this file."
        )

    if "Channel ID" not in sabee_headers or "Room name" not in sabee_headers:
        raise ValueError(
            "This does not look like a Sabee reservation export. "
            "Expected Channel ID and Room name columns."
        )

    rooms: dict[str, str] = {}
    for row in sabee_rows:
        channel = _normalise_id(row.get("Channel ID", ""))
        room = row.get("Room name", "")
        if channel and channel not in rooms:
            rooms[channel] = room

    output: list[dict[str, str]] = []
    rooms_missing = 0
    for row in booking_rows:
        reservation = _normalise_id(row.get(reservation_column, ""))
        if not reservation:
            continue
        fecha = _iso_date(row.get(checkout_column, ""))
        if not fecha:
            continue
        guest = row.get(guest_column, "")
        status = row.get(status_column, "")
        room = rooms.get(reservation)
        if room is None or room == "":
            room = NO_ROOM
            rooms_missing += 1
        for amount_type in value_columns:
            amount = _amount_text(row.get(amount_type, ""))
            if not amount:
                continue
            memo = f"{reservation} | {guest} | {status} | {amount_type} | {room}"
            output.append(
                {
                    "Fecha": fecha,
                    "Pago": "",
                    "Número": "",
                    "Beneficiario": "",
                    "Memo": memo,
                    "Importe": amount,
                    "Categoría": "",
                    "Etiquetas": "",
                }
            )

    if not output:
        raise ValueError("No transactions were found in these Booking and Sabee files.")

    output.sort(key=lambda item: (item["Fecha"], item["Memo"]))

    with Path(dst).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(output)

    return len(output), rooms_missing
