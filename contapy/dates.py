"""User-selectable date display formats.

Dates are stored and compared as ISO strings everywhere in the database.  This
module only controls how they are presented in the interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateFormat:
    key: str
    label: str
    pattern: str
    qt_pattern: str
    lowercase_month: bool = False


DATE_FORMATS: tuple[DateFormat, ...] = (
    DateFormat("yyyy/mmm/dd", "2026/feb/14", "%Y/%b/%d", "yyyy/MMM/dd", True),
    DateFormat("yyyy-mm-dd", "2026-02-14", "%Y-%m-%d", "yyyy-MM-dd"),
    DateFormat("dd/mm/yyyy", "14/02/2026", "%d/%m/%Y", "dd/MM/yyyy"),
    DateFormat("mm/dd/yyyy", "02/14/2026", "%m/%d/%Y", "MM/dd/yyyy"),
    DateFormat("dd mmm yyyy", "14 feb 2026", "%d %b %Y", "dd MMM yyyy", True),
    DateFormat("mmm dd, yyyy", "feb 14, 2026", "%b %d, %Y", "MMM dd, yyyy", True),
    DateFormat("dd-mmm-yyyy", "14-feb-2026", "%d-%b-%Y", "dd-MMM-yyyy", True),
    DateFormat("yyyy.mm.dd", "2026.02.14", "%Y.%m.%d", "yyyy.MM.dd"),
)

DEFAULT_DATE_FORMAT = DATE_FORMATS[0].key
_BY_KEY = {item.key: item for item in DATE_FORMATS}
_current = DATE_FORMATS[0]


def set_date_format(key: str) -> None:
    """Select the display format used by every date label."""
    global _current
    _current = _BY_KEY.get(key, DATE_FORMATS[0])


def current_date_format() -> str:
    return _current.key


def current_format() -> DateFormat:
    return _current


def date_format_label(key: str) -> str:
    return _BY_KEY.get(key, DATE_FORMATS[0]).label


def qt_date_format(key: str | None = None) -> str:
    return _BY_KEY.get(key or "", _current).qt_pattern


def format_date(value: str | date) -> str:
    """Format an ISO date string or ``date`` with the selected pattern."""
    if isinstance(value, date):
        day = value
    else:
        day = date.fromisoformat(value)
    text = day.strftime(_current.pattern)
    return text.lower() if _current.lowercase_month else text
