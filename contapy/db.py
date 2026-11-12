"""SQLite persistence for accounts, transactions and schedules.

Everything the dashboard shows is derived from the ledger: account balances,
the category donut and the monthly income/expense bars.  No figures are stored
as display-only snapshots.
"""

from __future__ import annotations

import calendar
import csv
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from datetime import date, timedelta
from pathlib import Path

from .csv_io import (
    header_signature,
    normalize,
    parse_amount,
    parse_date,
    read_csv_plan,
    statuses_from_row,
)
from .models import (
    Account,
    Balance,
    BudgetStatus,
    Category,
    MonthFlow,
    ReportRow,
    Rule,
    ScheduledItem,
    Slice,
    TransactionDraft,
    TransactionRow,
)
from .omarchy import theme_category_color

#: Marker for bulk updates that should leave a column untouched.  ``None`` is a
#: real value for nullable columns such as ``category_id``.
_UNCHANGED = object()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    opening         REAL NOT NULL DEFAULT 0,
    warning         INTEGER NOT NULL DEFAULT 0,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    last_reconciled TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'expense',
    color       TEXT NOT NULL DEFAULT '#888888',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    parent_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS budgets (
    category_id INTEGER PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
    amount      REAL NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    date        TEXT NOT NULL,
    payee       TEXT NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    amount      REAL NOT NULL,
    memo        TEXT NOT NULL DEFAULT '',
    cleared     INTEGER NOT NULL DEFAULT 1,
    reconciled  INTEGER NOT NULL DEFAULT 0,
    remind      INTEGER NOT NULL DEFAULT 0,
    flagged     INTEGER NOT NULL DEFAULT 0,
    voided      INTEGER NOT NULL DEFAULT 0,
    payment     TEXT NOT NULL DEFAULT '',
    number      TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    transfer_id TEXT
);

CREATE TABLE IF NOT EXISTS scheduled (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    next_date   TEXT NOT NULL,
    payee       TEXT NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    amount      REAL NOT NULL,
    memo        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'scheduled'
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS rules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1,
    sort_order        INTEGER NOT NULL DEFAULT 0,
    search            TEXT NOT NULL DEFAULT '',
    match_memo        INTEGER NOT NULL DEFAULT 1,
    match_payee       INTEGER NOT NULL DEFAULT 0,
    case_sensitive    INTEGER NOT NULL DEFAULT 0,
    regex             INTEGER NOT NULL DEFAULT 0,
    amount_enabled    INTEGER NOT NULL DEFAULT 0,
    amount_and        INTEGER NOT NULL DEFAULT 1,
    amount_op         TEXT NOT NULL DEFAULT '=',
    amount            REAL NOT NULL DEFAULT 0,
    assign_payee      TEXT NOT NULL DEFAULT '',
    payee_overwrite   INTEGER NOT NULL DEFAULT 0,
    category_id       INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    category_overwrite INTEGER NOT NULL DEFAULT 0,
    assign_payment    TEXT NOT NULL DEFAULT '',
    payment_overwrite INTEGER NOT NULL DEFAULT 0,
    assign_tags       TEXT NOT NULL DEFAULT '',
    tags_overwrite    INTEGER NOT NULL DEFAULT 0,
    assign_memo       TEXT NOT NULL DEFAULT '',
    memo_overwrite    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS import_profiles (
    signature  TEXT PRIMARY KEY,
    headers    TEXT NOT NULL,
    mapping    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_sched_date ON scheduled(next_date);
"""

KIND_LABELS = ["Bank", "Cash", "Credit card", "Savings"]


def _migrate_legacy_database(old_path: Path, new_path: Path) -> None:
    """Copy a pre-rename database to the ContaPy location on first run.

    Only runs when the ContaPy database does not exist yet and the old Budget
    one does. The original file is left untouched. A failed copy is rolled back
    so the next launch can try again.
    """
    if new_path.exists() or not old_path.exists():
        return

    copied: list[Path] = []
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            source = old_path.with_name(old_path.name + suffix)
            if source.exists():
                target = new_path.with_name(new_path.name + suffix)
                shutil.copy2(source, target)
                copied.append(target)
    except OSError:
        for target in copied:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass


def default_db_path() -> Path:
    # CONTAPY_DB is the current name; BUDGET_DB is honoured for older setups.
    override = os.environ.get("CONTAPY_DB") or os.environ.get("BUDGET_DB")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "contapy" / "contapy.db"
    _migrate_legacy_database(base / "budget" / "budget.db", path)
    return path


BACKUP_DIR_NAME = "dailylbaka"
ImportFingerprint = tuple[int, str, str, str, float]


def daily_backup_dir(db_path: str | Path) -> Path:
    """Folder for the automatic daily copies, beside the active database."""
    return Path(db_path).expanduser().parent / BACKUP_DIR_NAME


def _shift_month_start(day: date, months: int) -> date:
    """First day of the month ``months`` away from ``day``."""
    index = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, 1)


def _period_start(anchor: date, start_day: int) -> date:
    """First day of the budget period starting in ``anchor``'s month.

    Days that do not exist in a month are clamped to its last day, so a start
    day of 31 works in February.
    """
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return date(anchor.year, anchor.month, min(max(1, start_day), last_day))


def _budget_period(anchor: date, start_day: int) -> tuple[date, date]:
    """Inclusive ``(first, last)`` day of a budget period.

    The period is anchored to ``anchor``'s calendar month and runs from
    ``start_day`` to the day before the next month's start day. With the
    default start day of 1 it is simply the calendar month.
    """
    start = _period_start(anchor, start_day)
    next_start = _period_start(_shift_month_start(start, 1), start_day)
    return start, next_start - timedelta(days=1)


def import_fingerprint(
    account_id: int, date_text: str, amount: float, memo: str, payee: str
) -> ImportFingerprint:
    """Identity used to spot CSV rows already present in a ledger.

    The memo is the primary field. Date and amount disambiguate recurring
    payments that happen to share a memo. When the memo is empty the payee is
    used instead, so rows without a description still get a useful check.
    """
    memo_key = normalize(memo)
    if memo_key:
        kind, text = "memo", memo_key
    else:
        payee_key = normalize(payee)
        if payee_key:
            kind, text = "payee", payee_key
        else:
            kind, text = "blank", ""
    return (int(account_id), kind, text, date_text, round(float(amount), 2))


class DataStore:
    def __init__(self, path: str | Path | None = None, seed: bool = True):
        self.path = Path(path).expanduser() if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()
        if seed:
            from .seed import seed_if_empty

            if seed_if_empty(self.conn):
                self.conn.commit()

    def _migrate(self) -> None:
        """Add ledger state columns to databases created before they existed."""
        category_columns = {
            row[1] for row in self.conn.execute("PRAGMA table_info(categories)")
        }
        if "parent_id" not in category_columns:
            self.conn.execute(
                "ALTER TABLE categories ADD COLUMN parent_id INTEGER "
                "REFERENCES categories(id) ON DELETE SET NULL"
            )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(transactions)")}
        if "reconciled" not in columns:
            self.conn.execute(
                "ALTER TABLE transactions ADD COLUMN reconciled INTEGER NOT NULL DEFAULT 0"
            )
            # Older builds had no separate reconcile concept; everything that
            # was cleared is treated as reconciled to keep balances stable.
            self.conn.execute("UPDATE transactions SET reconciled = cleared")
        if "remind" not in columns:
            self.conn.execute(
                "ALTER TABLE transactions ADD COLUMN remind INTEGER NOT NULL DEFAULT 0"
            )
        if "flagged" not in columns:
            self.conn.execute(
                "ALTER TABLE transactions ADD COLUMN flagged INTEGER NOT NULL DEFAULT 0"
            )
        if "voided" not in columns:
            self.conn.execute(
                "ALTER TABLE transactions ADD COLUMN voided INTEGER NOT NULL DEFAULT 0"
            )
        for name in ("payment", "number", "tags"):
            if name not in columns:
                self.conn.execute(
                    f"ALTER TABLE transactions ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                )
        if "transfer_id" not in columns:
            self.conn.execute("ALTER TABLE transactions ADD COLUMN transfer_id TEXT")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tx_transfer ON transactions(transfer_id)"
        )

    # ---------------------------------------------------------------- basics
    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def backup_to(self, path: str | Path) -> Path:
        """Write a consistent snapshot of this database to ``path``.

        The copy is written to a temporary file first and moved into place, so
        an interrupted save never leaves a half-written database behind. The
        live database stays open and usable throughout.
        """
        target = Path(path).expanduser()
        if target.resolve() == self.path.resolve():
            return self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        try:
            destination = sqlite3.connect(temporary)
            try:
                self.conn.backup(destination)
            finally:
                destination.close()
            os.replace(temporary, target)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        # A replaced database must not inherit stale sidecars from an older file.
        for suffix in ("-wal", "-shm"):
            try:
                target.with_name(target.name + suffix).unlink(missing_ok=True)
            except OSError:
                pass
        return target

    def ensure_daily_backup(
        self, directory: str | Path | None = None, day: date | None = None
    ) -> Path | None:
        """Create today's backup once; return its path only when newly written."""
        if directory is None:
            folder = daily_backup_dir(self.path)
        else:
            folder = Path(directory).expanduser()
        day = day or date.today()
        target = folder / f"{self.path.stem}-{day.isoformat()}.db"
        if target.exists():
            return None
        return self.backup_to(target)

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    # -------------------------------------------------------------- accounts
    def accounts(self) -> list[Account]:
        # The warning marker is derived, not stored: an account needs
        # attention while it has posted transactions that are not reconciled.
        # Future-dated entries are excluded because they have not happened yet.
        today = date.today().isoformat()
        rows = self._rows(
            """
            SELECT a.id, a.name, a.kind, a.opening, a.sort_order,
                   (
                       SELECT COUNT(*)
                       FROM transactions t
                       WHERE t.account_id = a.id
                         AND t.reconciled = 0
                         AND t.voided = 0
                         AND t.date <= ?
                   ) AS unreconciled
            FROM accounts a
            ORDER BY a.sort_order, a.id
            """,
            (today,),
        )
        return [
            Account(
                id=r["id"],
                name=r["name"],
                kind=r["kind"],
                opening=float(r["opening"]),
                unreconciled=int(r["unreconciled"] or 0),
                sort_order=r["sort_order"],
            )
            for r in rows
        ]

    def account(self, account_id: int) -> Account | None:
        for account in self.accounts():
            if account.id == account_id:
                return account
        return None

    def add_account(self, name: str, kind: str, opening: float = 0.0) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM accounts").fetchone()
        cur = self.conn.execute(
            "INSERT INTO accounts(name, kind, opening, sort_order) VALUES (?,?,?,?)",
            (name.strip(), kind, float(opening), row[0]),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_account(self, account_id: int, name: str, kind: str, opening: float) -> None:
        self.conn.execute(
            "UPDATE accounts SET name=?, kind=?, opening=? WHERE id=?",
            (name.strip(), kind, float(opening), account_id),
        )
        self.conn.commit()

    def delete_account(self, account_id: int) -> None:
        self.conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        self.conn.commit()

    def move_account(self, account_id: int, direction: int) -> None:
        account = self.account(account_id)
        if account is None:
            return
        siblings = [a for a in self.accounts() if a.kind == account.kind]
        index = next((i for i, a in enumerate(siblings) if a.id == account_id), -1)
        target = index + direction
        if index < 0 or target < 0 or target >= len(siblings):
            return
        siblings[index], siblings[target] = siblings[target], siblings[index]
        for order, item in enumerate(siblings):
            self.conn.execute("UPDATE accounts SET sort_order=? WHERE id=?", (order, item.id))
        self.conn.commit()

    def balances(self, as_of: date | None = None) -> dict[int, Balance]:
        today = (as_of or date.today()).isoformat()
        rows = self._rows(
            """
            SELECT a.id AS account_id,
                   a.opening AS opening,
                   COALESCE(SUM(CASE WHEN t.reconciled = 1 AND t.voided = 0 AND t.date <= ? THEN t.amount END), 0) AS reconciled_sum,
                   COALESCE(SUM(CASE WHEN (t.cleared = 1 OR t.reconciled = 1) AND t.voided = 0 AND t.date <= ? THEN t.amount END), 0) AS cleared_sum,
                   COALESCE(SUM(CASE WHEN t.voided = 0 AND t.date <= ? THEN t.amount END), 0) AS today_sum
            FROM accounts a
            LEFT JOIN transactions t ON t.account_id = a.id
            GROUP BY a.id
            """,
            (today, today, today),
        )
        # Scheduled items are not part of the ledger until posted, so the
        # "Future" column is today plus already-posted future-dated transactions.
        posted_future = {
            r["account_id"]: float(r["amount"])
            for r in self._rows(
                "SELECT account_id, COALESCE(SUM(amount), 0) AS amount "
                "FROM transactions WHERE date > ? AND voided = 0 GROUP BY account_id",
                (today,),
            )
        }

        result: dict[int, Balance] = {}
        for r in rows:
            opening = float(r["opening"])
            reconciled = opening + float(r["reconciled_sum"])
            cleared = opening + float(r["cleared_sum"])
            current = opening + float(r["today_sum"])
            result[r["account_id"]] = Balance(
                account_id=r["account_id"],
                reconciled=reconciled,
                cleared=cleared,
                today=current,
                future=current + posted_future.get(r["account_id"], 0.0),
            )
        return result

    # ------------------------------------------------------------ categories
    def categories(self) -> list[Category]:
        rows = self._rows(
            """
            SELECT c.id, c.name, c.kind, c.color, c.sort_order, c.parent_id,
                   p.name AS parent_name
            FROM categories c
            LEFT JOIN categories p ON p.id = c.parent_id
            ORDER BY c.kind DESC, c.name COLLATE NOCASE, c.id
            """
        )
        return [
            Category(
                id=r["id"],
                name=r["name"],
                kind=r["kind"],
                color=r["color"],
                sort_order=r["sort_order"],
                parent_id=r["parent_id"],
                parent_name=r["parent_name"] or "",
            )
            for r in rows
        ]

    def category(self, category_id: int | None) -> Category | None:
        if category_id is None:
            return None
        for category in self.categories():
            if category.id == category_id:
                return category
        return None

    def _next_category_order(self) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories"
        ).fetchone()
        return int(row[0])

    def _validate_category(
        self,
        name: str,
        kind: str,
        parent_id: int | None,
        *,
        exclude_id: int | None = None,
    ) -> Category | None:
        """Check a category's name/kind/parent, returning its parent."""
        if not name:
            raise ValueError("Category names cannot be empty")
        if kind not in ("expense", "income"):
            raise ValueError(f"unknown category kind: {kind}")
        parent = self.category(parent_id) if parent_id is not None else None
        if parent is not None:
            if parent.parent_id is not None:
                raise ValueError(
                    "Subcategories cannot have subcategories of their own"
                )
            if parent.kind != kind:
                raise ValueError("A subcategory must share its parent's type")
        duplicate = any(
            category.id != exclude_id
            and category.parent_id == parent_id
            and category.name.casefold() == name.casefold()
            for category in self.categories()
        )
        if duplicate:
            raise ValueError(f"A category named “{name}” already exists")
        return parent

    def add_category(
        self,
        name: str,
        kind: str = "expense",
        parent_id: int | None = None,
        color: str | None = None,
    ) -> int:
        """Create a category, or a subcategory when ``parent_id`` is given."""
        name = name.strip()
        parent = self._validate_category(name, kind, parent_id)
        if color is None:
            color = parent.color if parent is not None else theme_category_color(
                name, "#8a8a8a"
            )
        # Subcategories share their parent's sort order so reports list them
        # directly under the parent they belong to.
        sort_order = (
            parent.sort_order
            if parent is not None
            else self._next_category_order()
        )
        cur = self.conn.execute(
            "INSERT INTO categories(name, kind, color, sort_order, parent_id) "
            "VALUES (?,?,?,?,?)",
            (name, kind, color, sort_order, parent_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_category(
        self,
        category_id: int,
        name: str,
        kind: str,
        parent_id: int | None,
        color: str | None = None,
    ) -> None:
        """Rename, retype or move a category; children follow its type."""
        category = self.category(category_id)
        if category is None:
            raise ValueError("That category no longer exists")
        if parent_id == category_id:
            raise ValueError("A category cannot be its own subcategory")
        name = name.strip()
        parent = self._validate_category(
            name, kind, parent_id, exclude_id=category_id
        )
        if color is None:
            color = parent.color if parent is not None else category.color
        sort_order = (
            parent.sort_order
            if parent is not None
            else self._next_category_order()
        )
        self.conn.execute(
            """
            UPDATE categories
            SET name=?, kind=?, parent_id=?, color=?, sort_order=?
            WHERE id=?
            """,
            (name, kind, parent_id, color, sort_order, category_id),
        )
        # Children always share their parent's type.
        self.conn.execute(
            "UPDATE categories SET kind=? WHERE parent_id=?", (kind, category_id)
        )
        self.conn.commit()

    def delete_category(self, category_id: int) -> int:
        """Remove a category, moving its transactions to the parent.

        Subcategories of a deleted parent become top-level categories; a
        deleted subcategory's transactions move to its parent. Returns how
        many posted transactions were reassigned.
        """
        category = self.category(category_id)
        if category is None:
            return 0
        target = category.parent_id
        moved = self.conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id=?", (category_id,)
        ).fetchone()[0]
        self.conn.execute(
            "UPDATE transactions SET category_id=? WHERE category_id=?",
            (target, category_id),
        )
        self.conn.execute(
            "UPDATE scheduled SET category_id=? WHERE category_id=?",
            (target, category_id),
        )
        self.conn.execute(
            "UPDATE categories SET parent_id=NULL WHERE parent_id=?", (category_id,)
        )
        self.conn.execute("DELETE FROM budgets WHERE category_id=?", (category_id,))
        self.conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
        self.conn.commit()
        return int(moved)


    # ---------------------------------------------------------------- budgets
    def budgets(self) -> dict[int, float]:
        """Monthly budget amount per category, ignoring removed/zero budgets."""
        rows = self._rows(
            "SELECT category_id, amount FROM budgets WHERE amount > 0 ORDER BY category_id"
        )
        return {int(row["category_id"]): float(row["amount"]) for row in rows}

    def budget_amount(self, category_id: int) -> float:
        row = self.conn.execute(
            "SELECT amount FROM budgets WHERE category_id = ?", (category_id,)
        ).fetchone()
        return float(row["amount"]) if row is not None else 0.0

    def budget_start_day(self) -> int:
        """Day of the month a budget period starts (1–31, default 1)."""
        raw = self.get_setting("budget_start_day", "1")
        try:
            day = int(raw or 1)
        except (TypeError, ValueError):
            day = 1
        return min(31, max(1, day))

    def set_budget_start_day(self, day: int) -> None:
        """Remember the day of the month budget periods start."""
        self.set_setting("budget_start_day", str(min(31, max(1, int(day)))))

    def budget_period(
        self, anchor: date, start_day: int | None = None
    ) -> tuple[date, date]:
        """Inclusive ``(first, last)`` day of the period anchored to ``anchor``."""
        if start_day is None:
            start_day = self.budget_start_day()
        return _budget_period(anchor, start_day)

    def current_budget_period(self, today: date | None = None) -> date:
        """First day of the calendar month whose budget period contains today."""
        today = today or date.today()
        start_day = self.budget_start_day()
        start = _period_start(today, start_day)
        if today >= start:
            return today.replace(day=1)
        return _shift_month_start(today.replace(day=1), -1)

    def set_budget(self, category_id: int, amount: float) -> None:
        """Set or clear one category's monthly budget."""
        amount = round(float(amount), 2)
        if amount <= 0:
            self.conn.execute(
                "DELETE FROM budgets WHERE category_id = ?", (category_id,)
            )
        else:
            self.conn.execute(
                """
                INSERT INTO budgets(category_id, amount, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(category_id) DO UPDATE SET
                    amount = excluded.amount,
                    updated_at = excluded.updated_at
                """,
                (category_id, amount, datetime.now().isoformat(timespec="seconds")),
            )
        self.conn.commit()

    def budget_report(
        self, month_start: date, months: int = 6
    ) -> list[BudgetStatus]:
        """Budgeted expense categories with period spend and a trend.

        ``month_start`` anchors the last period; its first day selects the
        calendar month. Periods honour :meth:`budget_start_day`, so a start day
        of 15 reports 15 January – 14 February as January.
        """
        months = max(1, int(months))
        start_day = self.budget_start_day()
        anchor = month_start.replace(day=1)
        periods: list[tuple[str, str, date, date]] = []
        for index in range(months):
            current = _shift_month_start(anchor, -(months - 1) + index)
            first, last = _budget_period(current, start_day)
            periods.append(
                (
                    current.strftime("%Y-%m"),
                    calendar.month_abbr[current.month],
                    first,
                    last,
                )
            )
        month_keys = [(key, label) for key, label, _first, _last in periods]

        rows = self._rows(
            """
            SELECT t.category_id AS category_id,
                   t.date AS date,
                   SUM(-t.amount) AS spent
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.voided = 0
              AND t.amount < 0
              AND c.kind = 'expense'
              AND t.date BETWEEN ? AND ?
            GROUP BY t.category_id, t.date
            """,
            (periods[0][2].isoformat(), periods[-1][3].isoformat()),
        )
        by_category: dict[int, dict[str, float]] = {}
        for row in rows:
            when = date.fromisoformat(str(row["date"]))
            for key, _label, first, last in periods:
                if first <= when <= last:
                    category_id = int(row["category_id"])
                    bucket = by_category.setdefault(category_id, {})
                    bucket[key] = bucket.get(key, 0.0) + float(row["spent"])
                    break

        # A budget on a category also covers its subcategories' spending.
        children_of: dict[int, list[int]] = {}
        for category in self.categories():
            if category.parent_id is not None:
                children_of.setdefault(category.parent_id, []).append(category.id)

        budgets = self.budgets()
        statuses: list[BudgetStatus] = []
        for category in self.categories():
            if category.kind != "expense" or category.id not in budgets:
                continue
            covered = [category.id, *children_of.get(category.id, [])]
            monthly = {
                key: sum(
                    by_category.get(child_id, {}).get(key, 0.0)
                    for child_id in covered
                )
                for key, _ in month_keys
            }
            trend = [
                (label, monthly.get(key, 0.0)) for key, label in month_keys
            ]
            statuses.append(
                BudgetStatus(
                    category_id=category.id,
                    category_name=category.full_name,
                    color=category.color,
                    budget=budgets[category.id],
                    spent=trend[-1][1],
                    trend=trend,
                )
            )
        return statuses

    # --------------------------------------------------------------- reports
    def date_span(self) -> tuple[date, date]:
        """First and last transaction date, or today when the ledger is empty."""
        row = self.conn.execute("SELECT MIN(date), MAX(date) FROM transactions WHERE voided = 0").fetchone()
        if row is None or row[0] is None or row[1] is None:
            today = date.today()
            return today, today
        return date.fromisoformat(row[0]), date.fromisoformat(row[1])

    def _report_transactions(
        self,
        start: date,
        end: date,
        account_id: int | None = None,
        search: str = "",
    ) -> list[sqlite3.Row]:
        params: list = [start.isoformat(), end.isoformat()]
        clauses = ["t.date BETWEEN ? AND ?", "t.voided = 0"]
        if account_id is not None:
            clauses.append("t.account_id = ?")
            params.append(account_id)
        text = search.strip()
        if text:
            like = f"%{text}%"
            clauses.append(
                "(t.payee LIKE ? OR t.memo LIKE ? OR t.tags LIKE ? "
                "OR c.name LIKE ? OR p.name LIKE ?)"
            )
            params.extend([like, like, like, like, like])
        return self._rows(
            f"""
            SELECT t.date, t.amount, t.payee,
                   a.id AS account_id, a.name AS account_name,
                   c.id AS category_id, c.name AS category_name,
                   c.kind AS category_kind, c.color AS category_color,
                   c.sort_order AS category_sort,
                   p.name AS parent_name,
                   COALESCE(p.id, c.id) AS top_id,
                   COALESCE(p.name, c.name) AS top_name,
                   COALESCE(p.color, c.color) AS top_color,
                   COALESCE(p.sort_order, c.sort_order) AS top_sort
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN categories p ON p.id = c.parent_id
            WHERE {' AND '.join(clauses)}
            """,
            tuple(params),
        )

    @staticmethod
    def _report_includes(row: sqlite3.Row, kind: str) -> bool:
        # Uncategorised transactions appear in both reports, as HomeBank does.
        if row["category_id"] is None:
            return True
        return (row["category_kind"] or "expense") == kind

    def report_rows(
        self,
        start: date,
        end: date,
        kind: str = "expense",
        view_by: str = "category",
        account_id: int | None = None,
        search: str = "",
        sort_by_amount: bool = False,
        rollup: bool = False,
    ) -> list[ReportRow]:
        """Aggregate a date range into report rows (category, payee or account).

        Category views can either list every subcategory (``rollup=False``)
        or fold subcategories into their parent (``rollup=True``).
        """
        groups: dict[str, ReportRow] = {}
        for row in self._report_transactions(start, end, account_id, search):
            if not self._report_includes(row, kind):
                continue
            if view_by == "payee":
                label = str(row["payee"] or "").strip() or "(no payee)"
                key = f"payee:{normalize(label)}"
                color, sort_order = "", 0
            elif view_by == "account":
                label = str(row["account_name"] or "(no account)")
                key = f"account:{row['account_id']}"
                color, sort_order = "", 0
            elif rollup:
                name = row["top_name"]
                label = str(name or "(no category)")
                key = f"category:{row['top_id'] or 'none'}"
                color = (
                    theme_category_color(str(name), str(row["top_color"]))
                    if name
                    else theme_category_color("", None)
                )
                sort_order = int(row["top_sort"] or 0)
            else:
                name = row["category_name"]
                parent_name = row["parent_name"]
                if name and parent_name:
                    label = f"{parent_name} : {name}"
                else:
                    label = str(name or "(no category)")
                key = f"category:{row['category_id'] or 'none'}"
                color = (
                    theme_category_color(str(name), str(row["category_color"]))
                    if name
                    else theme_category_color("", None)
                )
                sort_order = int(row["category_sort"] or 0)

            group = groups.get(key)
            if group is None:
                group = ReportRow(
                    key=key, label=label, color=color, sort_order=sort_order
                )
                groups[key] = group
            amount = float(row["amount"])
            if amount < 0:
                group.expense += amount
            else:
                group.income += amount

        rows = list(groups.values())
        if sort_by_amount:
            rows.sort(key=lambda item: (-item.magnitude, item.label.casefold()))
        else:
            rows.sort(key=lambda item: item.label.casefold())
        return rows

    def report_months(
        self,
        start: date,
        end: date,
        kind: str = "expense",
        account_id: int | None = None,
        search: str = "",
        sort_by_amount: bool = False,
    ) -> list[MonthFlow]:
        """Monthly totals for the Time report."""
        buckets: dict[str, list[float]] = {}
        for row in self._report_transactions(start, end, account_id, search):
            if not self._report_includes(row, kind):
                continue
            key = str(row["date"])[:7]
            income, expense = buckets.setdefault(key, [0.0, 0.0])
            amount = float(row["amount"])
            if amount < 0:
                expense += -amount
            else:
                income += amount
            buckets[key] = [income, expense]

        import calendar as _calendar

        flows: list[MonthFlow] = []
        for key in sorted(buckets):
            year, month = (int(part) for part in key.split("-"))
            income, expense = buckets[key]
            flows.append(
                MonthFlow(
                    year=year,
                    month=month,
                    label=_calendar.month_abbr[month],
                    income=income,
                    expense=expense,
                )
            )
        if sort_by_amount:
            flows.sort(key=lambda flow: -abs(flow.net))
        return flows

    # ---------------------------------------------------------------- charts
    def spend_by_category(
        self,
        start: date,
        end: date,
        account_id: int | None = None,
    ) -> tuple[list[Slice], float]:
        return self.category_slices(start, end, "expense", account_id)

    def category_slices(
        self,
        start: date,
        end: date,
        kind: str = "expense",
        account_id: int | None = None,
    ) -> tuple[list[Slice], float]:
        """Top ten categories of ``kind`` in a date range, plus an Other slice."""
        if kind not in ("expense", "income"):
            raise ValueError(f"unknown category kind: {kind}")
        expense = kind == "expense"
        sign = "-" if expense else ""
        comparison = "<" if expense else ">"
        params: list = [start.isoformat(), end.isoformat(), kind]
        account_sql = ""
        if account_id is not None:
            account_sql = " AND t.account_id = ?"
            params.append(account_id)
        rows = self._rows(
            f"""
            SELECT COALESCE(p.id, c.id) AS top_id,
                   COALESCE(p.name, c.name) AS name,
                   COALESCE(p.color, c.color) AS color,
                   SUM({sign}t.amount) AS total_amount
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            LEFT JOIN categories p ON p.id = c.parent_id
            WHERE t.date BETWEEN ? AND ?
              AND t.voided = 0
              AND t.amount {comparison} 0
              AND c.kind = ?
              {account_sql}
            GROUP BY top_id
            HAVING total_amount > 0
            ORDER BY total_amount DESC
            """,
            tuple(params),
        )
        items = [(r["name"], float(r["total_amount"]), r["color"]) for r in rows]
        total = sum(v for _, v, _ in items)
        if not items:
            return [], 0.0

        # Up to ten named categories plus an "Other" slice.
        named = [item for item in items if item[0] != "Other"]
        other = sum(v for n, v, _ in items if n == "Other")
        if len(named) > 10:
            other += sum(v for _, v, _ in named[10:])
            named = named[:10]
        slices = [
            Slice(name=n, amount=v, color=theme_category_color(n, color))
            for n, v, color in named
        ]
        if other > 0:
            slices.append(
                Slice(
                    name="Other",
                    amount=other,
                    color=theme_category_color("Other", "#77544d"),
                )
            )
        for item in slices:
            item.percent = item.amount / total if total else 0.0
        return slices, total

    def monthly_cashflow(
        self,
        months: int = 12,
        account_id: int | None = None,
        as_of: date | None = None,
    ) -> list[MonthFlow]:
        today = as_of or date.today()
        start_month = today.year * 12 + (today.month - 1) - (months - 1)
        start_year, start_m0 = divmod(start_month, 12)
        first = date(start_year, start_m0 + 1, 1)
        params: list = [first.isoformat()]
        account_sql = ""
        if account_id is not None:
            account_sql = " AND account_id = ?"
            params.append(account_id)
        rows = self._rows(
            f"""
            SELECT substr(date, 1, 7) AS ym,
                   SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS income,
                   SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS expense
            FROM transactions
            WHERE date >= ? AND voided = 0 AND category_id IS NOT NULL
              {account_sql}
            GROUP BY ym
            """,
            tuple(params),
        )
        by_month = {r["ym"]: (float(r["income"]), float(r["expense"])) for r in rows}

        import calendar as _calendar

        flows: list[MonthFlow] = []
        for offset in range(months):
            index = start_month + offset
            year, month0 = divmod(index, 12)
            month = month0 + 1
            income, expense = by_month.get(f"{year:04d}-{month:02d}", (0.0, 0.0))
            flows.append(
                MonthFlow(
                    year=year,
                    month=month,
                    label=_calendar.month_abbr[month],
                    income=income,
                    expense=expense,
                )
            )
        return flows

    # ------------------------------------------------------------- scheduled
    def scheduled_items(self, account_id: int | None = None) -> list[ScheduledItem]:
        params: tuple = ()
        where = ""
        if account_id is not None:
            where = "WHERE s.account_id = ?"
            params = (account_id,)
        rows = self._rows(
            f"""
            SELECT s.*, a.name AS account_name,
                   CASE WHEN p.name IS NOT NULL AND p.name <> ''
                        THEN p.name || ' : ' || c.name ELSE c.name END
                       AS category_name,
                   c.color AS category_color, c.kind AS category_kind
            FROM scheduled s
            JOIN accounts a ON a.id = s.account_id
            LEFT JOIN categories c ON c.id = s.category_id
            LEFT JOIN categories p ON p.id = c.parent_id
            {where}
            ORDER BY s.next_date, s.id
            """,
            params,
        )
        return [
            ScheduledItem(
                id=r["id"],
                account_id=r["account_id"],
                account_name=r["account_name"],
                next_date=r["next_date"],
                payee=r["payee"],
                category_id=r["category_id"],
                category_name=r["category_name"] or "Uncategorized",
                category_color=theme_category_color(r["category_name"], r["category_color"]),
                amount=float(r["amount"]),
                memo=r["memo"],
                status=r["status"],
                kind=r["category_kind"] or "expense",
            )
            for r in rows
        ]

    def scheduled_item(self, item_id: int) -> ScheduledItem | None:
        for item in self.scheduled_items():
            if item.id == item_id:
                return item
        return None

    def add_scheduled(self, draft: TransactionDraft) -> int:
        cur = self.conn.execute(
            "INSERT INTO scheduled(account_id, next_date, payee, category_id, amount, memo, status) "
            "VALUES (?,?,?,?,?,?, 'scheduled')",
            (
                draft.account_id,
                draft.date,
                draft.payee.strip(),
                draft.category_id,
                float(draft.amount),
                draft.memo.strip(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def post_scheduled(self, item_id: int) -> int:
        item = self.scheduled_item(item_id)
        if item is None:
            raise KeyError(f"No scheduled transaction {item_id}")
        cur = self.conn.execute(
            "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
            "cleared, reconciled, remind, flagged) "
            "VALUES (?,?,?,?,?,?,1,0,0,0)",
            (
                item.account_id,
                item.next_date,
                item.payee,
                item.category_id,
                item.amount,
                item.memo,
            ),
        )
        self.conn.execute("DELETE FROM scheduled WHERE id=?", (item_id,))
        self.conn.commit()
        return int(cur.lastrowid)

    def skip_scheduled(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM scheduled WHERE id=?", (item_id,))
        self.conn.commit()

    # ----------------------------------------------------------- transactions
    def add_transaction(self, draft: TransactionDraft) -> int:
        draft = self.apply_rules(draft)
        cleared = draft.reconciled or draft.cleared
        cur = self.conn.execute(
            "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
            "cleared, reconciled, remind, flagged, voided, payment, number, tags, transfer_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                draft.account_id,
                draft.date,
                draft.payee.strip(),
                draft.category_id,
                float(draft.amount),
                draft.memo.strip(),
                1 if cleared else 0,
                1 if draft.reconciled else 0,
                1 if draft.remind else 0,
                1 if draft.flagged else 0,
                1 if draft.voided else 0,
                draft.payment.strip(),
                draft.number.strip(),
                draft.tags.strip(),
                draft.transfer_id,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_transfer(self, draft: TransactionDraft, to_account_id: int) -> str:
        group = uuid.uuid4().hex
        self._insert_transfer(draft, to_account_id, group)
        self.conn.commit()
        return group

    def update_transfer(self, transfer_id: str, draft: TransactionDraft, to_account_id: int) -> str:
        self.conn.execute("DELETE FROM transactions WHERE transfer_id=?", (transfer_id,))
        self._insert_transfer(draft, to_account_id, transfer_id)
        self.conn.commit()
        return transfer_id

    def _insert_transfer(self, draft: TransactionDraft, to_account_id: int, group: str) -> None:
        amount = abs(float(draft.amount))
        cleared = draft.reconciled or draft.cleared
        payee = draft.payee.strip() or "Transfer"
        for account_id, signed_amount in (
            (draft.account_id, -amount),
            (to_account_id, amount),
        ):
            self.conn.execute(
                "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
                "cleared, reconciled, remind, flagged, voided, payment, number, tags, transfer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    account_id,
                    draft.date,
                    payee,
                    None,
                    signed_amount,
                    draft.memo.strip(),
                    1 if cleared else 0,
                    1 if draft.reconciled else 0,
                    1 if draft.remind else 0,
                    1 if draft.flagged else 0,
                    1 if draft.voided else 0,
                    draft.payment.strip(),
                    draft.number.strip(),
                    draft.tags.strip(),
                    group,
                ),
            )

    def transfer_legs(self, transfer_id: str) -> list[TransactionRow]:
        return [
            self._to_transaction_row(r)
            for r in self._transaction_query("WHERE t.transfer_id = ?", (transfer_id,))
        ]

    def update_transaction(self, transaction_id: int, draft: TransactionDraft) -> None:
        cleared = draft.reconciled or draft.cleared
        self.conn.execute(
            "UPDATE transactions SET account_id=?, date=?, payee=?, category_id=?, amount=?, "
            "memo=?, cleared=?, reconciled=?, remind=?, flagged=?, voided=?, payment=?, number=?, tags=? "
            "WHERE id=?",
            (
                draft.account_id,
                draft.date,
                draft.payee.strip(),
                draft.category_id,
                float(draft.amount),
                draft.memo.strip(),
                1 if cleared else 0,
                1 if draft.reconciled else 0,
                1 if draft.remind else 0,
                1 if draft.flagged else 0,
                1 if draft.voided else 0,
                draft.payment.strip(),
                draft.number.strip(),
                draft.tags.strip(),
                transaction_id,
            ),
        )
        self.conn.commit()

    def update_transactions(
        self,
        transaction_ids: list[int],
        *,
        payee: object = _UNCHANGED,
        category_id: object = _UNCHANGED,
        payment: object = _UNCHANGED,
        number: object = _UNCHANGED,
        tags: object = _UNCHANGED,
        memo: object = _UNCHANGED,
    ) -> None:
        """Update only the supplied fields on every listed transaction."""
        if not transaction_ids:
            return
        assignments: list[str] = []
        params: list = []
        for column, value in (
            ("payee", payee),
            ("category_id", category_id),
            ("payment", payment),
            ("number", number),
            ("tags", tags),
            ("memo", memo),
        ):
            if value is _UNCHANGED:
                continue
            assignments.append(f"{column}=?")
            params.append(value.strip() if isinstance(value, str) else value)
        if not assignments:
            return
        for start in range(0, len(transaction_ids), 500):
            chunk = transaction_ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            self.conn.execute(
                f"UPDATE transactions SET {', '.join(assignments)} "
                f"WHERE id IN ({placeholders})",
                (*params, *chunk),
            )
        self.conn.commit()

    def update_transaction_flags(
        self,
        transaction_ids: list[int],
        *,
        cleared: bool | None = None,
        reconciled: bool | None = None,
        remind: bool | None = None,
        flagged: bool | None = None,
        voided: bool | None = None,
    ) -> None:
        if not transaction_ids:
            return
        assignments: list[str] = []
        params: list = []
        if reconciled is not None:
            assignments.append("reconciled=?")
            params.append(1 if reconciled else 0)
            if reconciled:
                assignments.append("cleared=1")
        if cleared is not None:
            assignments.append("cleared=?")
            params.append(1 if cleared else 0)
            if not cleared:
                assignments.append("reconciled=0")
        if remind is not None:
            assignments.append("remind=?")
            params.append(1 if remind else 0)
        if flagged is not None:
            assignments.append("flagged=?")
            params.append(1 if flagged else 0)
        if voided is not None:
            assignments.append("voided=?")
            params.append(1 if voided else 0)
        if not assignments:
            return
        sql = f"UPDATE transactions SET {', '.join(assignments)} WHERE id=?"
        for transaction_id in transaction_ids:
            self.conn.execute(sql, (*params, transaction_id))
        self.conn.commit()

    def delete_transaction(self, transaction_id: int) -> None:
        row = self.conn.execute(
            "SELECT transfer_id FROM transactions WHERE id=?", (transaction_id,)
        ).fetchone()
        if row is not None and row["transfer_id"]:
            self.conn.execute(
                "DELETE FROM transactions WHERE transfer_id=?", (row["transfer_id"],)
            )
        else:
            self.conn.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
        self.conn.commit()

    def _transaction_query(self, where: str = "", params: tuple = ()) -> list[sqlite3.Row]:
        return self._rows(
            f"""
            SELECT t.*, a.name AS account_name,
                   CASE WHEN p.name IS NOT NULL AND p.name <> ''
                        THEN p.name || ' : ' || c.name ELSE c.name END
                       AS category_name,
                   c.color AS category_color, c.kind AS category_kind
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN categories p ON p.id = c.parent_id
            {where}
            ORDER BY t.date, t.id
            """,
            params,
        )

    @staticmethod
    def _to_transaction_row(r: sqlite3.Row, balance: float = 0.0) -> TransactionRow:
        return TransactionRow(
            id=r["id"],
            account_id=r["account_id"],
            account_name=r["account_name"],
            date=r["date"],
            payee=r["payee"],
            category_id=r["category_id"],
            category_name=r["category_name"] or "Uncategorized",
            category_color=theme_category_color(r["category_name"], r["category_color"]),
            category_kind=r["category_kind"] or "expense",
            amount=float(r["amount"]),
            memo=r["memo"],
            cleared=bool(r["cleared"]),
            reconciled=bool(r["reconciled"]),
            remind=bool(r["remind"]),
            flagged=bool(r["flagged"]),
            voided=bool(r["voided"]),
            payment=r["payment"] or "",
            number=r["number"] or "",
            tags=r["tags"] or "",
            transfer_id=r["transfer_id"],
            balance=balance,
        )

    def ledger_rows(self, account_id: int) -> list[TransactionRow]:
        """All transactions for one account, with a running balance."""
        account = self.account(account_id)
        if account is None:
            return []
        running = account.opening
        rows: list[TransactionRow] = []
        for raw in self._transaction_query("WHERE t.account_id = ?", (account_id,)):
            if not raw["voided"]:
                running += float(raw["amount"])
            rows.append(self._to_transaction_row(raw, running))
        return rows

    def category_transactions(
        self,
        category_id: int,
        include_subcategories: bool = True,
    ) -> list[TransactionRow]:
        """Transactions filed under a category, newest first.

        For a top-level category ``include_subcategories`` also returns its
        children's transactions; a subcategory only ever returns its own rows.
        """
        category = self.category(category_id)
        if category is None:
            return []
        ids = [category_id]
        if include_subcategories and category.parent_id is None:
            ids.extend(
                child.id
                for child in self.categories()
                if child.parent_id == category_id
            )
        placeholders = ",".join("?" for _ in ids)
        rows = self._transaction_query(
            f"WHERE t.category_id IN ({placeholders})", tuple(ids)
        )
        transactions = [self._to_transaction_row(row) for row in rows]
        transactions.sort(key=lambda row: (row.date, row.id), reverse=True)
        return transactions

    def transaction(self, transaction_id: int) -> TransactionRow | None:
        rows = self._transaction_query("WHERE t.id = ?", (transaction_id,))
        return self._to_transaction_row(rows[0]) if rows else None

    def strip_transactions(self) -> tuple[list[TransactionRow], list[TransactionRow]]:
        """Future-dated and remind-flagged posted transactions for the home strip."""
        today = date.today().isoformat()
        future = [
            self._to_transaction_row(r)
            for r in self._transaction_query("WHERE t.date > ? AND t.voided = 0", (today,))
        ]
        remind = [
            self._to_transaction_row(r)
            for r in self._transaction_query("WHERE t.remind = 1 AND t.voided = 0", ())
        ]
        return future, remind

    def payments(self) -> list[str]:
        rows = self._rows(
            "SELECT DISTINCT payment FROM transactions WHERE payment <> '' ORDER BY 1"
        )
        return [r[0] for r in rows]

    def tags(self) -> list[str]:
        rows = self._rows("SELECT tags FROM transactions WHERE tags <> ''")
        values: set[str] = set()
        for row in rows:
            values.update(part for part in row[0].split() if part)
        return sorted(values)

    def payees(self) -> list[str]:
        rows = self._rows(
            "SELECT payee FROM transactions WHERE payee <> '' "
            "UNION SELECT payee FROM scheduled WHERE payee <> '' ORDER BY 1"
        )
        return [r[0] for r in rows]

    # ----------------------------------------------------------------- rules
    @staticmethod
    def _rule_from_row(row: sqlite3.Row) -> Rule:
        return Rule(
            id=int(row["id"]),
            name=row["name"],
            enabled=bool(row["enabled"]),
            sort_order=int(row["sort_order"]),
            search=row["search"],
            match_memo=bool(row["match_memo"]),
            match_payee=bool(row["match_payee"]),
            case_sensitive=bool(row["case_sensitive"]),
            regex=bool(row["regex"]),
            amount_enabled=bool(row["amount_enabled"]),
            amount_and=bool(row["amount_and"]),
            amount_op=row["amount_op"],
            amount=float(row["amount"]),
            assign_payee=row["assign_payee"],
            payee_overwrite=bool(row["payee_overwrite"]),
            category_id=row["category_id"],
            category_overwrite=bool(row["category_overwrite"]),
            assign_payment=row["assign_payment"],
            payment_overwrite=bool(row["payment_overwrite"]),
            assign_tags=row["assign_tags"],
            tags_overwrite=bool(row["tags_overwrite"]),
            assign_memo=row["assign_memo"],
            memo_overwrite=bool(row["memo_overwrite"]),
        )

    def rules(self) -> list[Rule]:
        """All assignment rules in the order they are applied."""
        rows = self._rows("SELECT * FROM rules ORDER BY sort_order, id")
        return [self._rule_from_row(row) for row in rows]

    def rule(self, rule_id: int) -> Rule | None:
        row = self.conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        return self._rule_from_row(row) if row is not None else None

    def add_rule(self, rule: Rule) -> int:
        rule.validate()
        order = rule.sort_order
        if not order:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM rules"
            ).fetchone()
            order = int(row[0])
        cur = self.conn.execute(
            "INSERT INTO rules(name, enabled, sort_order, search, match_memo, "
            "match_payee, case_sensitive, regex, amount_enabled, amount_and, "
            "amount_op, amount, assign_payee, payee_overwrite, category_id, "
            "category_overwrite, assign_payment, payment_overwrite, assign_tags, "
            "tags_overwrite, assign_memo, memo_overwrite) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rule.name,
                1 if rule.enabled else 0,
                order,
                rule.search,
                1 if rule.match_memo else 0,
                1 if rule.match_payee else 0,
                1 if rule.case_sensitive else 0,
                1 if rule.regex else 0,
                1 if rule.amount_enabled else 0,
                1 if rule.amount_and else 0,
                rule.amount_op,
                float(rule.amount),
                rule.assign_payee,
                1 if rule.payee_overwrite else 0,
                rule.category_id,
                1 if rule.category_overwrite else 0,
                rule.assign_payment,
                1 if rule.payment_overwrite else 0,
                rule.assign_tags,
                1 if rule.tags_overwrite else 0,
                rule.assign_memo,
                1 if rule.memo_overwrite else 0,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_rule(self, rule: Rule) -> None:
        rule.validate()
        self.conn.execute(
            "UPDATE rules SET name=?, enabled=?, search=?, match_memo=?, "
            "match_payee=?, case_sensitive=?, regex=?, amount_enabled=?, "
            "amount_and=?, amount_op=?, amount=?, assign_payee=?, "
            "payee_overwrite=?, category_id=?, category_overwrite=?, "
            "assign_payment=?, payment_overwrite=?, assign_tags=?, "
            "tags_overwrite=?, assign_memo=?, memo_overwrite=? WHERE id=?",
            (
                rule.name,
                1 if rule.enabled else 0,
                rule.search,
                1 if rule.match_memo else 0,
                1 if rule.match_payee else 0,
                1 if rule.case_sensitive else 0,
                1 if rule.regex else 0,
                1 if rule.amount_enabled else 0,
                1 if rule.amount_and else 0,
                rule.amount_op,
                float(rule.amount),
                rule.assign_payee,
                1 if rule.payee_overwrite else 0,
                rule.category_id,
                1 if rule.category_overwrite else 0,
                rule.assign_payment,
                1 if rule.payment_overwrite else 0,
                rule.assign_tags,
                1 if rule.tags_overwrite else 0,
                rule.assign_memo,
                1 if rule.memo_overwrite else 0,
                rule.id,
            ),
        )
        self.conn.commit()

    def delete_rule(self, rule_id: int) -> None:
        self.conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        self.conn.commit()

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        self.conn.execute(
            "UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id)
        )
        self.conn.commit()

    def _apply_rule(self, rule: Rule, draft: TransactionDraft) -> None:
        """Apply one matching rule's assignments, honouring overwrite flags."""
        if rule.assign_payee and (rule.payee_overwrite or not draft.payee.strip()):
            draft.payee = rule.assign_payee
        if rule.category_id is not None and self.category(rule.category_id) is not None:
            if rule.category_overwrite or draft.category_id is None:
                draft.category_id = rule.category_id
        if rule.assign_payment and (
            rule.payment_overwrite or not draft.payment.strip()
        ):
            draft.payment = rule.assign_payment
        if rule.assign_tags and (rule.tags_overwrite or not draft.tags.strip()):
            draft.tags = rule.assign_tags
        if rule.assign_memo and (rule.memo_overwrite or not draft.memo.strip()):
            draft.memo = rule.assign_memo

    def apply_rules(self, draft: TransactionDraft) -> TransactionDraft:
        """Run every enabled rule against a new transaction and assign fields.

        Rules run in sort order, so a later overwrite rule wins. The draft is
        changed in place and returned for convenience.
        """
        for rule in self.rules():
            if not rule.enabled:
                continue
            if rule.matches(draft.payee, draft.memo, draft.amount):
                self._apply_rule(rule, draft)
        return draft

    # ------------------------------------------------------------------ meta
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ------------------------------------------------------------------- csv
    def export_csv(self, path: str | Path) -> int:
        rows = self._rows(
            """
            SELECT t.date, a.name AS account, t.payee,
                   CASE WHEN p.name IS NOT NULL AND p.name <> ''
                        THEN p.name || ' : ' || c.name ELSE c.name END
                       AS category,
                   t.memo, t.amount, t.cleared, t.reconciled, t.remind, t.flagged,
                   t.voided, t.payment, t.number, t.tags
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN categories p ON p.id = c.parent_id
            ORDER BY t.date, t.id
            """
        )
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["date", "account", "payee", "category", "memo", "amount",
                 "cleared", "reconciled", "remind", "flagged", "voided",
                 "payment", "number", "tags"]
            )
            for r in rows:
                writer.writerow(
                    [
                        r["date"],
                        r["account"],
                        r["payee"],
                        r["category"] or "",
                        r["memo"],
                        f"{r['amount']:.2f}",
                        "yes" if r["cleared"] else "no",
                        "yes" if r["reconciled"] else "no",
                        "yes" if r["remind"] else "no",
                        "yes" if r["flagged"] else "no",
                        "yes" if r["voided"] else "no",
                        r["payment"] or "",
                        r["number"] or "",
                        r["tags"] or "",
                    ]
                )
        return len(rows)

    def import_profile(self, headers: list[str]) -> dict[str, str] | None:
        """Return a saved field→header mapping for this header set."""
        row = self.conn.execute(
            "SELECT mapping FROM import_profiles WHERE signature=?",
            (header_signature(headers),),
        ).fetchone()
        if row is None:
            return None
        try:
            saved = json.loads(row["mapping"])
        except (TypeError, ValueError):
            return None
        actual = {normalize(header): header for header in headers}
        mapped: dict[str, str] = {}
        for field, normalized_header in saved.items():
            if normalized_header in actual:
                mapped[field] = actual[normalized_header]
        return mapped or None

    def remember_import_profile(self, headers: list[str], mapping: dict[str, str]) -> None:
        """Persist a mapping keyed by the file's normalized header set."""
        normalized = {
            field: normalize(header)
            for field, header in mapping.items()
            if header
        }
        self.conn.execute(
            "INSERT INTO import_profiles(signature, headers, mapping, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(signature) DO UPDATE SET "
            "headers=excluded.headers, mapping=excluded.mapping, "
            "updated_at=excluded.updated_at",
            (
                header_signature(headers),
                json.dumps(headers),
                json.dumps(normalized),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def forget_import_profile(self, headers: list[str]) -> None:
        self.conn.execute(
            "DELETE FROM import_profiles WHERE signature=?",
            (header_signature(headers),),
        )
        self.conn.commit()

    def import_fingerprints(self, account_ids: list[int] | None = None) -> set[ImportFingerprint]:
        """Fingerprints for duplicate detection during CSV import."""
        sql = "SELECT account_id, date, memo, payee, amount FROM transactions WHERE voided = 0"
        params: tuple = ()
        if account_ids is not None:
            ids = list(dict.fromkeys(int(account_id) for account_id in account_ids))
            if not ids:
                return set()
            sql += f" AND account_id IN ({','.join('?' * len(ids))})"
            params = tuple(ids)
        return {
            import_fingerprint(
                int(row["account_id"]),
                str(row["date"]),
                float(row["amount"]),
                str(row["memo"] or ""),
                str(row["payee"] or ""),
            )
            for row in self.conn.execute(sql, params)
        }

    def import_csv(
        self,
        path: str | Path,
        account_id: int | None = None,
        memo_as_payee: bool = False,
        mapping: dict[str, str] | None = None,
        skip_rows: set[int] | None = None,
        apply_rules: bool = True,
    ) -> tuple[int, int, int]:
        """Import a CSV, auto-detecting English/Spanish bank header names.

        Files with an account column use the account names in the file. Files
        without one (such as HomeBank bank exports) use ``account_id`` as the
        target account. ``skip_rows`` lets the import dialog leave out rows it
        already marked as duplicates; set ``apply_rules`` to false to import the
        raw rows without running the automatic assignment rules. Returns
        added, unreadable, duplicates.
        """
        plan = read_csv_plan(path)
        if mapping is not None:
            plan.mapping = mapping
        if plan.missing_required:
            missing = ", ".join(plan.missing_required)
            raise ValueError(
                f"Could not find the required {missing} column(s) in the CSV. "
                "Supported names include Date/Fecha and Amount/Importe."
            )
        added = 0
        skipped = 0
        duplicates = 0
        for index, row in enumerate(plan.rows):
            if skip_rows is not None and index in skip_rows:
                duplicates += 1
                continue
            try:
                parsed = parse_date(plan.value(row, "date"))
                if parsed is None:
                    raise ValueError("date")
                amount = parse_amount(plan.value(row, "amount"))
                if amount is None or abs(amount) < 1e-9:
                    raise ValueError("amount")
                file_account = plan.value(row, "account")
                if file_account:
                    row_account_id = self._ensure_account(file_account)
                elif account_id is not None:
                    row_account_id = account_id
                else:
                    row_account_id = self._ensure_account("Imported")
                payee = plan.value(row, "payee")
                memo = plan.value(row, "memo")
                if memo_as_payee and not payee and memo:
                    payee = memo
                category_name = plan.value(row, "category")
                category_id = None
                if category_name:
                    try:
                        category_id = self.ensure_category(
                            category_name, "income" if amount > 0 else "expense"
                        )
                    except ValueError:
                        # Unreadable category text should not abort the import;
                        # keep the row and leave it uncategorized.
                        category_id = None
                cleared, reconciled, remind, flagged, voided = statuses_from_row(plan, row)
                draft = TransactionDraft(
                    date=parsed.isoformat(),
                    account_id=row_account_id,
                    payee=payee,
                    category_id=category_id,
                    amount=amount,
                    memo=memo,
                    cleared=cleared,
                    reconciled=reconciled,
                    remind=remind,
                    flagged=flagged,
                    voided=voided,
                    payment=plan.value(row, "payment"),
                    number=plan.value(row, "number"),
                    tags=plan.value(row, "tags"),
                )
                if apply_rules:
                    draft = self.apply_rules(draft)
                self.conn.execute(
                    "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
                    "cleared, reconciled, remind, flagged, voided, payment, number, tags) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        draft.account_id,
                        draft.date,
                        draft.payee.strip(),
                        draft.category_id,
                        float(draft.amount),
                        draft.memo.strip(),
                        1 if draft.reconciled or draft.cleared else 0,
                        1 if draft.reconciled else 0,
                        1 if draft.remind else 0,
                        1 if draft.flagged else 0,
                        1 if draft.voided else 0,
                        draft.payment.strip(),
                        draft.number.strip(),
                        draft.tags.strip(),
                    ),
                )
                added += 1
            except Exception:
                skipped += 1
        self.conn.commit()
        return added, skipped, duplicates

    def _ensure_account(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM accounts WHERE name=?", (name.strip(),)).fetchone()
        if row:
            return int(row[0])
        return self.add_account(name.strip() or "Imported", "Bank", 0.0)

    def ensure_category(self, name: str, kind: str = "expense") -> int:
        """Find or create a category from typed text.

        A plain name creates a top-level category; ``parent:child`` (with or
        without spaces around the colon) creates the parent when needed and
        returns the child. Matching is case-insensitive, so typing an existing
        name reuses that category instead of creating a duplicate.
        """
        label = name.strip()
        if not label:
            raise ValueError("Category names cannot be empty")

        parent_name, child_name = "", label
        if ":" in label:
            head, _, tail = label.partition(":")
            head, tail = head.strip(), tail.strip()
            if head and tail:
                parent_name, child_name = head, tail
            elif head:
                # A trailing colon is harmless while typing: keep the name.
                child_name = head
            elif tail:
                child_name = tail
            else:
                raise ValueError("Category names cannot be empty")

        parent_id = None
        if parent_name:
            parent_id = self.ensure_category(parent_name, kind)

        folded = child_name.casefold()
        for category in self.categories():
            if category.parent_id == parent_id and category.name.casefold() == folded:
                return category.id

        parent = self.category(parent_id)
        if parent is not None:
            kind = parent.kind
        color = (
            parent.color
            if parent is not None
            else theme_category_color(child_name, "#8a8a8a")
        )
        cur = self.conn.execute(
            "INSERT INTO categories(name, kind, color, sort_order, parent_id) "
            "VALUES (?,?,?,?,?)",
            (
                child_name,
                kind,
                color,
                parent.sort_order
                if parent is not None
                else self._next_category_order(),
                parent_id,
            ),
        )
        return int(cur.lastrowid)

    # ----------------------------------------------------------------- reset
    def reset_demo_data(self) -> None:
        self.conn.execute("DELETE FROM transactions")
        self.conn.execute("DELETE FROM scheduled")
        self.conn.execute("DELETE FROM accounts")
        self.conn.execute("DELETE FROM categories")
        self.conn.execute("DELETE FROM sqlite_sequence WHERE name IN "
                          "('transactions','scheduled','accounts','categories')")
        self.conn.commit()
        from .seed import seed_if_empty

        seed_if_empty(self.conn, force=True)
        self.conn.commit()

    def summary_line(self) -> str:
        accounts = len(self.accounts())
        tx = self.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        return f"{accounts} accounts · {tx} transactions"

