"""Convert a Banamex HTML statement into ContaPy's CSV format.

Banamex statements are saved web pages with a single transactions table using
the columns ``Fecha``, ``Descripción`` and ``Movimientos``. Dates omit the
year, so it is taken from the statement header (falling back to the page or
file year).
"""

from __future__ import annotations

import csv
import re
from datetime import date
from html.parser import HTMLParser
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

MONTHS = {
    "Ene": 1,
    "Feb": 2,
    "Mar": 3,
    "Abr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Ago": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dic": 12,
}

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

PDF_TRANSACTION = re.compile(
    r"^\s*(\d{1,2})/(\d{1,2})\s+(.+?)\s+(-?\s*\$)\s*([\d,]+\.\d{2})\s*$"
)


class _FirstTableParser(HTMLParser):
    """Collect the rows and cells of the first <table> in the document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_table = False
        self._done = False
        self._in_row = False
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            if not self._in_table and not self._done:
                self._in_table = True
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "table":
            self._in_table = False
            self._done = True
        elif tag == "tr" and self._in_row:
            self.rows.append(self._row)
            self._in_row = False
            self._in_cell = False
        elif tag in ("td", "th") and self._in_cell:
            self._row.append(" ".join(self._cell).strip())
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            text = data.strip()
            if text:
                self._cell.append(text)


def _read_statement(path: str | Path) -> tuple[list[list[str]], str]:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("windows-1252")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    parser = _FirstTableParser()
    parser.feed(text)
    return parser.rows, text


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
            "PDF statements require the pypdf package. Install it with: "
            "python -m pip install pypdf"
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
            "The PDF statement has no readable text. If it is a scanned "
            "image, export a text-based statement first."
        )
    return text


def _statement_year(text: str, path: str | Path) -> tuple[int, int | None]:
    """Return (year, reference month) from the statement header or filename."""
    match = re.search(
        r"(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+de\s+(20\d{2})", text
    )
    if match:
        month = FULL_MONTHS.get(match.group(2).lower())
        return int(match.group(3)), month
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


def _parse_date(value: str, year: int, reference_month: int | None) -> str | None:
    text = re.sub(r"\s*CEP\s*", " ", value).strip()
    parts = text.split()
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    day = int(parts[0])
    month = MONTHS.get(parts[1][:3].capitalize())
    if month is None or not 1 <= day <= 31:
        return None
    row_year = year
    if reference_month is not None and month > reference_month:
        row_year -= 1
    return f"{row_year}-{month:02d}-{day:02d}"


def _parse_amount(value: str) -> float | None:
    sign = -1.0 if "-" in value else 1.0
    digits = re.sub(r"[^\d.]", "", value)
    if not digits:
        return None
    try:
        return sign * float(digits)
    except ValueError:
        return None


def _clean_description(value: str) -> str:
    concepto = re.search(r"Concepto de pago:\s*(.+)", value)
    main = re.split(r"Referencia", value)[0].strip()
    if concepto:
        return f"{main} | {concepto.group(1).strip()}"
    return main


def _pdf_memo(description: str) -> str:
    text = re.sub(r"\s+", " ", description).strip()
    installment = re.search(r"\b(\d{1,2}\s+de\s+\d{1,2})\s*$", text)
    if installment:
        base = text[: installment.start()].strip()
        return f"{base} · {installment.group(1)}"
    return text


def _pdf_transactions(
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
        match = PDF_TRANSACTION.match(line)
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
                "Memo": _pdf_memo(description),
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


def _transform_html(src: str | Path, dst: str | Path) -> tuple[int, int, int]:
    rows, text = _read_statement(src)
    year, reference_month = _statement_year(text, src)

    has_header = any(
        row and row[0].strip().lower() == "fecha" for row in rows
    )
    if not has_header:
        raise ValueError(
            "This does not look like a Banamex HTML statement. "
            "Expected a transactions table with a Fecha column."
        )

    output: list[dict[str, str]] = []
    skipped = 0
    for row in rows:
        if len(row) < 3:
            continue
        fecha, description, amount_text = row[0], row[1], row[2]
        if not fecha or fecha.strip().lower() == "fecha":
            continue
        parsed = _parse_date(fecha, year, reference_month)
        amount = _parse_amount(amount_text)
        if parsed is None or amount is None:
            skipped += 1
            continue
        pending = "en proceso" in amount_text.casefold()
        output.append(
            {
                "Fecha": parsed,
                "Pago": "",
                "Número": "",
                "Beneficiario": "",
                "Memo": _clean_description(description),
                "Importe": f"{amount:.2f}",
                "Categoría": "",
                "Etiquetas": "",
                "Status": "Remind" if pending else "",
            }
        )

    if not output:
        raise ValueError("No transactions were found in this Banamex statement.")

    _write_output(output, dst)
    return len(output), skipped, year


def transform(src: str | Path, dst: str | Path) -> tuple[int, int, int]:
    """Write the Banamex statement at ``src`` as a ContaPy CSV at ``dst``.

    Handles saved HTML statements and text-based PDF statements. Returns
    ``(rows_written, rows_skipped, statement_year)``.
    """
    source = Path(src)
    if _is_pdf(source):
        text = _read_pdf_statement(source)
        year, reference_month = _statement_year(text, source)
        output, skipped = _pdf_transactions(text, year, reference_month)
        if not output:
            raise ValueError(
                "No transactions were found in this Banamex PDF statement."
            )
        _write_output(output, dst)
        return len(output), skipped, year
    return _transform_html(source, dst)
