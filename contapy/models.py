"""Plain data containers shared by the store and the widgets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Account:
    id: int
    name: str
    kind: str
    opening: float = 0.0
    unreconciled: int = 0
    sort_order: int = 0

    @property
    def warning(self) -> bool:
        """True when any posted transaction still needs reconciliation."""
        return self.unreconciled > 0


@dataclass(slots=True)
class Category:
    id: int
    name: str
    kind: str = "expense"
    color: str = "#888888"
    sort_order: int = 0


@dataclass(slots=True)
class Balance:
    account_id: int
    reconciled: float = 0.0
    cleared: float = 0.0
    today: float = 0.0
    future: float = 0.0


@dataclass(slots=True)
class ScheduledItem:
    id: int
    account_id: int
    account_name: str
    next_date: str
    payee: str
    category_id: int | None
    category_name: str
    category_color: str
    amount: float
    memo: str = ""
    status: str = "scheduled"
    kind: str = "expense"
    source: str = "scheduled"


@dataclass(slots=True)
class TransactionRow:
    id: int
    account_id: int
    account_name: str
    date: str
    payee: str
    category_id: int | None
    category_name: str
    category_color: str
    category_kind: str
    amount: float
    memo: str = ""
    cleared: bool = True
    reconciled: bool = False
    remind: bool = False
    flagged: bool = False
    voided: bool = False
    payment: str = ""
    number: str = ""
    tags: str = ""
    transfer_id: str | None = None
    balance: float = 0.0


@dataclass(slots=True)
class Slice:
    name: str
    amount: float
    color: str
    percent: float = 0.0


@dataclass(slots=True)
class ReportRow:
    key: str
    label: str
    expense: float = 0.0
    income: float = 0.0
    color: str = ""
    sort_order: int = 0

    @property
    def total(self) -> float:
        return self.income + self.expense

    @property
    def magnitude(self) -> float:
        return abs(self.total)


@dataclass(slots=True)
class MonthFlow:
    year: int
    month: int
    label: str
    income: float
    expense: float

    @property
    def net(self) -> float:
        return self.income - self.expense


@dataclass(slots=True)
class TransactionDraft:
    date: str
    account_id: int
    payee: str
    category_id: int | None
    amount: float
    memo: str = ""
    cleared: bool = True
    reconciled: bool = False
    remind: bool = False
    flagged: bool = False
    voided: bool = False
    payment: str = ""
    number: str = ""
    tags: str = ""
    transfer_account_id: int | None = None
    transfer_id: str | None = None
    scheduled: bool = False
