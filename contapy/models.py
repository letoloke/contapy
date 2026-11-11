"""Plain data containers shared by the store and the widgets."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


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
    parent_id: int | None = None
    parent_name: str = ""

    @property
    def full_name(self) -> str:
        """HomeBank-style label, e.g. ``Bills : Electricity``."""
        return f"{self.parent_name} : {self.name}" if self.parent_name else self.name


def ordered_categories(categories: list[Category]) -> list[Category]:
    """Parents alphabetically, each followed by its alphabetically sorted subs."""
    by_parent: dict[int | None, list[Category]] = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)
    ordered: list[Category] = []

    def emit(parent_id: int | None) -> None:
        for category in sorted(
            by_parent.pop(parent_id, []),
            key=lambda item: (item.name.casefold(), item.id),
        ):
            ordered.append(category)
            if parent_id is None:
                emit(category.id)

    emit(None)
    # Anything left over belongs to a category that no longer exists; keep it
    # visible at the end rather than dropping rows from the UI.
    for remaining in by_parent.values():
        ordered.extend(sorted(remaining, key=lambda item: item.name.casefold()))
    return ordered


@dataclass(slots=True)
class BudgetStatus:
    """Monthly budget progress for one category."""

    category_id: int
    category_name: str
    color: str
    budget: float
    spent: float
    trend: list[tuple[str, float]] = field(default_factory=list)

    @property
    def remaining(self) -> float:
        return self.budget - self.spent

    @property
    def ratio(self) -> float:
        return self.spent / self.budget if self.budget > 0 else 0.0

    @property
    def over(self) -> bool:
        return self.budget > 0 and self.spent > self.budget + 0.005


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


@dataclass(slots=True)
class Rule:
    """A matching condition plus the assignments applied to a transaction.

    ``search`` is matched against the selected fields. ``amount``, when enabled,
    compares the signed transaction amount using ``amount_op``: ``-`` means "at
    most", ``+`` means "at least" and ``=`` means exactly. ``amount_and``
    combines the amount filter with the text filter using AND when true, or OR
    when false.
    """

    id: int = 0
    name: str = ""
    enabled: bool = True
    sort_order: int = 0
    search: str = ""
    match_memo: bool = True
    match_payee: bool = False
    case_sensitive: bool = False
    regex: bool = False
    amount_enabled: bool = False
    amount_and: bool = True
    amount_op: str = "="
    amount: float = 0.0
    assign_payee: str = ""
    payee_overwrite: bool = False
    category_id: int | None = None
    category_overwrite: bool = False
    assign_payment: str = ""
    payment_overwrite: bool = False
    assign_tags: str = ""
    tags_overwrite: bool = False
    assign_memo: str = ""
    memo_overwrite: bool = False

    def text_matches(self, payee: str, memo: str) -> bool:
        """Whether the search text appears in the selected fields."""
        if not self.search:
            return False
        fields: list[str] = []
        if self.match_payee:
            fields.append(payee or "")
        if self.match_memo:
            fields.append(memo or "")
        if not fields:
            return False
        if self.regex:
            flags = 0 if self.case_sensitive else re.IGNORECASE
            try:
                pattern = re.compile(self.search, flags)
            except re.error:
                return False
            return any(pattern.search(value) for value in fields)
        if self.case_sensitive:
            return any(self.search in value for value in fields)
        needle = self.search.casefold()
        return any(needle in value.casefold() for value in fields)

    def amount_matches(self, amount: float) -> bool:
        """Whether the signed amount satisfies the optional filter."""
        if not self.amount_enabled:
            return False
        if self.amount_op == "-":
            return amount <= self.amount + 1e-9
        if self.amount_op == "+":
            return amount >= self.amount - 1e-9
        return abs(amount - self.amount) < 0.005

    def matches(self, payee: str, memo: str, amount: float) -> bool:
        """Match a transaction, combining text and amount conditions."""
        has_text = bool(self.search) and (self.match_payee or self.match_memo)
        text_ok = self.text_matches(payee, memo) if has_text else None
        amount_ok = self.amount_matches(amount) if self.amount_enabled else None
        if amount_ok is None:
            return bool(text_ok)
        if text_ok is None:
            return amount_ok
        return (text_ok and amount_ok) if self.amount_and else (text_ok or amount_ok)

    def validate(self) -> None:
        """Raise ``ValueError`` for a condition or assignment that cannot work."""
        if not self.search and not self.amount_enabled:
            raise ValueError("Add search text or enable the amount condition.")
        if self.search and not (self.match_memo or self.match_payee):
            raise ValueError("Choose at least one field to search in (Memo or Payee).")
        if self.regex and self.search:
            try:
                re.compile(self.search)
            except re.error as error:
                raise ValueError(f"Invalid regular expression: {error}") from error
