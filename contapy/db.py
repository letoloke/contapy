"""SQLite persistence for accounts, transactions and schedules.

Everything the dashboard shows is derived from the ledger: account balances,
the category donut and the monthly income/expense bars.  No figures are stored
as display-only snapshots.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime
from datetime import date
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
    Category,
    MonthFlow,
    ScheduledItem,
    Slice,
    TransactionDraft,
    TransactionRow,
)
from .omarchy import theme_category_color

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
    sort_order  INTEGER NOT NULL DEFAULT 0
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


def daily_backup_dir(db_path: str | Path) -> Path:
    """Folder for the automatic daily copies, beside the active database."""
    return Path(db_path).expanduser().parent / BACKUP_DIR_NAME


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
                   COALESCE(SUM(CASE WHEN t.reconciled = 1 AND t.date <= ? THEN t.amount END), 0) AS reconciled_sum,
                   COALESCE(SUM(CASE WHEN (t.cleared = 1 OR t.reconciled = 1) AND t.date <= ? THEN t.amount END), 0) AS cleared_sum,
                   COALESCE(SUM(CASE WHEN t.date <= ? THEN t.amount END), 0) AS today_sum
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
                "FROM transactions WHERE date > ? GROUP BY account_id",
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
        rows = self._rows("SELECT * FROM categories ORDER BY kind DESC, sort_order, id")
        return [
            Category(
                id=r["id"],
                name=r["name"],
                kind=r["kind"],
                color=r["color"],
                sort_order=r["sort_order"],
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

    # ---------------------------------------------------------------- charts
    def spend_by_category(
        self,
        start: date,
        end: date,
        account_id: int | None = None,
    ) -> tuple[list[Slice], float]:
        params: list = [start.isoformat(), end.isoformat()]
        account_sql = ""
        if account_id is not None:
            account_sql = " AND t.account_id = ?"
            params.append(account_id)
        rows = self._rows(
            f"""
            SELECT c.id, c.name, c.color, SUM(-t.amount) AS spent
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.date BETWEEN ? AND ?
              AND t.amount < 0
              AND c.kind = 'expense'
              {account_sql}
            GROUP BY c.id
            HAVING spent > 0
            ORDER BY spent DESC
            """,
            tuple(params),
        )
        items = [(r["name"], float(r["spent"]), r["color"]) for r in rows]
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
            WHERE date >= ? AND category_id IS NOT NULL
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
                   c.name AS category_name, c.color AS category_color, c.kind AS category_kind
            FROM scheduled s
            JOIN accounts a ON a.id = s.account_id
            LEFT JOIN categories c ON c.id = s.category_id
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
        cleared = draft.reconciled or draft.cleared
        cur = self.conn.execute(
            "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
            "cleared, reconciled, remind, flagged, payment, number, tags, transfer_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                "cleared, reconciled, remind, flagged, payment, number, tags, transfer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            "memo=?, cleared=?, reconciled=?, remind=?, flagged=?, payment=?, number=?, tags=? "
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
                draft.payment.strip(),
                draft.number.strip(),
                draft.tags.strip(),
                transaction_id,
            ),
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
                   c.name AS category_name, c.color AS category_color, c.kind AS category_kind
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
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
            running += float(raw["amount"])
            rows.append(self._to_transaction_row(raw, running))
        return rows

    def transaction(self, transaction_id: int) -> TransactionRow | None:
        rows = self._transaction_query("WHERE t.id = ?", (transaction_id,))
        return self._to_transaction_row(rows[0]) if rows else None

    def strip_transactions(self) -> tuple[list[TransactionRow], list[TransactionRow]]:
        """Future-dated and remind-flagged posted transactions for the home strip."""
        today = date.today().isoformat()
        future = [
            self._to_transaction_row(r)
            for r in self._transaction_query("WHERE t.date > ?", (today,))
        ]
        remind = [
            self._to_transaction_row(r)
            for r in self._transaction_query("WHERE t.remind = 1", ())
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
            SELECT t.date, a.name AS account, t.payee, c.name AS category,
                   t.memo, t.amount, t.cleared, t.reconciled, t.remind, t.flagged,
                   t.payment, t.number, t.tags
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            LEFT JOIN categories c ON c.id = t.category_id
            ORDER BY t.date, t.id
            """
        )
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["date", "account", "payee", "category", "memo", "amount",
                 "cleared", "reconciled", "remind", "flagged",
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

    def import_csv(
        self,
        path: str | Path,
        account_id: int | None = None,
        memo_as_payee: bool = False,
        mapping: dict[str, str] | None = None,
    ) -> tuple[int, int]:
        """Import a CSV, auto-detecting English/Spanish bank header names.

        Files with an account column use the account names in the file. Files
        without one (such as HomeBank bank exports) use ``account_id`` as the
        target account.
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
        for row in plan.rows:
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
                    category_id = self._ensure_category(
                        category_name, "income" if amount > 0 else "expense"
                    )
                cleared, reconciled, remind, flagged = statuses_from_row(plan, row)
                self.conn.execute(
                    "INSERT INTO transactions(account_id, date, payee, category_id, amount, memo, "
                    "cleared, reconciled, remind, flagged, payment, number, tags) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row_account_id,
                        parsed.isoformat(),
                        payee,
                        category_id,
                        amount,
                        memo,
                        1 if cleared else 0,
                        1 if reconciled else 0,
                        1 if remind else 0,
                        1 if flagged else 0,
                        plan.value(row, "payment"),
                        plan.value(row, "number"),
                        plan.value(row, "tags"),
                    ),
                )
                added += 1
            except Exception:
                skipped += 1
        self.conn.commit()
        return added, skipped

    def _ensure_account(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM accounts WHERE name=?", (name.strip(),)).fetchone()
        if row:
            return int(row[0])
        return self.add_account(name.strip() or "Imported", "Bank", 0.0)

    def _ensure_category(self, name: str, kind: str) -> int:
        row = self.conn.execute("SELECT id FROM categories WHERE name=?", (name.strip(),)).fetchone()
        if row:
            return int(row[0])
        color = theme_category_color(name, "#8a8a8a")
        cur = self.conn.execute(
            "INSERT INTO categories(name, kind, color, sort_order) VALUES (?,?,?, "
            "(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories))",
            (name.strip(), kind, color),
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

