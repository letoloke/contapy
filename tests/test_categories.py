"""Tests for subcategories: storage, reports, budgets and the manager dialog."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from contapy.db import DataStore
from contapy.models import Category, ordered_categories
from contapy.widgets.dialogs import (
    CategoriesDialog,
    CategoryDialog,
    CategoryTransactionsDialog,
    TransactionDialog,
)


def insert_transaction(
    store: DataStore,
    account_id: int,
    category_id: int | None,
    amount: float,
    when: date | None = None,
    payee: str = "Payee",
) -> None:
    store.conn.execute(
        "INSERT INTO transactions(account_id, date, payee, category_id, amount, "
        "cleared, reconciled, remind, flagged, voided) VALUES (?,?,?,?,?,1,0,0,0,0)",
        (
            account_id,
            (when or date.today()).isoformat(),
            payee,
            category_id,
            amount,
        ),
    )
    store.conn.commit()


class SubcategoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "subs.db", seed=False)
        cur = self.store.conn.execute(
            "INSERT INTO accounts(name, kind, opening, sort_order) VALUES ('Bank','Bank',0,0)"
        )
        self.account_id = int(cur.lastrowid)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    # ------------------------------------------------------------- hierarchy
    def test_full_name_and_alphabetical_ordering(self) -> None:
        parent = Category(id=1, name="Bills", kind="expense", sort_order=3)
        child = Category(
            id=2, name="Electricity", kind="expense", sort_order=3, parent_id=1,
            parent_name="Bills",
        )
        other = Category(id=3, name="renta", kind="expense", sort_order=0)
        coffee = Category(id=4, name="Coffee", kind="expense", sort_order=1)
        self.assertEqual(child.full_name, "Bills : Electricity")
        self.assertEqual(parent.full_name, "Bills")
        ordered = ordered_categories([child, other, parent, coffee])
        self.assertEqual([c.id for c in ordered], [1, 2, 4, 3])

    def test_add_category_creates_a_subcategory(self) -> None:
        parent_id = self.store.add_category("Bills", "expense")
        child_id = self.store.add_category("Electricity", "expense", parent_id)
        parent, child = self.store.category(parent_id), self.store.category(child_id)
        self.assertIsNone(parent.parent_id)
        self.assertEqual(child.parent_id, parent_id)
        self.assertEqual(child.parent_name, "Bills")
        self.assertEqual(child.full_name, "Bills : Electricity")
        self.assertEqual(child.color, parent.color)
        self.assertEqual(child.sort_order, parent.sort_order)

    def test_subcategory_rules_are_enforced(self) -> None:
        parent_id = self.store.add_category("Bills", "expense")
        child_id = self.store.add_category("Electricity", "expense", parent_id)
        with self.assertRaises(ValueError):
            self.store.add_category("Voltage", "expense", child_id)
        income_id = self.store.add_category("Salary", "income")
        with self.assertRaises(ValueError):
            self.store.add_category("Bonus", "expense", income_id)
        with self.assertRaises(ValueError):
            self.store.add_category("", "expense")
        with self.assertRaises(ValueError):
            self.store.add_category("Bills", "expense")

    def test_update_category_renames_and_reparents(self) -> None:
        first = self.store.add_category("First", "expense")
        second = self.store.add_category("Second", "expense")
        child = self.store.add_category("Child", "expense", first)
        self.store.update_category(child, "Renamed", "expense", second)
        updated = self.store.category(child)
        self.assertEqual(updated.name, "Renamed")
        self.assertEqual(updated.parent_id, second)
        self.assertEqual(updated.full_name, "Second : Renamed")

    def test_update_category_syncs_children_types(self) -> None:
        parent = self.store.add_category("Bills", "expense")
        child = self.store.add_category("Electricity", "expense", parent)
        self.store.update_category(parent, "Bills", "income", None)
        self.assertEqual(self.store.category(child).kind, "income")

    def test_delete_subcategory_moves_transactions_to_its_parent(self) -> None:
        parent = self.store.add_category("Bills", "expense")
        child = self.store.add_category("Electricity", "expense", parent)
        insert_transaction(self.store, self.account_id, child, -100)
        insert_transaction(self.store, self.account_id, child, -50)

        moved = self.store.delete_category(child)
        self.assertEqual(moved, 2)
        rows = self.store.ledger_rows(self.account_id)
        self.assertTrue(rows)
        self.assertTrue(all(row.category_id == parent for row in rows))
        self.assertTrue(all(row.category_name == "Bills" for row in rows))

    def test_delete_parent_promotes_children_and_uncategorizes(self) -> None:
        parent = self.store.add_category("Bills", "expense")
        child = self.store.add_category("Electricity", "expense", parent)
        insert_transaction(self.store, self.account_id, parent, -100)

        self.store.delete_category(parent)
        promoted = self.store.category(child)
        self.assertIsNone(promoted.parent_id)
        self.assertEqual(promoted.full_name, "Electricity")
        rows = self.store.ledger_rows(self.account_id)
        self.assertTrue(rows)
        self.assertTrue(all(row.category_id is None for row in rows))

    # ---------------------------------------------------------------- reports
    def _seed_reports(self) -> tuple[int, int]:
        parent = self.store.add_category("alimentos", "expense")
        child = self.store.add_category("despensa", "expense", parent)
        insert_transaction(self.store, self.account_id, parent, -300)
        insert_transaction(self.store, self.account_id, child, -200)
        return parent, child

    def test_report_detail_lists_subcategories_with_full_names(self) -> None:
        _parent, _child = self._seed_reports()
        start = date.today() - timedelta(days=1)
        rows = self.store.report_rows(start, date.today(), kind="expense")
        self.assertEqual(
            [row.label for row in rows], ["alimentos", "alimentos : despensa"]
        )
        self.assertAlmostEqual(sum(-row.expense for row in rows), 500.0, places=2)

    def test_report_rollup_folds_subcategories_into_their_parent(self) -> None:
        _parent, _child = self._seed_reports()
        start = date.today() - timedelta(days=1)
        rows = self.store.report_rows(start, date.today(), kind="expense", rollup=True)
        self.assertEqual([row.label for row in rows], ["alimentos"])
        self.assertAlmostEqual(-rows[0].expense, 500.0, places=2)

    def test_report_search_matches_a_parent_for_subcategory_rows(self) -> None:
        _parent, _child = self._seed_reports()
        start = date.today() - timedelta(days=1)
        rows = self.store.report_rows(
            start, date.today(), kind="expense", search="alimentos"
        )
        self.assertEqual(len(rows), 2)

    def test_donut_rolls_subcategories_into_their_parent(self) -> None:
        _parent, _child = self._seed_reports()
        start = date.today() - timedelta(days=1)
        slices, total = self.store.spend_by_category(start, date.today())
        self.assertEqual([slice_.name for slice_ in slices], ["alimentos"])
        self.assertAlmostEqual(total, 500.0, places=2)

    def test_budget_on_a_parent_includes_subcategory_spending(self) -> None:
        parent, child = self._seed_reports()
        self.store.set_budget(parent, 1_000)
        status = self.store.budget_report(date.today().replace(day=1))[0]
        self.assertEqual(status.category_name, "alimentos")
        self.assertAlmostEqual(status.spent, 500.0, places=2)

        self.store.set_budget(child, 250)
        statuses = {
            status.category_name: status
            for status in self.store.budget_report(date.today().replace(day=1))
        }
        self.assertAlmostEqual(statuses["alimentos"].spent, 500.0, places=2)
        self.assertAlmostEqual(statuses["alimentos : despensa"].spent, 200.0, places=2)

    # ---------------------------------------------------------- transactions
    def test_category_transactions_filters_by_category(self) -> None:
        parent, child = self._seed_reports()
        other = self.store.add_category("renta", "expense")
        insert_transaction(self.store, self.account_id, other, -50)

        rows = self.store.category_transactions(parent)
        self.assertEqual({row.category_id for row in rows}, {parent, child})
        self.assertAlmostEqual(sum(row.amount for row in rows), -500.0, places=2)

        only_parent = self.store.category_transactions(
            parent, include_subcategories=False
        )
        self.assertEqual([row.category_id for row in only_parent], [parent])

        child_rows = self.store.category_transactions(child)
        self.assertEqual([row.category_id for row in child_rows], [child])
        self.assertEqual(self.store.category_transactions(99_999), [])

    def test_category_transactions_are_newest_first(self) -> None:
        category = self.store.add_category("Food", "expense")
        today = date.today()
        insert_transaction(
            self.store, self.account_id, category, -10, today - timedelta(days=3)
        )
        insert_transaction(
            self.store, self.account_id, category, -20, today - timedelta(days=1)
        )
        insert_transaction(self.store, self.account_id, category, -30, today)

        rows = self.store.category_transactions(category)
        self.assertEqual([row.amount for row in rows], [-30.0, -20.0, -10.0])
        self.assertEqual(
            [row.date for row in rows],
            [
                today.isoformat(),
                (today - timedelta(days=1)).isoformat(),
                (today - timedelta(days=3)).isoformat(),
            ],
        )

    def test_category_transactions_include_voided_rows(self) -> None:
        category = self.store.add_category("Food", "expense")
        insert_transaction(self.store, self.account_id, category, -10)
        self.store.conn.execute(
            "UPDATE transactions SET voided=1 WHERE category_id=?", (category,)
        )
        self.store.conn.commit()
        rows = self.store.category_transactions(category)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].voided)

    # ---------------------------------------------------------------- imports
    def test_ensure_category_parses_parent_child_labels(self) -> None:
        first = self.store.ensure_category("Bills : Electricity", "expense")
        again = self.store.ensure_category("Bills : Electricity", "expense")
        category = self.store.category(first)
        self.assertEqual(first, again)
        self.assertEqual(category.full_name, "Bills : Electricity")
        self.assertEqual(category.parent_name, "Bills")

        plain = self.store.ensure_category("renta", "expense")
        self.assertIsNone(self.store.category(plain).parent_id)

    def test_ensure_category_accepts_colon_variants(self) -> None:
        no_spaces = self.store.ensure_category("Bills:Electricity", "expense")
        self.assertEqual(
            self.store.category(no_spaces).full_name, "Bills : Electricity"
        )
        padded = self.store.ensure_category("  Bills  :  Electricity  ", "expense")
        self.assertEqual(no_spaces, padded)

        # A half-finished label still creates a usable category.
        trailing = self.store.ensure_category("Water:", "expense")
        self.assertEqual(self.store.category(trailing).name, "Water")
        leading = self.store.ensure_category(":Gas", "expense")
        self.assertEqual(self.store.category(leading).name, "Gas")

        with self.assertRaises(ValueError):
            self.store.ensure_category("   ", "expense")
        with self.assertRaises(ValueError):
            self.store.ensure_category(":", "expense")

    def test_ensure_category_reuses_names_case_insensitively(self) -> None:
        first = self.store.ensure_category("comida", "expense")
        self.assertEqual(self.store.ensure_category("Comida", "expense"), first)
        self.assertEqual(self.store.ensure_category("COMIDA", "expense"), first)

        child = self.store.ensure_category("comida:despensa", "expense")
        self.assertEqual(
            self.store.ensure_category("Comida : Despensa", "expense"), child
        )
        self.assertEqual(len([c for c in self.store.categories() if c.name == "comida"]), 1)

    def test_ensure_category_inherits_the_parent_type(self) -> None:
        parent = self.store.ensure_category("Salary", "income")
        child = self.store.ensure_category("Salary:Bonus", "income")
        self.assertEqual(self.store.category(child).kind, "income")
        self.assertEqual(self.store.category(child).parent_id, parent)

    def test_import_creates_categories_from_typed_text(self) -> None:
        path = Path(self.tmp.name) / "typed.csv"
        path.write_text(
            "date,amount,payee,category\n"
            "2026-11-06,-50.00,Store,comida:despensa\n"
            "2026-11-06,-12.00,Cafe,comida\n",
            encoding="utf-8",
        )
        added, _skipped, _duplicates = self.store.import_csv(
            path, account_id=self.account_id
        )
        self.assertEqual(added, 2)
        names = {c.full_name for c in self.store.categories()}
        self.assertIn("comida", names)
        self.assertIn("comida : despensa", names)

        rows = self.store.ledger_rows(self.account_id)
        labels = {row.payee: row.category_name for row in rows}
        self.assertEqual(labels["Store"], "comida : despensa")
        self.assertEqual(labels["Cafe"], "comida")

    def test_import_leaves_invalid_category_text_uncategorized(self) -> None:
        path = Path(self.tmp.name) / "invalid.csv"
        path.write_text(
            "date,amount,payee,category\n"
            "2026-11-06,-9.00,Store,:\n",
            encoding="utf-8",
        )
        added, _skipped, _duplicates = self.store.import_csv(
            path, account_id=self.account_id
        )
        self.assertEqual(added, 1)
        rows = self.store.ledger_rows(self.account_id)
        self.assertTrue(rows)
        self.assertIsNone(rows[0].category_id)

    def test_export_and_import_preserves_subcategories(self) -> None:
        parent, child = self._seed_reports()
        path = Path(self.tmp.name) / "export.csv"
        exported = self.store.export_csv(path)

        second = DataStore(Path(self.tmp.name) / "second.db", seed=False)
        try:
            added, _skipped, _duplicates = second.import_csv(path)
            self.assertEqual(added, exported)
            names = {c.full_name for c in second.categories()}
            self.assertIn("alimentos", names)
            self.assertIn("alimentos : despensa", names)
        finally:
            second.close()

    # ------------------------------------------------------------------- seed
    def test_demo_data_includes_subcategories(self) -> None:
        demo = DataStore(Path(self.tmp.name) / "demo.db")
        try:
            categories = demo.categories()
            subs = [c for c in categories if c.parent_id is not None]
            self.assertEqual(len(subs), 3)
            self.assertTrue(all(c.parent_name for c in subs))
            parents = {c.id: c for c in categories if c.parent_id is None}
            self.assertTrue(
                all(c.parent_id in parents and parents[c.parent_id].kind == "expense"
                    for c in subs)
            )
        finally:
            demo.close()


class CategoryDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _store(self) -> DataStore:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = DataStore(Path(tmp.name) / "dialog.db", seed=False)
        self.addCleanup(store.close)
        return store

    def test_values_and_parent_preselection(self) -> None:
        store = self._store()
        parent = store.add_category("Bills", "expense")
        dialog = CategoryDialog(store, parent_id=parent)
        dialog.name_edit.setText("Electricity")
        name, kind, parent_id = dialog.values()
        self.assertEqual((name, kind, parent_id), ("Electricity", "expense", parent))
        dialog.deleteLater()

    def test_parent_combo_follows_the_selected_type(self) -> None:
        store = self._store()
        store.add_category("Bills", "expense")
        salary = store.add_category("Salary", "income")
        dialog = CategoryDialog(store)
        texts = [dialog.parent_combo.itemText(i) for i in range(dialog.parent_combo.count())]
        self.assertIn("Bills", texts)
        self.assertNotIn("Salary", texts)

        dialog.kind_combo.setCurrentIndex(1)
        texts = [dialog.parent_combo.itemText(i) for i in range(dialog.parent_combo.count())]
        self.assertIn("Salary", texts)
        self.assertNotIn("Bills", texts)
        self.assertEqual(dialog.parent_combo.currentData(), None)
        self.assertIn(salary, [
            dialog.parent_combo.itemData(i) for i in range(dialog.parent_combo.count())
        ])
        dialog.deleteLater()

    def test_categories_dialog_lists_and_tracks_changes(self) -> None:
        store = self._store()
        parent = store.add_category("Bills", "expense")
        store.add_category("Electricity", "expense", parent)
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        texts = [dialog.listing.item(i).text().split("\n")[0] for i in range(dialog.listing.count())]
        self.assertEqual(texts, ["Bills", "Bills : Electricity"])

        dialog.listing.setCurrentRow(1)
        self.assertEqual(dialog._selected_category().full_name, "Bills : Electricity")
        self.assertEqual(dialog._default_parent_id(), parent)

        child = store.add_category("Water", "expense", parent)
        dialog._reload_list(select_id=child)
        self.assertEqual(dialog._selected_category().full_name, "Bills : Water")

    def test_new_category_dialog_opens_on_the_active_tab_type(self) -> None:
        store = self._store()
        dialog = CategoryDialog(store, kind="income")
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.kind_combo.currentData(), "income")

    def test_categories_dialog_separates_income_and_expense_tabs(self) -> None:
        store = self._store()
        store.add_category("Bills", "expense")
        store.add_category("Salary", "income")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.tabs.count(), 2)
        self.assertEqual(
            [dialog.tabs.tabText(i) for i in range(2)],
            ["Expense (1)", "Income (1)"],
        )
        self.assertIs(dialog.tabs.currentWidget(), dialog.expense_listing)
        self.assertEqual(
            [
                dialog.expense_listing.item(i).text().split("\n")[0]
                for i in range(dialog.expense_listing.count())
            ],
            ["Bills"],
        )
        self.assertEqual(
            [
                dialog.income_listing.item(i).text().split("\n")[0]
                for i in range(dialog.income_listing.count())
            ],
            ["Salary"],
        )

        dialog.tabs.setCurrentWidget(dialog.income_listing)
        self.assertIs(dialog.listing, dialog.income_listing)
        self.assertEqual(dialog._current_kind(), "income")
        self.assertIsNone(dialog._selected_category())

    def test_reloading_a_selected_category_opens_its_tab(self) -> None:
        store = self._store()
        store.add_category("Bills", "expense")
        salary = store.add_category("Salary", "income")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)

        dialog._reload_list(select_id=salary)
        self.assertIs(dialog.tabs.currentWidget(), dialog.income_listing)
        self.assertEqual(dialog._selected_category().id, salary)

    def test_delete_key_works_on_the_income_tab(self) -> None:
        store = self._store()
        category = store.add_category("Salary", "income")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.tabs.setCurrentWidget(dialog.income_listing)
        dialog.income_listing.setCurrentRow(0)

        with mock.patch.object(
            QMessageBox, "exec", return_value=QMessageBox.StandardButton.Discard
        ):
            QTest.keyClick(dialog.income_listing, Qt.Key.Key_Delete)

        self.assertIsNone(store.category(category))
        self.assertTrue(dialog.changed)

    def test_enter_key_opens_the_selected_category_for_editing(self) -> None:
        store = self._store()
        store.add_category("Bills", "expense")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.listing.setCurrentRow(0)

        with mock.patch.object(
            CategoryDialog, "exec", return_value=CategoryDialog.DialogCode.Rejected
        ) as edit_dialog:
            QTest.keyClick(dialog.listing, Qt.Key.Key_Return)

        self.assertEqual(edit_dialog.call_count, 1)

    def test_delete_key_deletes_the_selected_category(self) -> None:
        store = self._store()
        category = store.add_category("Bills", "expense")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.listing.setCurrentRow(0)

        with mock.patch.object(
            QMessageBox, "exec", return_value=QMessageBox.StandardButton.Discard
        ):
            QTest.keyClick(dialog.listing, Qt.Key.Key_Delete)

        self.assertIsNone(store.category(category))
        self.assertTrue(dialog.changed)
        self.assertEqual(dialog.listing.count(), 0)

    def test_delete_key_cancel_keeps_the_category(self) -> None:
        store = self._store()
        category = store.add_category("Bills", "expense")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.listing.setCurrentRow(0)

        with mock.patch.object(
            QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel
        ):
            QTest.keyClick(dialog.listing, Qt.Key.Key_Delete)

        self.assertIsNotNone(store.category(category))
        self.assertFalse(dialog.changed)
        self.assertEqual(dialog.listing.count(), 1)

    def test_delete_confirmation_warns_that_it_cannot_be_undone(self) -> None:
        store = self._store()
        store.add_category("Bills", "expense")
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.listing.setCurrentRow(0)
        captured: dict[str, str] = {}

        def fake_exec(box):
            captured["text"] = box.text()
            captured["info"] = box.informativeText()
            captured["icon"] = box.icon()
            return QMessageBox.StandardButton.Cancel

        with mock.patch.object(QMessageBox, "exec", fake_exec):
            dialog.delete_category()

        self.assertIn("Delete", captured["text"])
        self.assertIn("cannot be undone", captured["info"])
        self.assertEqual(captured["icon"], QMessageBox.Icon.Warning)

    # ------------------------------------------------- category transactions
    def _food_store(self):
        store = self._store()
        store.add_account("Checking", "Bank")
        account_id = store.accounts()[0].id
        food = store.add_category("Food", "expense")
        return store, account_id, food

    def test_category_transactions_dialog_lists_and_summarises(self) -> None:
        store, account_id, food = self._food_store()
        insert_transaction(store, account_id, food, -12.5, payee="Cafe")
        insert_transaction(store, account_id, food, -7.25, payee="Bakery")

        dialog = CategoryTransactionsDialog(store, store.category(food))
        self.addCleanup(dialog.deleteLater)

        self.assertEqual(dialog.table.rowCount(), 2)
        payees = {
            dialog.table.item(row, 2).text()
            for row in range(dialog.table.rowCount())
        }
        self.assertEqual(payees, {"Cafe", "Bakery"})
        self.assertIn("2 transactions", dialog.summary.text())
        self.assertIn("$ -19.75", dialog.summary.text())

    def test_category_transactions_dialog_includes_subcategories_by_default(self) -> None:
        store, account_id, food = self._food_store()
        groceries = store.add_category("Groceries", "expense", food)
        insert_transaction(store, account_id, food, -30, payee="Restaurant")
        insert_transaction(store, account_id, groceries, -20, payee="Market")

        dialog = CategoryTransactionsDialog(store, store.category(food))
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.sub_check.isHidden())
        self.assertEqual(dialog.table.rowCount(), 2)

        dialog.sub_check.setChecked(False)
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 2).text(), "Restaurant")

    def test_category_transactions_dialog_hides_the_subcategory_toggle_for_a_child(self) -> None:
        store, account_id, food = self._food_store()
        groceries = store.add_category("Groceries", "expense", food)
        insert_transaction(store, account_id, groceries, -20)

        dialog = CategoryTransactionsDialog(store, store.category(groceries))
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.sub_check.isHidden())
        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 3).text(), "Food : Groceries")

    def test_category_transactions_dialog_filters_with_search(self) -> None:
        store, account_id, food = self._food_store()
        insert_transaction(store, account_id, food, -12.5, payee="Coffee shop")
        insert_transaction(store, account_id, food, -7.25, payee="Bakery")

        dialog = CategoryTransactionsDialog(store, store.category(food))
        self.addCleanup(dialog.deleteLater)
        dialog.search_edit.setText("coffee")

        self.assertEqual(dialog.table.rowCount(), 1)
        self.assertEqual(dialog.table.item(0, 2).text(), "Coffee shop")
        self.assertIn("1 transaction", dialog.summary.text())

    def test_categories_dialog_transactions_button_requires_a_selection(self) -> None:
        store, _account_id, _food = self._food_store()
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.transactions_button.isEnabled())

        dialog.listing.setCurrentRow(0)
        self.assertTrue(dialog.transactions_button.isEnabled())

    # ------------------------------------------------------- typed categories
    def _transaction_dialog(self, store: DataStore) -> TransactionDialog:
        store.add_account("Checking", "Bank")
        dialog = TransactionDialog(store, store.accounts(), store.categories())
        self.addCleanup(dialog.deleteLater)
        dialog.amount_spin.setValue(42.0)
        return dialog

    def test_transaction_dialog_creates_a_category_from_typed_text(self) -> None:
        store = self._store()
        dialog = self._transaction_dialog(store)
        dialog.category_combo.setEditText("comida")
        dialog._save()

        draft = dialog.draft()
        self.assertIsNotNone(draft)
        category = store.category(draft.category_id)
        self.assertEqual(category.name, "comida")
        self.assertIsNone(category.parent_id)
        self.assertEqual(category.kind, "expense")
        self.assertAlmostEqual(draft.amount, -42.0)

    def test_transaction_dialog_creates_a_subcategory_from_typed_text(self) -> None:
        store = self._store()
        dialog = self._transaction_dialog(store)
        dialog.category_combo.setEditText("comida:despensa")
        dialog._save()

        draft = dialog.draft()
        self.assertIsNotNone(draft)
        self.assertEqual(
            store.category(draft.category_id).full_name, "comida : despensa"
        )
        self.assertIn(
            "comida : despensa",
            [c.full_name for c in store.categories()],
        )

    def test_transaction_dialog_reuses_an_existing_typed_category(self) -> None:
        store = self._store()
        existing = store.add_category("comida", "expense")
        dialog = self._transaction_dialog(store)
        dialog.category_combo.setEditText("Comida")
        dialog._save()

        draft = dialog.draft()
        self.assertIsNotNone(draft)
        self.assertEqual(draft.category_id, existing)
        self.assertEqual(len([c for c in store.categories() if c.name == "comida"]), 1)

    def test_transaction_dialog_uncategorized_creates_nothing(self) -> None:
        store = self._store()
        dialog = self._transaction_dialog(store)
        dialog.category_combo.setEditText("Uncategorized")
        dialog._save()

        draft = dialog.draft()
        self.assertIsNotNone(draft)
        self.assertIsNone(draft.category_id)
        self.assertEqual(store.categories(), [])

    def test_transaction_dialog_warns_and_keeps_open_for_invalid_category(self) -> None:
        store = self._store()
        dialog = self._transaction_dialog(store)
        dialog.category_combo.setEditText(":")
        with mock.patch(
            "contapy.widgets.dialogs.QMessageBox.warning"
        ) as warning:
            dialog._save()
        warning.assert_called_once()
        self.assertIsNone(dialog.draft())
        self.assertEqual(store.categories(), [])

    def test_delete_key_on_a_subcategory_moves_transactions_to_the_parent(self) -> None:
        store = self._store()
        parent = store.add_category("Bills", "expense")
        child = store.add_category("Electricity", "expense", parent)
        cur = store.conn.execute(
            "INSERT INTO accounts(name, kind, opening, sort_order) VALUES ('Bank','Bank',0,0)"
        )
        account_id = int(cur.lastrowid)
        insert_transaction(store, account_id, child, -75)
        dialog = CategoriesDialog(store)
        self.addCleanup(dialog.deleteLater)
        dialog.listing.setCurrentRow(1)

        with mock.patch.object(
            QMessageBox, "exec", return_value=QMessageBox.StandardButton.Discard
        ):
            QTest.keyClick(dialog.listing, Qt.Key.Key_Delete)

        self.assertIsNone(store.category(child))
        rows = store.ledger_rows(account_id)
        self.assertEqual(rows[0].category_id, parent)


if __name__ == "__main__":
    unittest.main()
