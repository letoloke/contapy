"""Tests for automatic transaction assignment rules."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from contapy.db import DataStore
from contapy.models import Rule, TransactionDraft
from contapy.widgets.rules import RuleDialog, RulesDialog

_APP: QApplication | None = None


def app() -> QApplication:
    global _APP
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


class RuleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "rules.db", seed=False)
        self.account = self.store.add_account("Checking", "Bank", 1_000)
        self.expense = self.store.ensure_category("Bills : Electricity", "expense")
        self.other = self.store.ensure_category("Coffee", "expense")

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def draft(self, **kwargs) -> TransactionDraft:
        values = {
            "date": "2026-11-11",
            "account_id": self.account,
            "payee": "",
            "category_id": None,
            "amount": -50.0,
            "memo": "",
        }
        values.update(kwargs)
        return TransactionDraft(**values)

    # ------------------------------------------------------------- matching
    def test_text_matching_memo_payee_and_case(self) -> None:
        rule = Rule(search="aki", match_memo=True, match_payee=False)
        self.assertTrue(rule.matches("", "Tokyo aki bowl", -10))
        self.assertFalse(rule.matches("Tokyo aki", "", -10))
        self.assertFalse(rule.matches("", "Sushi", -10))

        both = Rule(search="aki", match_memo=True, match_payee=True)
        self.assertTrue(both.matches("Tokyo aki", "", -10))

        sensitive = Rule(search="Aki", match_memo=True, case_sensitive=True)
        self.assertTrue(sensitive.matches("", "Aki", -10))
        self.assertFalse(sensitive.matches("", "aki", -10))

        insensitive = Rule(search="Aki", match_memo=True)
        self.assertTrue(insensitive.matches("", "aki", -10))

    def test_regex_condition_and_invalid_pattern(self) -> None:
        rule = Rule(search=r"\baki\b", match_memo=True, regex=True)
        self.assertTrue(rule.matches("", "lunch at aki today", -10))
        self.assertFalse(rule.matches("", "akira", -10))
        with self.assertRaises(ValueError):
            Rule(search="(", match_memo=True, regex=True).validate()

    def test_amount_operators_and_and_or_combination(self) -> None:
        at_most = Rule(amount_enabled=True, amount_op="-", amount=-100)
        self.assertTrue(at_most.matches("", "", -150))
        self.assertTrue(at_most.matches("", "", -100))
        self.assertFalse(at_most.matches("", "", -50))

        at_least = Rule(amount_enabled=True, amount_op="+", amount=100)
        self.assertTrue(at_least.matches("", "", 150))
        self.assertFalse(at_least.matches("", "", 50))

        exactly = Rule(amount_enabled=True, amount_op="=", amount=-25)
        self.assertTrue(exactly.matches("", "", -25))
        self.assertFalse(exactly.matches("", "", -25.5))

        both = Rule(
            search="coffee",
            match_memo=True,
            amount_enabled=True,
            amount_op="-",
            amount=-10,
            amount_and=True,
        )
        self.assertTrue(both.matches("", "coffee", -20))
        self.assertFalse(both.matches("", "coffee", -5))
        self.assertFalse(both.matches("", "tea", -20))

        either = Rule(
            search="coffee",
            match_memo=True,
            amount_enabled=True,
            amount_op="-",
            amount=-10,
            amount_and=False,
        )
        self.assertTrue(either.matches("", "coffee", -5))
        self.assertTrue(either.matches("", "tea", -20))
        self.assertFalse(either.matches("", "tea", -5))

    def test_validation_requires_a_condition(self) -> None:
        with self.assertRaises(ValueError):
            Rule(search="").validate()
        with self.assertRaises(ValueError):
            Rule(search="x", match_memo=False, match_payee=False).validate()
        Rule(amount_enabled=True, amount=10).validate()

    # ------------------------------------------------------------- storage
    def test_rules_round_trip_in_order_and_toggle(self) -> None:
        first = Rule(
            name="Coffee",
            search="coffee",
            match_memo=True,
            assign_payee="Café",
            payee_overwrite=True,
            assign_memo="Morning",
        )
        second = Rule(
            name="Bills",
            search="electric",
            match_payee=True,
            category_id=self.expense,
            category_overwrite=True,
        )
        first_id = self.store.add_rule(first)
        second_id = self.store.add_rule(second)

        rules = self.store.rules()
        self.assertEqual([rule.id for rule in rules], [first_id, second_id])
        loaded = rules[0]
        self.assertEqual(loaded.name, "Coffee")
        self.assertTrue(loaded.payee_overwrite)
        self.assertEqual(loaded.assign_memo, "Morning")
        self.assertEqual(rules[1].category_id, self.expense)

        self.store.set_rule_enabled(first_id, False)
        self.assertFalse(self.store.rule(first_id).enabled)
        self.store.set_rule_enabled(first_id, True)
        self.assertTrue(self.store.rule(first_id).enabled)

        self.store.update_rule(
            Rule(
                id=second_id,
                name="Power",
                search="power",
                match_payee=True,
                category_id=self.other,
            )
        )
        self.assertEqual(self.store.rule(second_id).name, "Power")
        self.assertEqual(self.store.rule(second_id).category_id, self.other)

        self.store.delete_rule(first_id)
        self.assertEqual([rule.id for rule in self.store.rules()], [second_id])

    # ---------------------------------------------------------- assignments
    def test_assignments_fill_empty_fields_only_by_default(self) -> None:
        self.store.add_rule(
            Rule(
                search="coffee",
                match_memo=True,
                assign_payee="Café",
                category_id=self.other,
                assign_payment="Cash",
                assign_tags="morning",
                assign_memo="Rule note",
            )
        )
        filled = self.store.apply_rules(self.draft(memo="coffee"))
        self.assertEqual(filled.payee, "Café")
        self.assertEqual(filled.category_id, self.other)
        self.assertEqual(filled.payment, "Cash")
        self.assertEqual(filled.tags, "morning")
        # The memo supplied the match, so it is not empty and stays untouched.
        self.assertEqual(filled.memo, "coffee")

        self.store.add_rule(
            Rule(
                search="shop",
                match_payee=True,
                assign_memo="Rule note",
            )
        )
        noted = self.store.apply_rules(self.draft(payee="Corner shop"))
        self.assertEqual(noted.memo, "Rule note")

        kept = self.store.apply_rules(
            self.draft(
                payee="My café",
                category_id=self.expense,
                payment="Card",
                tags="work",
                memo="coffee with friends",
            )
        )
        self.assertEqual(kept.payee, "My café")
        self.assertEqual(kept.category_id, self.expense)
        self.assertEqual(kept.payment, "Card")
        self.assertEqual(kept.tags, "work")
        self.assertEqual(kept.memo, "coffee with friends")

    def test_overwrite_flags_replace_existing_values(self) -> None:
        self.store.add_rule(
            Rule(
                search="coffee",
                match_memo=True,
                assign_payee="Café",
                payee_overwrite=True,
                category_id=self.other,
                category_overwrite=True,
                assign_payment="Cash",
                payment_overwrite=True,
                assign_tags="morning",
                tags_overwrite=True,
                assign_memo="Rule note",
                memo_overwrite=True,
            )
        )
        changed = self.store.apply_rules(
            self.draft(
                payee="Old",
                category_id=self.expense,
                payment="Card",
                tags="work",
                memo="coffee with friends",
            )
        )
        self.assertEqual(changed.payee, "Café")
        self.assertEqual(changed.category_id, self.other)
        self.assertEqual(changed.payment, "Cash")
        self.assertEqual(changed.tags, "morning")
        self.assertEqual(changed.memo, "Rule note")

    def test_later_rules_win_and_disabled_rules_are_skipped(self) -> None:
        self.store.add_rule(
            Rule(
                search="coffee",
                match_memo=True,
                assign_payee="First",
                payee_overwrite=True,
            )
        )
        second = self.store.add_rule(
            Rule(
                search="coffee",
                match_memo=True,
                assign_payee="Second",
                payee_overwrite=True,
            )
        )
        self.assertEqual(
            self.store.apply_rules(self.draft(memo="coffee")).payee, "Second"
        )
        self.store.set_rule_enabled(second, False)
        self.assertEqual(
            self.store.apply_rules(self.draft(memo="coffee")).payee, "First"
        )

    # ------------------------------------------------------------- creation
    def test_add_transaction_applies_rules(self) -> None:
        self.store.add_rule(
            Rule(
                search="electric",
                match_payee=True,
                category_id=self.expense,
                assign_payment="Direct debit",
                assign_tags="home",
            )
        )
        transaction_id = self.store.add_transaction(
            self.draft(payee="Electric Co", amount=-80)
        )
        row = next(
            row for row in self.store.ledger_rows(self.account) if row.id == transaction_id
        )
        self.assertEqual(row.category_id, self.expense)
        self.assertEqual(row.payment, "Direct debit")
        self.assertEqual(row.tags, "home")

    def test_import_applies_rules(self) -> None:
        self.store.add_rule(
            Rule(
                search="coffee",
                match_memo=True,
                category_id=self.other,
                category_overwrite=True,
                assign_tags="imported",
                tags_overwrite=True,
            )
        )
        path = Path(self.tmp.name) / "import.csv"
        path.write_text(
            "Date,Amount,Payee,Memo\n"
            "2026-11-01,-12.50,Corner shop,Coffee beans\n"
            "2026-11-02,-8.00,Corner shop,Tea\n",
            encoding="utf-8",
        )
        added, skipped, _duplicates = self.store.import_csv(path, account_id=self.account)
        self.assertEqual((added, skipped), (2, 0))
        rows = self.store.ledger_rows(self.account)
        coffee = next(row for row in rows if row.memo == "Coffee beans")
        tea = next(row for row in rows if row.memo == "Tea")
        self.assertEqual(coffee.category_id, self.other)
        self.assertEqual(coffee.tags, "imported")
        self.assertIsNone(tea.category_id)
        self.assertEqual(tea.tags, "")

    def test_import_can_skip_automatic_rules(self) -> None:
        self.store.add_rule(
            Rule(
                search="coffee",
                match_memo=True,
                category_id=self.other,
                category_overwrite=True,
                assign_tags="imported",
                tags_overwrite=True,
            )
        )
        path = Path(self.tmp.name) / "raw-import.csv"
        path.write_text(
            "Date,Amount,Payee,Memo\n"
            "2026-11-03,-12.50,Corner shop,Coffee beans\n",
            encoding="utf-8",
        )
        added, skipped, _duplicates = self.store.import_csv(
            path, account_id=self.account, apply_rules=False
        )
        self.assertEqual((added, skipped), (1, 0))
        row = next(
            row
            for row in self.store.ledger_rows(self.account)
            if row.memo == "Coffee beans"
        )
        self.assertIsNone(row.category_id)
        self.assertEqual(row.tags, "")

        path.write_text(
            "Date,Amount,Payee,Memo\n"
            "2026-11-04,-9.00,Corner shop,Coffee beans 2\n",
            encoding="utf-8",
        )
        self.store.import_csv(path, account_id=self.account)
        applied = next(
            row
            for row in self.store.ledger_rows(self.account)
            if row.memo == "Coffee beans 2"
        )
        self.assertEqual(applied.category_id, self.other)
        self.assertEqual(applied.tags, "imported")


class RuleDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "rules-ui.db", seed=False)
        self.account = self.store.add_account("Checking", "Bank", 100)
        self.category = self.store.ensure_category("Food : Coffee", "expense")

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_dialog_builds_and_round_trips_a_rule(self) -> None:
        rule = Rule(
            id=7,
            name="Coffee",
            search="aki",
            match_memo=True,
            match_payee=True,
            case_sensitive=True,
            regex=False,
            amount_enabled=True,
            amount_and=True,
            amount_op="-",
            amount=-100,
            assign_payee="Café",
            payee_overwrite=True,
            category_id=self.category,
            category_overwrite=True,
            assign_payment="Cash",
            payment_overwrite=True,
            assign_tags="food",
            tags_overwrite=True,
            assign_memo="Imported",
            memo_overwrite=True,
        )
        dialog = RuleDialog(self.store, rule)
        self.addCleanup(dialog.deleteLater)
        built = dialog.values()
        self.assertEqual(built.id, 7)
        self.assertEqual(built.name, "Coffee")
        self.assertEqual(built.search, "aki")
        self.assertTrue(built.match_payee)
        self.assertTrue(built.amount_enabled)
        self.assertEqual(built.amount_op, "-")
        self.assertEqual(built.amount, -100)
        self.assertEqual(built.category_id, self.category)
        self.assertEqual(built.assign_payment, "Cash")
        self.assertEqual(built.assign_memo, "Imported")
        self.assertTrue(built.memo_overwrite)

    def test_manager_lists_and_toggles_rules(self) -> None:
        rule_id = self.store.add_rule(
            Rule(name="Coffee", search="coffee", match_memo=True, assign_payee="Café")
        )
        dialog = RulesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.listing.count(), 1)
        item = dialog.listing.item(0)
        self.assertIn("Coffee", item.text())
        self.assertIn("Payee → Café", item.text())
        self.assertEqual(item.checkState(), Qt.CheckState.Checked)

        item.setCheckState(Qt.CheckState.Unchecked)
        self.assertFalse(self.store.rule(rule_id).enabled)
        self.assertTrue(dialog.changed)
