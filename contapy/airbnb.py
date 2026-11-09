"""Convert Airbnb reservation exports into ContaPy's CSV format.

The source export uses Airbnb's Spanish column names and includes a ``Payout``
row for money transferred to the bank. Those payout rows duplicate the
individual reservation and tax rows, so they are left out.
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

DATE_COLUMN = "Fecha de inicio"
REQUIRED_COLUMNS = ("Tipo", DATE_COLUMN, "Monto")


def is_airbnb_export(headers: list[str]) -> bool:
    """True when the CSV looks like an Airbnb reservation export."""
    return all(column in headers for column in REQUIRED_COLUMNS)


def _uses_day_first(rows: list[dict[str, str]]) -> bool:
    """Airbnb switches between mm/dd/yyyy and dd/mm/yyyy by export locale."""
    highest = 0
    for row in rows:
        parts = (row.get(DATE_COLUMN) or "").strip().split("/")
        if len(parts) == 3:
            try:
                highest = max(highest, int(parts[0]))
            except ValueError:
                continue
    return highest > 12


def _iso_date(value: str, day_first: bool) -> str:
    parts = (value or "").strip().split("/")
    if len(parts) != 3:
        return ""
    first, second, year = (part.strip() for part in parts)
    month, day = (second, first) if day_first else (first, second)
    try:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return ""


def _memo(row: dict[str, str]) -> str:
    pieces = [
        (row.get("Código de confirmación") or "").strip(),
        (row.get("Tipo") or "").strip(),
        (row.get("Espacio") or "").strip(),
        (row.get("Huésped") or "").strip(),
    ]
    return " - ".join(piece for piece in pieces if piece)


def _amount(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return value


def transform(src: str | Path, dst: str | Path) -> tuple[int, int]:
    """Write the Airbnb export at ``src`` as a ContaPy CSV at ``dst``.

    Returns ``(rows_written, payouts_excluded)``. Raises ``ValueError`` when
    the file is not an Airbnb export.
    """
    with Path(src).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = [header for header in (reader.fieldnames or []) if header]
        if not is_airbnb_export(headers):
            missing = ", ".join(
                column for column in REQUIRED_COLUMNS if column not in headers
            )
            raise ValueError(
                "This does not look like an Airbnb reservation export. "
                f"Missing column(s): {missing}."
            )
        rows = list(reader)

    day_first = _uses_day_first(rows)
    output: list[dict[str, str]] = []
    excluded = 0
    for row in rows:
        if (row.get("Tipo") or "").strip() == "Payout":
            excluded += 1
            continue
        output.append(
            {
                "Fecha": _iso_date(row.get(DATE_COLUMN) or "", day_first),
                "Pago": "",
                "Número": "",
                "Beneficiario": "",
                "Memo": _memo(row),
                "Importe": _amount(row.get("Monto") or ""),
                "Categoría": "",
                "Etiquetas": "",
            }
        )

    with Path(dst).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(output)

    return len(output), excluded
