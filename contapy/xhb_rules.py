"""Import HomeBank automatic-assignment rules from a ``.xhb`` file.

HomeBank stores its automatic assignment rules as ``<asg>`` elements inside the
wallet XML. The element references categories and payees by key, so this module
also reads the ``<cat>`` and ``<pay>`` tables to translate those keys into the
names ContaPy uses. Categories are created on demand (including their parent)
through :meth:`DataStore.ensure_category`.

HomeBank's matching semantics are preserved:

* ``field=0`` matches the memo, ``field=1`` matches the payee.
* ``ASGF_EXACT`` makes the text match case-sensitive.
* ``ASGF_REGEX`` treats the search text as a regular expression.
* ``ASGF_AMOUNT`` additionally requires the amount to be equal.
* The ``DOPAY``/``DOCAT``/``DOMOD``/``DOTAG`` flags assign only when the field is
  still empty; the matching ``OVW*`` flags replace the existing value.

HomeBank's per-rule ``notes`` text has no matching flag; it is imported as a
ContaPy Notes assignment so the note is actually written to matched
transactions. HomeBank itself stores it without applying it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .db import DataStore
from .models import Rule

# HomeBank assignment flags (src/hb-assign.h, 5.10).
ASGF_EXACT = 1 << 0
ASGF_DOPAY = 1 << 1
ASGF_DOCAT = 1 << 2
ASGF_DOMOD = 1 << 3
ASGF_DOTAG = 1 << 4
ASGF_PREFILLED = 1 << 5
ASGF_AMOUNT = 1 << 7
ASGF_REGEX = 1 << 8
ASGF_OVWPAY = 1 << 9
ASGF_OVWCAT = 1 << 10
ASGF_OVWMOD = 1 << 11
ASGF_OVWTAG = 1 << 12

# HomeBank payment modes (src/hb-payment.h).
HOMEBANK_PAYMENT_MODES = {
    1: "Credit card",
    2: "Check",
    3: "Cash",
    4: "Bank transfer",
    5: "Internal transfer",
    6: "Debit card",
    7: "Standing order",
    8: "Electronic payment",
    9: "Deposit",
    10: "Financial institution fee",
    11: "Direct debit",
}

# HomeBank category flags: bit 1 marks an income category.
_HB_CATEGORY_INCOME = 1 << 1


@dataclass(slots=True)
class _Assignment:
    key: int
    pos: int
    flags: int
    field: int
    search: str
    notes: str
    payee_key: int | None
    category_key: int | None
    paymode: int
    amount: float
    tags: str


@dataclass(slots=True)
class XhbImportResult:
    """Outcome of one ``.xhb`` rules import."""

    file_name: str = ""
    imported: int = 0
    duplicates: int = 0
    skipped: int = 0
    categories_created: int = 0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Imported {self.imported} rule"
            f"{'' if self.imported == 1 else 's'} from {self.file_name or 'HomeBank'}."
        ]
        if self.categories_created:
            lines.append(
                f"Created {self.categories_created} "
                f"categor{'y' if self.categories_created == 1 else 'ies'}."
            )
        if self.duplicates:
            lines.append(
                f"Skipped {self.duplicates} rule"
                f"{'' if self.duplicates == 1 else 's'} that already exist."
            )
        if self.skipped:
            lines.append(
                f"Skipped {self.skipped} unusable rule"
                f"{'' if self.skipped == 1 else 's'}."
            )
        if not self.imported and not self.duplicates and not self.skipped:
            lines.append("This file does not contain any automatic assignments.")
        if self.warnings:
            lines.append("")
            lines.append("Details:")
            lines.extend(f"• {warning}" for warning in self.warnings[:8])
            if len(self.warnings) > 8:
                lines.append(f"… and {len(self.warnings) - 8} more.")
        return "\n".join(lines)


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _text(value: str | None) -> str:
    return "" if value in (None, "(null)") else value


def _parse_categories(root: ElementTree.Element) -> dict[int, tuple[str, int | None, str]]:
    """Map HomeBank category keys to ``(name, parent_key, kind)``."""
    categories: dict[int, tuple[str, int | None, str]] = {}
    for node in root.findall("cat"):
        key = _int(node.get("key"))
        name = _text(node.get("name")).strip()
        if not key or not name:
            continue
        parent = _int(node.get("parent")) or None
        flags = _int(node.get("flags"))
        kind = "income" if flags & _HB_CATEGORY_INCOME else "expense"
        categories[key] = (name, parent, kind)
    return categories


def _parse_payees(root: ElementTree.Element) -> dict[int, str]:
    payees: dict[int, str] = {}
    for node in root.findall("pay"):
        key = _int(node.get("key"))
        name = _text(node.get("name")).strip()
        if key and name:
            payees[key] = name
    return payees


def _parse_assignments(root: ElementTree.Element) -> list[_Assignment]:
    version = _float(root.get("v"), 1.0)
    assignments: list[_Assignment] = []
    for node in root.findall("asg"):
        key = _int(node.get("key"))
        flags = _int(node.get("flags"))
        if version <= 0.7:
            # Before v0.8 every rule assigned payee and category; case
            # sensitivity came from a separate attribute.
            flags |= ASGF_DOPAY | ASGF_DOCAT
            if _int(node.get("exact")):
                flags |= ASGF_EXACT
        assignments.append(
            _Assignment(
                key=key,
                pos=_int(node.get("pos"), key),
                flags=flags,
                field=_int(node.get("field")),
                search=_text(node.get("name")),
                notes=_text(node.get("notes")),
                payee_key=_int(node.get("payee")) or None,
                category_key=_int(node.get("category")) or None,
                paymode=_int(node.get("paymode")),
                amount=_float(node.get("amount")),
                tags=_text(node.get("tags")).strip(),
            )
        )
    assignments.sort(key=lambda item: (item.pos, item.key))
    return assignments


def _category_label(
    categories: dict[int, tuple[str, int | None, str]],
    key: int,
    seen: set[int] | None = None,
) -> str:
    name, parent, _kind = categories[key]
    if parent is None or parent not in categories or (seen and key in seen):
        return name
    seen = (seen or set()) | {key}
    return f"{_category_label(categories, parent, seen)} : {name}"


def _ensure_category(
    store: DataStore,
    categories: dict[int, tuple[str, int | None, str]],
    key: int,
    cache: dict[int, int],
) -> int:
    if key in cache:
        return cache[key]
    name, parent, kind = categories[key]
    if parent is not None and parent in categories:
        label = f"{_category_label(categories, parent)} : {name}"
        _ensure_category(store, categories, parent, cache)
    else:
        label = name
    category_id = store.ensure_category(label, kind)
    cache[key] = category_id
    return category_id


def _signature(rule: Rule, category_label: str) -> tuple[object, ...]:
    return (
        rule.search,
        rule.match_memo,
        rule.match_payee,
        rule.case_sensitive,
        rule.regex,
        rule.amount_enabled,
        rule.amount_op,
        round(rule.amount, 4),
        rule.assign_payee,
        rule.payee_overwrite,
        category_label,
        rule.category_overwrite,
        rule.assign_payment,
        rule.payment_overwrite,
        rule.assign_tags,
        rule.tags_overwrite,
        rule.assign_memo,
        rule.memo_overwrite,
    )


def _existing_signatures(store: DataStore) -> set[tuple[object, ...]]:
    signatures: set[tuple[object, ...]] = set()
    for rule in store.rules():
        category = store.category(rule.category_id)
        signatures.add(
            _signature(rule, category.full_name if category is not None else "")
        )
    return signatures


def import_xhb_rules(store: DataStore, path: str | Path) -> XhbImportResult:
    """Read HomeBank assignments from *path* and add them to *store*.

    The file is parsed in HomeBank position order. Rules that reference a
    missing payee or category still import their remaining assignments; a rule
    that has no usable assignment at all is skipped. Rules already present in
    ContaPy (same condition and assignments) are not duplicated.
    """
    source = Path(path)
    try:
        root = ElementTree.parse(source).getroot()
    except (ElementTree.ParseError, OSError) as error:
        raise ValueError(f"Could not read {source.name}: {error}") from error
    if root.tag != "homebank":
        raise ValueError(f"{source.name} is not a HomeBank wallet file")

    categories = _parse_categories(root)
    payees = _parse_payees(root)
    assignments = _parse_assignments(root)

    result = XhbImportResult(file_name=source.name)
    existing = _existing_signatures(store)
    before_categories = len(store.categories())
    category_ids: dict[int, int] = {}

    def describe(assignment: _Assignment) -> str:
        label = assignment.search or f"rule {assignment.key}"
        return f"“{label}”"

    for assignment in assignments:
        if assignment.flags & ASGF_PREFILLED:
            result.skipped += 1
            result.warnings.append(
                f"{describe(assignment)}: prefilled-from-transaction rule skipped."
            )
            continue

        flags = assignment.flags
        search = assignment.search
        amount_enabled = bool(flags & ASGF_AMOUNT)
        if not search and not amount_enabled:
            result.skipped += 1
            result.warnings.append(f"{describe(assignment)}: no condition.")
            continue

        match_payee = assignment.field == 1
        assign_payee = ""
        if flags & (ASGF_DOPAY | ASGF_OVWPAY) and assignment.payee_key is not None:
            name = payees.get(assignment.payee_key)
            if name:
                assign_payee = name
            else:
                result.warnings.append(
                    f"{describe(assignment)}: payee #{assignment.payee_key} not found."
                )

        category_key: int | None = None
        category_label = ""
        if flags & (ASGF_DOCAT | ASGF_OVWCAT) and assignment.category_key is not None:
            if assignment.category_key in categories:
                category_key = assignment.category_key
                category_label = _category_label(categories, category_key)
            else:
                result.warnings.append(
                    f"{describe(assignment)}: category #{assignment.category_key} "
                    "not found."
                )

        assign_payment = ""
        if flags & (ASGF_DOMOD | ASGF_OVWMOD):
            assign_payment = HOMEBANK_PAYMENT_MODES.get(assignment.paymode, "")

        assign_tags = ""
        if flags & (ASGF_DOTAG | ASGF_OVWTAG):
            assign_tags = assignment.tags

        # ``notes`` has no HomeBank flag; it is a note shown on the rule. Map it
        # to ContaPy's Notes assignment so matched transactions receive it.
        assign_memo = assignment.notes

        if not (assign_payee or category_key or assign_payment or assign_tags or assign_memo):
            result.skipped += 1
            result.warnings.append(f"{describe(assignment)}: no usable assignment.")
            continue

        candidate = Rule(
            search=search,
            match_memo=not match_payee,
            match_payee=match_payee,
            case_sensitive=bool(flags & ASGF_EXACT),
            regex=bool(flags & ASGF_REGEX),
            amount_enabled=amount_enabled,
            amount_and=True,
            amount_op="=",
            amount=assignment.amount,
            assign_payee=assign_payee,
            payee_overwrite=bool(flags & ASGF_OVWPAY),
            category_overwrite=bool(flags & ASGF_OVWCAT),
            assign_payment=assign_payment,
            payment_overwrite=bool(flags & ASGF_OVWMOD),
            assign_tags=assign_tags,
            tags_overwrite=bool(flags & ASGF_OVWTAG),
            assign_memo=assign_memo,
            memo_overwrite=bool(assign_memo),
        )

        signature = _signature(candidate, category_label)
        if signature in existing:
            result.duplicates += 1
            continue

        try:
            candidate.validate()
        except ValueError as error:
            result.skipped += 1
            result.warnings.append(f"{describe(assignment)}: {error}")
            continue

        if category_key is not None:
            try:
                candidate.category_id = _ensure_category(
                    store, categories, category_key, category_ids
                )
            except ValueError as error:
                result.skipped += 1
                result.warnings.append(f"{describe(assignment)}: {error}")
                continue

        store.add_rule(candidate)
        existing.add(signature)
        result.imported += 1

    result.categories_created = len(store.categories()) - before_categories
    return result
