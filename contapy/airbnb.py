"""Convert an Airbnb transaction export into LetoBank's CSV format.

Based on ``airbnb_csv_transform4.py``. It groups rows by confirmation code and
splits each reservation into reservation, cleaning-fee and service-fee rows,
including the guest name in every memo. The reservation row absorbs rounding
and discounts so each group sums exactly to the source ``Monto``. Payout rows
are excluded because they duplicate the reservation rows.

The converter writes the English CSV headers
``date,payee,category,memo,amount,payment,tags,status`` and keeps each
reservation's rows together.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

COLUMNS = [
    "date",
    "payee",
    "category",
    "memo",
    "amount",
    "payment",
    "tags",
    "status",
]

DATE_COLUMN = "Fecha de inicio"
REQUIRED_COLUMNS = (
    "Tipo",
    DATE_COLUMN,
    "Código de confirmación",
    "Espacio",
    "Huésped",
    "Monto",
    "Tarifa de limpieza",
    "Tarifa de servicio",
)


def _number(value: str) -> float:
    text = (value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError as error:
        raise ValueError(f"Invalid amount: {value!r}") from error


def _date_parser(values: list[str]):
    """Return an ISO-date converter, detecting dd/mm vs mm/dd like Airbnb."""
    firsts: list[int] = []
    seconds: list[int] = []
    for value in values:
        parts = (value or "").strip().split("/")
        if len(parts) != 3:
            continue
        try:
            firsts.append(int(parts[0]))
            seconds.append(int(parts[1]))
        except ValueError:
            continue
    day_first = max(firsts, default=0) > 12 and max(seconds, default=0) <= 12

    def to_iso(value: str) -> str:
        parts = (value or "").strip().split("/")
        if len(parts) != 3:
            raise ValueError(f"Invalid date: {value!r}")
        first, second, year = parts
        month, day = (second, first) if day_first else (first, second)
        try:
            return date(int(year), int(month), int(day)).isoformat()
        except ValueError as error:
            raise ValueError(f"Invalid date: {value!r}") from error

    return to_iso


def _unit(space: str) -> str:
    return (space or "").split(",")[0].strip()


def transform(src: str | Path, dst: str | Path) -> tuple[int, int]:
    """Write the Airbnb transaction export at ``src`` as a CSV at ``dst``.

    Returns ``(rows_written, payouts_excluded)``. Raises ``ValueError`` when
    the file is not an Airbnb transaction export or contains invalid values.
    """
    with Path(src).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [header for header in (reader.fieldnames or []) if header]
        missing = [
            column for column in REQUIRED_COLUMNS if column not in headers
        ]
        if missing:
            raise ValueError(
                "This does not look like an Airbnb transaction export. "
                f"Missing column(s): {', '.join(missing)}."
            )
        all_rows = list(reader)
        rows = [
            row
            for row in all_rows
            if (row.get("Tipo") or "").strip() != "Payout"
        ]
    excluded = len(all_rows) - len(rows)

    if not rows:
        raise ValueError(
            "No Airbnb transactions were found in this file."
        )

    to_iso = _date_parser(
        [row.get(DATE_COLUMN) or "" for row in rows]
    )
    groups: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for row in rows:
        key = (row.get("Código de confirmación") or "").strip()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    output: list[tuple[str, int, int, dict[str, str]]] = []
    for group_index, key in enumerate(order):
        group = groups[key]
        when = to_iso(group[0].get(DATE_COLUMN) or "")
        unit = _unit(group[0].get("Espacio") or "")
        guest = (group[0].get("Huésped") or "").strip()
        records: list[dict[str, str]] = []

        def add(concept: str, amount: float) -> None:
            memo = " - ".join(
                piece for piece in (key, unit, concept, guest) if piece
            )
            records.append(
                {
                    "date": when,
                    "payee": "",
                    "category": "",
                    "memo": memo,
                    "amount": f"{amount:.2f}",
                    "payment": "",
                    "tags": "",
                    "status": "",
                }
            )

        for row in group:
            if (row.get("Tipo") or "").strip() != "Reservación":
                continue
            total = _number(row.get("Monto") or "")
            cleaning = _number(row.get("Tarifa de limpieza") or "")
            service = _number(row.get("Tarifa de servicio") or "")
            # The reservation row absorbs rounding and discounts so the
            # generated group sums exactly to the source Monto.
            add("Reservación", total - cleaning + abs(service))
            if cleaning:
                add("Tarifa de limpieza", cleaning)
            if service:
                add("Tarifa de servicio", -abs(service))

        for row in group:
            kind = (row.get("Tipo") or "").strip()
            if kind == "Reservación":
                continue
            add(kind, _number(row.get("Monto") or ""))

        for record_index, record in enumerate(records):
            output.append((when, group_index, record_index, record))

    if not output:
        raise ValueError(
            "No Airbnb transactions were found in this file."
        )

    # Newest dates first, keeping each reservation's generated rows together.
    output.sort(key=lambda item: (item[1], item[2]))
    output.sort(key=lambda item: item[0], reverse=True)

    with Path(dst).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(item[3] for item in output)

    return len(output), excluded
