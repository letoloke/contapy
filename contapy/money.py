"""Money and date formatting helpers."""

from __future__ import annotations

from .dates import format_date


def money(value: float, symbol: str = "$", decimals: int = 2) -> str:
    """Format a signed amount as ``$ 1,234.56`` / ``$ -42.00``."""
    if decimals == 0:
        body = f"{abs(round(value)):,.0f}"
    else:
        body = f"{abs(value):,.{decimals}f}"
    sign = "-" if value < -0.0000001 else ""
    return f"{symbol} {sign}{body}"


def money_short(value: float, symbol: str = "$") -> str:
    """Axis-style amount without cents: ``$ 300,000`` or ``$ -100,000``."""
    return money(value, symbol=symbol, decimals=0)


def percent(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def friendly_date(iso: str) -> str:
    return format_date(iso)
