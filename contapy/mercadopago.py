"""Convert a Mercado Pago credit-card PDF statement into ContaPy's CSV format.

The statement's **Movimientos** section lists ``DD/MM`` dates, a description
that may end in an installment label such as ``8 de 9``, and a signed amount.
The opening **Saldo al corte** balance is not a transaction and is skipped.
"""

from __future__ import annotations

import csv
import re
from datetime import date
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
    "Status",
]

FULL_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

TRANSACTION = re.compile(
    r"^\s*(\d{1,2})/(\d{1,2})\s+(.+?)\s+(-?\s*\$)\s*([\d,]+\.\d{2})\s*$"
)


def _is_pdf(path: Path) -> bool:
    if path.suffix.lower() == ".pdf":
        return True
    try:
        with path.open("rb") as handle:
            return handle.read(5) == b"%PDF-"
    except OSError:
        return False


def _read_pdf_statement(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError(
            "Mercado Pago PDF statements require the pypdf package. "
            "Install it with: python -m pip install pypdf"
        ) from exc
    try:
        reader = PdfReader(str(path))
        text = "\n".join(
            page.extract_text(extraction_mode="layout") or ""
            for page in reader.pages
        )
    except Exception as exc:
        raise ValueError(f"Could not read the PDF statement: {exc}") from exc
    if not text.strip():
        raise ValueError(
            "The Mercado Pago PDF has no readable text. If it is a scanned "
            "image, export a text-based statement first."
        )
    return text


def _statement_year(text: str, path: str | Path) -> tuple[int, int | None]:
    """Return (year, reference month) from the statement header or filename."""
    match = re.search(
        r"Fecha[^\n]*?(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(20\d{2})",
        text,
    )
    if match:
        month = FULL_MONTHS.get(match.group(2).lower())
        return int(match.group(3)), month
    for source in (Path(path).stem, text):
        years = [int(year) for year in re.findall(r"\b20\d{2}\b", source)]
        if years:
            return max(set(years), key=years.count), None
    return date.today().year, None


def _parse_amount(value: str) -> float | None:
    sign = -1.0 if "-" in value else 1.0
    digits = re.sub(r"[^\d.]", "", value)
    if not digits:
        return None
    try:
        return sign * float(digits)
    except ValueError:
        return None


def _memo(description: str) -> str:
    text = re.sub(r"\s+", " ", description).strip()
    installment = re.search(r"\b(\d{1,2}\s+de\s+\d{1,2})\s*$", text)
    if installment:
        base = text[: installment.start()].strip()
        return f"{base} · {installment.group(1)}"
    return text


def _transactions(
    text: str, year: int, reference_month: int | None
) -> tuple[list[dict[str, str]], int]:
    output: list[dict[str, str]] = []
    skipped = 0
    in_movements = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_movements:
            if stripped.casefold() == "movimientos":
                in_movements = True
            continue
        if stripped.casefold().startswith("subtotal"):
            break
        match = TRANSACTION.match(line)
        if match is None:
            continue
        day_text, month_text, description = (
            match.group(1),
            match.group(2),
            match.group(3),
        )
        amount_text = f"{match.group(4)} {match.group(5)}"
        if "saldo al corte" in description.casefold():
            continue
        day, month = int(day_text), int(month_text)
        if not 1 <= day <= 31 or not 1 <= month <= 12:
            skipped += 1
            continue
        row_year = year
        if reference_month is not None and month > reference_month:
            row_year -= 1
        amount = _parse_amount(amount_text)
        if amount is None:
            skipped += 1
            continue
        pending = "en proceso" in description.casefold()
        output.append(
            {
                "Fecha": f"{row_year}-{month:02d}-{day:02d}",
                "Pago": "",
                "Número": "",
                "Beneficiario": "",
                "Memo": _memo(description),
                "Importe": f"{amount:.2f}",
                "Categoría": "",
                "Etiquetas": "",
                "Status": "Remind" if pending else "",
            }
        )
    return output, skipped


def _write_output(output: list[dict[str, str]], dst: str | Path) -> None:
    with Path(dst).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=COLUMNS, quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(output)


def transform(src: str | Path, dst: str | Path) -> tuple[int, int, int]:
    """Write the Mercado Pago statement at ``src`` as a CSV at ``dst``.

    Returns ``(rows_written, rows_skipped, statement_year)``.
    """
    source = Path(src)
    if not _is_pdf(source):
        raise ValueError("Mercado Pago import expects a PDF statement.")
    text = _read_pdf_statement(source)
    year, reference_month = _statement_year(text, source)
    output, skipped = _transactions(text, year, reference_month)
    if not output:
        raise ValueError(
            "No transactions were found in this Mercado Pago statement."
        )
    _write_output(output, dst)
    return len(output), skipped, year
