"""CSV detection and parsing for HomeBank-style imports.

Headers are matched across English and Spanish spellings and accents are
ignored, so a HomeBank "ready to import" file such as
``Fecha,Pago,Número,Beneficiario,Memo,Importe,Categoría,Etiquetas`` works
without renaming anything.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

FIELD_ALIASES: dict[str, set[str]] = {
    "date": {
        "fecha",
        "date",
        "fecha operacion",
        "fecha de operacion",
        "fecha valor",
        "fecha contable",
        "fecha transaccion",
        "fecha movimiento",
        "posting date",
        "transaction date",
        "value date",
    },
    "amount": {
        "importe",
        "amount",
        "monto",
        "cantidad",
        "valor",
        "total",
    },
    "payee": {
        "beneficiario",
        "beneficiary",
        "payee",
        "comercio",
        "merchant",
        "nombre",
        "name",
    },
    "memo": {
        "memo",
        "concepto",
        "detalle",
        "descripcion",
        "description",
        "nota",
        "notas",
        "glosa",
    },
    "payment": {
        "pago",
        "payment",
        "metodo de pago",
        "forma de pago",
        "payment method",
        "tipo de pago",
    },
    "number": {
        "numero",
        "number",
        "num",
        "referencia",
        "reference",
        "ref",
        "documento",
        "cheque",
        "check number",
    },
    "category": {"categoria", "category"},
    "tags": {"etiquetas", "tags", "tag"},
    "account": {"cuenta", "account", "cuenta origen", "account name"},
    "cleared": {"cleared", "conciliado", "compensado", "cleared status"},
    "reconciled": {"reconciled", "reconciliado"},
    "remind": {"remind", "recordatorio"},
    "flagged": {"flagged", "marcado", "flag"},
    "status": {"status", "estado"},
}

REQUIRED_FIELDS = ("date", "amount")
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%y",
    "%m/%d/%y",
)


def normalize(value: str) -> str:
    """Lowercase, strip accents and collapse punctuation to single spaces."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def header_signature(headers: list[str]) -> str:
    """Stable key for a set of columns, independent of order/case/accents."""
    return "|".join(sorted(normalize(header) for header in headers if normalize(header)))


def detect_mapping(headers: list[str]) -> dict[str, str]:
    normalized = {header: normalize(header) for header in headers}
    mapping: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for header, normalized_header in normalized.items():
            if normalized_header in aliases:
                mapping[field] = header
                break
    return mapping


@dataclass(slots=True)
class CsvPlan:
    path: Path
    headers: list[str]
    rows: list[dict[str, str]]
    mapping: dict[str, str]
    delimiter: str
    encoding: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def missing_required(self) -> list[str]:
        return [field for field in REQUIRED_FIELDS if field not in self.mapping]

    def has(self, field: str) -> bool:
        return field in self.mapping

    def value(self, row: dict[str, str], field: str) -> str:
        header = self.mapping.get(field)
        if header is None:
            return ""
        value = row.get(header)
        return str(value).strip() if value is not None else ""

    def mapping_summary(self) -> list[tuple[str, str]]:
        labels = {
            "date": "Date",
            "amount": "Amount",
            "payee": "Payee",
            "memo": "Memo",
            "payment": "Payment",
            "number": "Number",
            "category": "Category",
            "tags": "Tags",
            "account": "Account",
            "cleared": "Cleared",
            "reconciled": "Reconciled",
            "remind": "Remind",
            "flagged": "Flagged",
            "status": "Status",
        }
        return [
            (labels[field], header)
            for field, header in self.mapping.items()
            if field in labels
        ]


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _detect_delimiter(text: str) -> str:
    header_line = next((line for line in text.splitlines() if line.strip()), "")
    counts = {delimiter: header_line.count(delimiter) for delimiter in (",", ";", "\t", "|")}
    delimiter = max(counts, key=counts.get)
    return delimiter if counts[delimiter] else ","


def read_csv_plan(path: str | Path) -> CsvPlan:
    path = Path(path)
    text, encoding = _decode(path.read_bytes())
    delimiter = _detect_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = [header for header in (reader.fieldnames or []) if header is not None]
    rows: list[dict[str, str]] = []
    for row in reader:
        cleaned = {
            header: (value if value is not None else "")
            for header, value in row.items()
            if header is not None
        }
        if any(str(value).strip() for value in cleaned.values()):
            rows.append(cleaned)
    return CsvPlan(
        path=path,
        headers=headers,
        rows=rows,
        mapping=detect_mapping(headers),
        delimiter=delimiter,
        encoding=encoding,
    )


def parse_date(value: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    text = text.split("T", 1)[0].strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: str) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("\xa0", "").replace(" ", "")
    text = re.sub(r"[^0-9.,+\-]", "", text)
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        parts = text.rsplit(",", 1)
        if len(parts[1]) in (1, 2):
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    if text.count(".") > 1:
        parts = text.split(".")
        text = "".join(parts[:-1]) + "." + parts[-1]
    try:
        amount = float(text)
    except ValueError:
        return None
    if negative:
        amount = -abs(amount)
    return amount


def parse_bool(value: str, default: bool = False) -> bool:
    text = normalize(value)
    if not text:
        return default
    if text in {"no", "false", "0", "n", "off"}:
        return False
    if text in {"yes", "true", "1", "y", "si", "x", "on"}:
        return True
    return default


def statuses_from_row(plan: CsvPlan, row: dict[str, str]) -> tuple[bool, bool, bool, bool]:
    """Return cleared, reconciled, remind, flagged."""
    if plan.has("status"):
        status = normalize(plan.value(row, "status"))
        if "reconcil" in status:
            return True, True, False, False
        if "remind" in status or "record" in status:
            return True, False, True, False
        if "flag" in status:
            return True, False, False, True
        if "clear" in status:
            return True, False, False, False
        if status in {"none", "no", "uncleared", "pendiente"}:
            return False, False, False, False
    cleared = parse_bool(plan.value(row, "cleared"), True) if plan.has("cleared") else True
    reconciled = parse_bool(plan.value(row, "reconciled"), False) if plan.has("reconciled") else False
    remind = parse_bool(plan.value(row, "remind"), False) if plan.has("remind") else False
    flagged = parse_bool(plan.value(row, "flagged"), False) if plan.has("flagged") else False
    if reconciled:
        cleared = True
    return cleared, reconciled, remind, flagged
