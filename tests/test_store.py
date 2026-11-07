"""Headless tests for the ledger, demo seed and CSV round-trip."""

from __future__ import annotations

import calendar
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from contapy.csv_io import parse_amount, read_csv_plan
from contapy.db import DataStore, daily_backup_dir, default_db_path, import_fingerprint
from contapy.models import TransactionDraft


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "contapy.db"
        self.store = DataStore(self.path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def account(self, name: str):
        return next(a for a in self.store.accounts() if a.name == name)

    def test_demo_balances_match_reference(self) -> None:
        balances = self.store.balances()
        today = sum(b.today for b in balances.values())
        future = sum(b.future for b in balances.values())
        reconciled = sum(b.reconciled for b in balances.values())
        self.assertAlmostEqual(today, -97_263.62, places=2)
        self.assertAlmostEqual(future, -97_263.62, places=2)
        self.assertAlmostEqual(reconciled, 20_289.30, places=2)
        self.assertAlmostEqual(balances[self.account("Banamex").id].today, 126_658.10, places=2)
        self.assertAlmostEqual(balances[self.account("inversion").id].today, -250_987.41, places=2)

    def test_last_thirty_days_donut(self) -> None:
        today = date.today()
        slices, total = self.store.spend_by_category(today - timedelta(days=29), today)
        self.assertAlmostEqual(total, 167_248.99, places=2)
        self.assertEqual(len(slices), 11)
        self.assertEqual(slices[0].name, "renta")
        self.assertAlmostEqual(slices[0].amount, 64_056.36, places=2)
        self.assertEqual(slices[-1].name, "Other")

    def test_schedules_are_not_in_balances_until_posted(self) -> None:
        account = self.account("eCash")
        before = self.store.balances()[account.id]
        self.assertAlmostEqual(before.today, 54_098.54, places=2)
        self.assertAlmostEqual(before.future, 54_098.54, places=2)

        renta = next(i for i in self.store.scheduled_items() if i.payee == "Santiago pancho")
        self.store.post_scheduled(renta.id)
        after = self.store.balances()[account.id]
        self.assertAlmostEqual(after.today, 54_098.54, places=2)
        self.assertAlmostEqual(after.future, -10_901.46, places=2)
        self.assertFalse(any(i.id == renta.id for i in self.store.scheduled_items()))

    def test_add_transaction_moves_balance(self) -> None:
        account = self.account("eCash")
        before = self.store.balances()[account.id].today
        self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account.id,
                payee="Coffee",
                category_id=None,
                amount=-125.50,
            )
        )
        after = self.store.balances()[account.id].today
        self.assertAlmostEqual(after - before, -125.50, places=2)

    def test_cashflow_window_labels(self) -> None:
        flows = self.store.monthly_cashflow(12)
        self.assertEqual(len(flows), 12)
        today = date.today()
        year, month = today.year, today.month - 11
        while month <= 0:
            month += 12
            year -= 1
        self.assertEqual((flows[0].year, flows[0].month), (year, month))
        self.assertEqual(flows[-1].month, today.month)
        self.assertEqual(flows[-1].label, calendar.month_abbr[today.month])

    def test_remind_flag_and_strip_filters(self) -> None:
        account = self.account("Banamex")
        tx_id = self.store.add_transaction(
            TransactionDraft(
                date=(date.today() + timedelta(days=5)).isoformat(),
                account_id=account.id,
                payee="Insurance",
                category_id=None,
                amount=-99,
                remind=True,
                flagged=True,
            )
        )
        row = self.store.transaction(tx_id)
        self.assertIsNotNone(row)
        self.assertTrue(row.remind)
        self.assertTrue(row.flagged)
        future, remind = self.store.strip_transactions()
        self.assertIn(tx_id, [r.id for r in future])
        self.assertIn(tx_id, [r.id for r in remind])

    def test_ledger_running_balance_and_status(self) -> None:
        account = self.account("Banamex")
        rows = self.store.ledger_rows(account.id)
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0].date, min(r.date for r in rows))
        self.assertAlmostEqual(rows[-1].balance, self.store.balances()[account.id].today, places=2)

        test_account = self.store.add_account("Ledger test", "Cash", 1000.0)
        tx_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=test_account,
                payee="Ledger purchase",
                category_id=None,
                amount=-100,
            )
        )
        balances = self.store.balances()[test_account]
        self.assertAlmostEqual(balances.reconciled, 1000.0, places=2)
        self.assertAlmostEqual(balances.cleared, 900.0, places=2)
        self.assertAlmostEqual(balances.today, 900.0, places=2)

        self.store.update_transaction_flags([tx_id], cleared=True, reconciled=True)
        balances = self.store.balances()[test_account]
        self.assertAlmostEqual(balances.reconciled, 900.0, places=2)
        self.assertAlmostEqual(balances.cleared, 900.0, places=2)

        self.store.update_transaction_flags([tx_id], cleared=True, reconciled=False)
        balances = self.store.balances()[test_account]
        self.assertAlmostEqual(balances.reconciled, 1000.0, places=2)
        self.assertAlmostEqual(balances.cleared, 900.0, places=2)

    def test_account_warning_tracks_unreconciled_transactions(self) -> None:
        account_id = self.store.add_account("Test account", "Bank")

        def account():
            return next(a for a in self.store.accounts() if a.id == account_id)

        self.assertFalse(account().warning)
        self.assertEqual(account().unreconciled, 0)

        # Future-dated entries have not happened yet, so they do not warn.
        self.store.add_transaction(
            TransactionDraft(
                date=(date.today() + timedelta(days=5)).isoformat(),
                account_id=account_id,
                payee="Future",
                category_id=None,
                amount=-10,
            )
        )
        self.assertFalse(account().warning)

        tx_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account_id,
                payee="Needs review",
                category_id=None,
                amount=-25,
            )
        )
        self.assertTrue(account().warning)
        self.assertEqual(account().unreconciled, 1)

        self.store.update_transaction_flags([tx_id], cleared=True, reconciled=True)
        self.assertFalse(account().warning)
        self.assertEqual(account().unreconciled, 0)

    def test_csv_round_trip(self) -> None:
        csv_path = Path(self.tmp.name) / "export.csv"
        exported = self.store.export_csv(csv_path)
        self.assertGreater(exported, 0)

        second_path = Path(self.tmp.name) / "imported.db"
        second = DataStore(second_path, seed=False)
        try:
            added, skipped, duplicates = second.import_csv(csv_path)
            self.assertEqual(added, exported)
            self.assertEqual(skipped, 0)
            self.assertEqual(duplicates, 0)
            self.assertEqual(len(second.accounts()), 7)
        finally:
            second.close()

    def test_old_schema_migrates_status_columns(self) -> None:
        path = Path(self.tmp.name) / "old.db"
        legacy = sqlite3.connect(path)
        legacy.executescript(
            """
            CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                kind TEXT NOT NULL, opening REAL NOT NULL DEFAULT 0,
                warning INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0,
                last_reconciled TEXT);
            CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'expense', color TEXT NOT NULL DEFAULT '#888888',
                sort_order INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL, date TEXT NOT NULL, payee TEXT NOT NULL DEFAULT '',
                category_id INTEGER, amount REAL NOT NULL, memo TEXT NOT NULL DEFAULT '',
                cleared INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE scheduled (id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL, next_date TEXT NOT NULL,
                payee TEXT NOT NULL DEFAULT '', category_id INTEGER,
                amount REAL NOT NULL, memo TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'scheduled');
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO accounts(name, kind, opening, sort_order) VALUES ('Old', 'Bank', 100, 0);
            INSERT INTO transactions(account_id, date, payee, amount, cleared)
                VALUES (1, '2026-11-01', 'Legacy', -25, 1);
            """
        )
        legacy.commit()
        legacy.close()

        migrated = DataStore(path, seed=False)
        try:
            columns = {r[1] for r in migrated.conn.execute("PRAGMA table_info(transactions)")}
            self.assertTrue(
                {"reconciled", "remind", "flagged", "payment", "number", "tags", "transfer_id"}
                <= columns
            )
            balance = migrated.balances()[1]
            self.assertAlmostEqual(balance.reconciled, 75.0, places=2)
            self.assertAlmostEqual(balance.cleared, 75.0, places=2)
            self.assertTrue(migrated.ledger_rows(1)[0].reconciled)
        finally:
            migrated.close()

    def test_import_homebank_spanish_csv(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "readyparahomebank.csv"
        plan = read_csv_plan(fixture)
        self.assertEqual(plan.row_count, 70)
        self.assertEqual(plan.mapping["date"], "Fecha")
        self.assertEqual(plan.mapping["amount"], "Importe")
        self.assertEqual(plan.mapping["payee"], "Beneficiario")
        self.assertEqual(plan.mapping["memo"], "Memo")
        self.assertFalse(plan.missing_required)

        target = self.store.add_account("Imported bank", "Bank", 0)
        added, skipped, duplicates = self.store.import_csv(
            fixture, account_id=target, memo_as_payee=True
        )
        self.assertEqual((added, skipped, duplicates), (70, 0, 0))
        rows = self.store.ledger_rows(target)
        self.assertEqual(len(rows), 70)
        self.assertAlmostEqual(sum(row.amount for row in rows), 35_038.47, places=2)
        first = next(row for row in rows if row.date == "2026-11-05")
        self.assertAlmostEqual(first.amount, 949.0, places=2)
        self.assertEqual(first.memo, "DEPOSITO INTERBANCARIO AUT 0907289")
        self.assertEqual(first.payee, first.memo)
        self.assertIsNone(first.category_id)
        self.assertTrue(first.cleared)
        self.assertFalse(any(account.name == "Imported" for account in self.store.accounts()))
        self.assertEqual(parse_amount("1.234,56"), 1234.56)

    def test_import_header_profiles_are_remembered(self) -> None:
        headers = [
            "Fecha", "Pago", "Número", "Beneficiario",
            "Memo", "Importe", "Categoría", "Etiquetas",
        ]
        mapping = {
            "date": "Fecha",
            "amount": "Importe",
            "payee": "Beneficiario",
            "memo": "Memo",
            "payment": "Pago",
            "number": "Número",
            "category": "Categoría",
            "tags": "Etiquetas",
        }
        self.store.remember_import_profile(headers, mapping)
        self.assertEqual(self.store.import_profile(headers), mapping)
        # Header order does not matter.
        self.assertEqual(self.store.import_profile(list(reversed(headers))), mapping)
        # Case/accent variants still match the same column signature.
        variant = [header.upper() for header in headers]
        loaded = self.store.import_profile(variant)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["date"], "FECHA")
        self.assertEqual(loaded["amount"], "IMPORTE")
        self.store.forget_import_profile(headers)
        self.assertIsNone(self.store.import_profile(headers))

    def test_import_uses_custom_header_mapping(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "readyparahomebank.csv"
        target = self.store.add_account("Custom map bank", "Bank", 0)
        custom = {
            "date": "Fecha",
            "amount": "Importe",
            "payee": "Memo",
            "memo": "Memo",
        }
        added, skipped, duplicates = self.store.import_csv(
            fixture, account_id=target, mapping=custom
        )
        self.assertEqual((added, skipped, duplicates), (70, 0, 0))
        rows = self.store.ledger_rows(target)
        self.assertEqual(len(rows), 70)
        self.assertTrue(all(row.payee == row.memo for row in rows))
        self.assertTrue(all(row.category_id is None for row in rows))

    def test_import_duplicate_detection_prefers_memo(self) -> None:
        target = self.store.add_account("Duplicate bank", "Bank", 0)
        csv_path = Path(self.tmp.name) / "duplicates.csv"
        csv_path.write_text(
            "date,amount,payee,memo\n"
            "2026-11-06,-85.50,Cafe,Morning coffee\n"
            "2026-11-06,-20.00,Taxi,Airport ride\n",
            encoding="utf-8",
        )
        added, skipped, duplicates = self.store.import_csv(csv_path, account_id=target)
        self.assertEqual((added, skipped, duplicates), (2, 0, 0))

        fingerprints = self.store.import_fingerprints([target])
        memo_key = import_fingerprint(
            target, "2026-11-06", -85.5, "  MORNING COFFEE ", "Different payee"
        )
        self.assertIn(memo_key, fingerprints)
        # Date and amount disambiguate recurring payments with the same memo.
        self.assertNotIn(
            import_fingerprint(target, "2026-12-06", -85.5, "Morning coffee", "Cafe"),
            fingerprints,
        )
        # A different memo with the same date and amount is not a duplicate.
        self.assertNotIn(
            import_fingerprint(target, "2026-11-06", -85.5, "Evening tea", "Cafe"),
            fingerprints,
        )

        # The dialog passes the rows it marked as duplicate, and they are skipped.
        added, skipped, duplicates = self.store.import_csv(
            csv_path, account_id=target, skip_rows={0, 1}
        )
        self.assertEqual((added, skipped, duplicates), (0, 0, 2))
        self.assertEqual(len(self.store.ledger_rows(target)), 2)

    def test_metadata_and_transfer_pair(self) -> None:
        account = self.account("Banamex")
        destination = self.account("eCash")
        tx_id = self.store.add_transaction(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account.id,
                payee="amazon",
                category_id=None,
                amount=-429,
                payment="Credit card",
                number="zapatos",
                tags="us shopping",
            )
        )
        row = self.store.transaction(tx_id)
        self.assertEqual(row.payment, "Credit card")
        self.assertEqual(row.number, "zapatos")
        self.assertEqual(row.tags, "us shopping")

        before = self.store.balances()
        group = self.store.add_transfer(
            TransactionDraft(
                date=date.today().isoformat(),
                account_id=account.id,
                payee="",
                category_id=None,
                amount=-1000,
                payment="Bank transfer",
                tags="move",
            ),
            destination.id,
        )
        legs = self.store.transfer_legs(group)
        self.assertEqual(len(legs), 2)
        self.assertEqual(sorted(leg.amount for leg in legs), [-1000.0, 1000.0])
        self.assertTrue(all(leg.transfer_id == group for leg in legs))
        self.assertTrue(all(leg.category_id is None for leg in legs))
        after = self.store.balances()
        self.assertAlmostEqual(
            after[account.id].today - before[account.id].today, -1000.0, places=2
        )
        self.assertAlmostEqual(
            after[destination.id].today - before[destination.id].today, 1000.0, places=2
        )

        self.store.delete_transaction(legs[0].id)
        self.assertEqual(self.store.transfer_legs(group), [])

    def test_reset_restores_demo(self) -> None:
        self.store.add_account("Temporary", "Cash", 10)
        self.store.reset_demo_data()
        self.assertEqual(len(self.store.accounts()), 7)
        grand = sum(b.today for b in self.store.balances().values())
        self.assertAlmostEqual(grand, -97_263.62, places=2)

    def test_backup_to_writes_independent_copy(self) -> None:
        target = Path(self.tmp.name) / "copies" / "snapshot.db"
        result = self.store.backup_to(target)
        self.assertEqual(result, target)
        self.assertTrue(target.is_file())

        copy = DataStore(target, seed=False)
        try:
            self.assertEqual(len(copy.accounts()), len(self.store.accounts()))
            copy.add_account("Only in copy", "Cash")
            self.assertFalse(
                any(a.name == "Only in copy" for a in self.store.accounts())
            )
            self.store.add_account("Only in original", "Cash")
            self.assertFalse(
                any(a.name == "Only in original" for a in copy.accounts())
            )
        finally:
            copy.close()

    def test_backup_to_same_path_is_a_noop(self) -> None:
        self.assertEqual(self.store.backup_to(self.path), self.path)
        self.assertEqual(len(self.store.accounts()), 7)

    def test_daily_backup_is_written_once_per_day(self) -> None:
        day = date(2026, 11, 6)
        self.assertEqual(daily_backup_dir(self.path), self.path.parent / "dailylbaka")

        first = self.store.ensure_daily_backup(day=day)
        expected = self.path.parent / "dailylbaka" / "contapy-2026-11-06.db"
        self.assertEqual(first, expected)
        self.assertTrue(first.is_file())

        self.store.add_account("Later edit", "Cash")
        self.assertIsNone(self.store.ensure_daily_backup(day=day))

        backup = DataStore(first, seed=False)
        try:
            self.assertFalse(any(a.name == "Later edit" for a in backup.accounts()))
        finally:
            backup.close()

        next_day = self.store.ensure_daily_backup(day=date(2026, 11, 7))
        self.assertEqual(next_day, self.path.parent / "dailylbaka" / "contapy-2026-11-07.db")
        later = DataStore(next_day, seed=False)
        try:
            self.assertTrue(any(a.name == "Later edit" for a in later.accounts()))
        finally:
            later.close()


    def test_report_rows_and_months_cover_the_ledger(self) -> None:
        start, end = self.store.date_span()
        self.assertEqual(start, date(2025, 12, 3))
        self.assertEqual(end, date(2026, 11, 6))

        expense_rows = self.store.report_rows(start, end, kind="expense")
        expense_labels = {row.label for row in expense_rows}
        self.assertIn("renta", expense_labels)
        self.assertIn("(no category)", expense_labels)
        self.assertNotIn("Ingresos", expense_labels)
        self.assertAlmostEqual(
            sum(-row.expense for row in expense_rows), 2_817_772.68, places=2
        )

        income_rows = self.store.report_rows(start, end, kind="income")
        income_labels = {row.label for row in income_rows}
        self.assertIn("Ingresos", income_labels)
        # Uncategorised transactions appear in both reports, as HomeBank does.
        self.assertIn("(no category)", income_labels)
        self.assertAlmostEqual(
            sum(row.income for row in income_rows), 2_161_970.77, places=2
        )

        sorted_rows = self.store.report_rows(
            start, end, kind="expense", sort_by_amount=True
        )
        magnitudes = [row.magnitude for row in sorted_rows]
        self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))

        months = self.store.report_months(start, end, kind="expense")
        self.assertEqual(len(months), 12)
        self.assertEqual((months[0].label, months[0].year), ("Dec", 2025))
        self.assertAlmostEqual(months[0].expense, 8_000.0, places=2)
        self.assertGreaterEqual(min(flow.expense for flow in months), 0.0)

        payees = self.store.report_rows(start, end, kind="expense", view_by="payee")
        accounts = self.store.report_rows(start, end, kind="expense", view_by="account")
        self.assertEqual(len(payees), 12)
        self.assertEqual(len(accounts), 7)
        self.assertTrue(all(not row.color for row in payees))
        self.assertTrue(all(not row.color for row in accounts))

        searched = self.store.report_rows(
            start, end, kind="expense", search="renta"
        )
        self.assertEqual([row.label for row in searched], ["renta"])

        banamex = self.account("Banamex")
        filtered = self.store.report_rows(
            start, end, kind="expense", account_id=banamex.id
        )
        self.assertEqual(len(filtered), 5)


class DatabasePathTests(unittest.TestCase):
    def test_legacy_budget_database_is_copied_to_contapy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = base / "budget" / "budget.db"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy-budget-db")

            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(base)}, clear=True):
                expected = base / "contapy" / "contapy.db"
                self.assertEqual(default_db_path(), expected)
                self.assertTrue(expected.exists())
                self.assertEqual(expected.read_bytes(), b"legacy-budget-db")
                # The old file is copied, never moved or deleted.
                self.assertTrue(legacy.exists())

    def test_existing_contapy_database_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "budget").mkdir(parents=True)
            (base / "budget" / "budget.db").write_bytes(b"legacy")
            current = base / "contapy" / "contapy.db"
            current.parent.mkdir(parents=True)
            current.write_bytes(b"current")

            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(base)}, clear=True):
                self.assertEqual(default_db_path(), current)
                self.assertEqual(current.read_bytes(), b"current")


if __name__ == "__main__":
    unittest.main()
