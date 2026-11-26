"""Tests for automatic transaction assignment rules."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from contapy.db import DataStore
from contapy.models import (
    Rule,
    RuleCondition,
    SplitDraft,
    Template,
    TransactionDraft,
)
from contapy.widgets.rules import (
    RuleDialog,
    RulesDialog,
    TemplateDialog,
    TemplatesDialog,
)

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

    def test_apply_rules_to_existing_transactions(self) -> None:
        self.store.add_rule(
            Rule(
                name="Coffee",
                search="coffee",
                match_memo=True,
                assign_payee="Cafe",
                assign_tags="morning",
            )
        )
        transaction_id = self.store.add_transaction(
            self.draft(payee="", memo="coffee with milk"),
            apply_rules=False,
        )

        changed = self.store.apply_rules_to_transactions([transaction_id])

        self.assertEqual(changed, [transaction_id])
        row = self.store.transaction(transaction_id)
        assert row is not None
        self.assertEqual(row.payee, "Cafe")
        self.assertEqual(row.tags, "morning")
        self.assertEqual(
            self.store.apply_rules_to_transactions([transaction_id]), []
        )

    def test_existing_rule_application_skips_transfers_and_splits(self) -> None:
        self.store.add_rule(
            Rule(
                search="transfer",
                match_payee=True,
                assign_payee="Changed",
                payee_overwrite=True,
            )
        )
        destination = self.store.add_account("Savings", "Bank", 0)
        group = self.store.add_transfer(
            self.draft(payee="Transfer", amount=-100),
            destination,
        )
        transfer_ids = [row.id for row in self.store.transfer_legs(group)]
        self.assertEqual(
            self.store.apply_rules_to_transactions(transfer_ids), []
        )

        category = self.store.ensure_category("Split Rule", "expense")
        split_id = self.store.add_transaction(
            self.draft(
                payee="Split",
                memo="transfer",
                amount=-100,
                splits=[
                    SplitDraft(category, -60),
                    SplitDraft(category, -40),
                ],
            )
        )
        self.assertEqual(
            self.store.apply_rules_to_transactions([split_id]), []
        )

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

    def test_multiple_conditions_match_any_or_all(self) -> None:
        any_rule = Rule(
            conditions=[
                RuleCondition(search="coffee", match_memo=True),
                RuleCondition(search="tea", match_memo=True),
            ],
            condition_mode="any",
        )
        self.assertTrue(any_rule.matches("", "coffee time", -10))
        self.assertTrue(any_rule.matches("", "tea time", -10))
        self.assertFalse(any_rule.matches("", "water", -10))

        all_rule = Rule(
            conditions=[
                RuleCondition(search="coffee", match_memo=True),
                RuleCondition(
                    amount_enabled=True, amount_op="-", amount=-100
                ),
            ],
            condition_mode="all",
        )
        self.assertTrue(all_rule.matches("", "coffee", -150))
        self.assertFalse(all_rule.matches("", "coffee", -50))
        self.assertFalse(all_rule.matches("", "tea", -150))

    def test_multiple_conditions_round_trip_and_apply(self) -> None:
        rule_id = self.store.add_rule(
            Rule(
                name="Drinks",
                conditions=[
                    RuleCondition(search="coffee", match_memo=True),
                    RuleCondition(search="tea", match_memo=True),
                ],
                condition_mode="any",
                assign_payee="Café",
            )
        )

        loaded = self.store.rule(rule_id)
        assert loaded is not None
        self.assertEqual(loaded.condition_mode, "any")
        self.assertEqual(
            [condition.search for condition in loaded.conditions],
            ["coffee", "tea"],
        )
        self.assertEqual(
            self.store.apply_rules(self.draft(memo="tea")).payee, "Café"
        )
        self.assertEqual(
            self.store.apply_rules(self.draft(memo="coffee")).payee, "Café"
        )
        self.assertEqual(
            self.store.apply_rules(self.draft(memo="water")).payee, ""
        )

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

    def test_dialog_adds_and_removes_conditions(self) -> None:
        dialog = RuleDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(len(dialog.condition_editors), 1)
        first = dialog.condition_editors[0]
        first.search_edit.setText("coffee")
        dialog.add_condition_button.click()
        self.assertEqual(len(dialog.condition_editors), 2)
        second = dialog.condition_editors[1]
        second.search_edit.setText("tea")
        dialog.condition_mode_combo.setCurrentIndex(
            dialog.condition_mode_combo.findData("any")
        )
        dialog.payee_combo.setEditText("Café")

        rule = dialog.values()
        self.assertEqual(len(rule.conditions), 2)
        self.assertEqual(rule.condition_mode, "any")
        self.assertEqual(rule.search, "coffee")
        self.assertEqual(rule.assign_payee, "Café")
        self.assertTrue(rule.matches("", "coffee", -10))
        self.assertTrue(rule.matches("", "tea", -10))
        self.assertFalse(rule.matches("", "water", -10))

        second.remove_button.click()
        self.assertEqual(len(dialog.condition_editors), 1)
        self.assertFalse(
            dialog.condition_editors[0].remove_button.isEnabled()
        )

    def test_manager_searches_rules_by_name_condition_and_assignment(self) -> None:
        self.store.add_rule(
            Rule(
                name="Coffee",
                search="coffee",
                match_memo=True,
                assign_payee="Café",
            )
        )
        self.store.add_rule(
            Rule(
                name="Rent",
                search="renta",
                match_memo=True,
                assign_payment="Transfer",
            )
        )
        self.store.add_rule(
            Rule(
                name="Groceries",
                search="market",
                match_memo=True,
                category_id=self.category,
            )
        )

        dialog = RulesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.listing.count(), 3)

        dialog.search_edit.setText("Café")
        self.assertEqual(dialog.listing.count(), 1)
        self.assertIn("Coffee", dialog.listing.item(0).text())

        dialog.search_edit.setText("renta")
        self.assertEqual(dialog.listing.count(), 1)
        self.assertIn("Rent", dialog.listing.item(0).text())

        dialog.search_edit.setText("Food : Coffee")
        self.assertEqual(dialog.listing.count(), 1)
        self.assertIn("Groceries", dialog.listing.item(0).text())

        dialog.search_edit.setText("no matching rule")
        self.assertEqual(dialog.listing.count(), 0)

        dialog.search_edit.clear()
        self.assertEqual(dialog.listing.count(), 3)

    def test_search_enter_offers_to_create_a_missing_rule(self) -> None:
        dialog = RulesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        dialog.search_edit.setText("Netflix")
        self.assertEqual(dialog.listing.count(), 0)

        class FakeDialog:
            def __init__(self, store, parent=None):
                self.name_edit = mock.Mock()
                self.condition_editors = []

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def rule(self) -> Rule:
                return Rule(name="Netflix", search="netflix", match_memo=True)

        with mock.patch(
            "contapy.widgets.rules.RuleDialog", FakeDialog
        ), mock.patch(
            "contapy.widgets.rules.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            dialog.search_edit.returnPressed.emit()

        self.assertEqual(question.call_count, 1)
        self.assertIn("Netflix", question.call_args.args[2])
        rules = self.store.rules()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, "Netflix")
        self.assertTrue(dialog.changed)
        self.assertEqual(dialog.search_edit.text(), "")
        self.assertEqual(dialog.listing.count(), 1)

    def test_manager_summary_shows_all_conditions(self) -> None:
        self.store.add_rule(
            Rule(
                name="Drinks",
                conditions=[
                    RuleCondition(search="coffee", match_memo=True),
                    RuleCondition(search="tea", match_memo=True),
                ],
                condition_mode="any",
                assign_payee="Café",
            )
        )

        dialog = RulesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        text = dialog.listing.item(0).text()
        self.assertIn("coffee", text)
        self.assertIn("tea", text)
        self.assertIn(" OR ", text)
        self.assertIn("Payee → Café", text)

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


class TemplateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "batch.db", seed=False)
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

    def test_templates_round_trip_update_and_delete(self) -> None:
        first = self.store.add_template(
            Template(name="Coffee", payee="Café", tags="food")
        )
        second = self.store.add_template(
            Template(
                name="Rent",
                payment="Bank transfer",
                memo="Monthly",
                memo_mode="append",
                status="reconciled",
            )
        )

        self.assertEqual(
            [template.name for template in self.store.templates()],
            ["Coffee", "Rent"],
        )
        loaded = self.store.template(second)
        assert loaded is not None
        self.assertEqual(loaded.payment, "Bank transfer")
        self.assertEqual(loaded.memo_mode, "append")
        self.assertEqual(loaded.status, "reconciled")

        loaded.payee = "Landlord"
        loaded.payee_overwrite = True
        loaded.category_id = self.expense
        loaded.category_set = True
        loaded.category_overwrite = True
        self.store.update_template(loaded)
        updated = self.store.template(second)
        assert updated is not None
        self.assertEqual(updated.payee, "Landlord")
        self.assertTrue(updated.payee_overwrite)
        self.assertEqual(updated.category_id, self.expense)
        self.assertTrue(updated.category_set)
        self.assertTrue(updated.category_overwrite)

        updated.status = "flagged"
        self.store.update_template(updated)
        reloaded = self.store.template(second)
        assert reloaded is not None
        self.assertEqual(reloaded.status, "flagged")

        self.store.delete_template(first)
        self.assertIsNone(self.store.template(first))
        self.assertEqual(
            [template.name for template in self.store.templates()], ["Rent"]
        )

    def test_only_selected_rows_change_and_overwrite_is_per_field(self) -> None:
        empty = self.store.add_transaction(self.draft())
        filled = self.store.add_transaction(
            self.draft(
                payee="Old payee",
                category_id=self.other,
                payment="Cash",
                tags="old",
                memo="Existing memo",
            )
        )
        untouched = self.store.add_transaction(self.draft(payee="Untouched"))

        changed = self.store.apply_template_to_transactions(
            [empty, filled],
            Template(
                payee="New payee",
                payee_overwrite=False,
                category_id=self.expense,
                category_set=True,
                category_overwrite=True,
                payment="Card",
                payment_overwrite=False,
                tags="tag",
                tags_overwrite=False,
                memo="note",
                memo_mode="append",
            ),
        )

        self.assertEqual(changed, [empty, filled])
        first = self.store.transaction(empty)
        second = self.store.transaction(filled)
        third = self.store.transaction(untouched)
        assert first is not None and second is not None and third is not None
        self.assertEqual(first.payee, "New payee")
        self.assertEqual(first.category_id, self.expense)
        self.assertEqual(first.payment, "Card")
        self.assertEqual(first.tags, "tag")
        self.assertEqual(first.memo, "note")

        self.assertEqual(second.payee, "Old payee")
        self.assertEqual(second.category_id, self.expense)
        self.assertEqual(second.payment, "Cash")
        self.assertEqual(second.tags, "old")
        self.assertEqual(second.memo, "Existing memo note")

        self.assertEqual(third.payee, "Untouched")
        self.assertIsNone(third.category_id)
        self.assertEqual(third.memo, "")

    def test_overwrite_can_clear_a_category_and_replace_a_memo(self) -> None:
        transaction_id = self.store.add_transaction(
            self.draft(
                payee="Old",
                category_id=self.other,
                memo="Old memo",
            )
        )

        changed = self.store.apply_template_to_transactions(
            [transaction_id],
            Template(
                payee="New",
                payee_overwrite=True,
                category_id=None,
                category_set=True,
                category_overwrite=True,
                memo="Replacement",
                memo_mode="overwrite",
            ),
        )

        self.assertEqual(changed, [transaction_id])
        row = self.store.transaction(transaction_id)
        assert row is not None
        self.assertEqual(row.payee, "New")
        self.assertIsNone(row.category_id)
        self.assertEqual(row.memo, "Replacement")

    def test_status_assignment_replaces_transaction_flags(self) -> None:
        transaction_id = self.store.add_transaction(
            self.draft(
                cleared=False,
                remind=True,
                flagged=True,
                voided=True,
            )
        )

        changed = self.store.apply_template_to_transactions(
            [transaction_id], Template(status="reconciled")
        )

        self.assertEqual(changed, [transaction_id])
        row = self.store.transaction(transaction_id)
        assert row is not None
        self.assertTrue(row.cleared)
        self.assertTrue(row.reconciled)
        self.assertFalse(row.remind)
        self.assertFalse(row.flagged)
        self.assertFalse(row.voided)

        self.store.apply_template_to_transactions(
            [transaction_id], Template(status="none")
        )
        row = self.store.transaction(transaction_id)
        assert row is not None
        self.assertFalse(row.cleared)
        self.assertFalse(row.reconciled)
        self.assertFalse(row.remind)
        self.assertFalse(row.flagged)
        self.assertFalse(row.voided)

        self.store.apply_template_to_transactions(
            [transaction_id], Template(status="voided")
        )
        row = self.store.transaction(transaction_id)
        assert row is not None
        self.assertFalse(row.cleared)
        self.assertFalse(row.reconciled)
        self.assertFalse(row.remind)
        self.assertFalse(row.flagged)
        self.assertTrue(row.voided)

    def test_transfers_and_splits_are_skipped(self) -> None:
        destination = self.store.add_account("Savings", "Bank", 0)
        group = self.store.add_transfer(
            self.draft(payee="Transfer", amount=-100),
            destination,
        )
        transfer_ids = [row.id for row in self.store.transfer_legs(group)]
        split_id = self.store.add_transaction(
            self.draft(
                payee="Split",
                amount=-100,
                splits=[
                    SplitDraft(self.expense, -60),
                    SplitDraft(self.expense, -40),
                ],
            )
        )

        changed = self.store.apply_template_to_transactions(
            [*transfer_ids, split_id],
            Template(payee="Changed", payee_overwrite=True),
        )

        self.assertEqual(changed, [])
        for transaction_id in transfer_ids:
            leg = self.store.transaction(transaction_id)
            assert leg is not None
            self.assertEqual(leg.payee, "Transfer")
        split = self.store.transaction(split_id)
        assert split is not None
        self.assertEqual(split.payee, "Split")

    def test_values_that_would_not_change_anything_are_not_reported(self) -> None:
        transaction_id = self.store.add_transaction(
            self.draft(payee="Already set", memo="Already noted")
        )

        changed = self.store.apply_template_to_transactions(
            [transaction_id],
            Template(
                payee="Ignored",
                payee_overwrite=False,
                memo="Ignored",
                memo_mode="empty",
            ),
        )

        self.assertEqual(changed, [])


class TemplateDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        app()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = DataStore(Path(self.tmp.name) / "template-ui.db", seed=False)
        self.store.add_account("Checking", "Bank", 100)
        self.category = self.store.ensure_category("Food : Coffee", "expense")

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_editor_returns_template_values_and_memo_modes(self) -> None:
        dialog = TemplateDialog(self.store)
        self.addCleanup(dialog.deleteLater)

        dialog.name_edit.setText("Coffee")
        dialog.payee_combo.setEditText("Café")
        dialog.payee_overwrite.setChecked(True)
        dialog.category_combo.setCurrentIndex(
            dialog.category_combo.findData(self.category)
        )
        dialog.category_combo.setEditText("Food : Coffee")
        dialog.category_overwrite.setChecked(False)
        dialog.payment_combo.setEditText("Cash")
        dialog.tags_combo.setEditText("food coffee")
        dialog.status_combo.setCurrentIndex(
            dialog.status_combo.findData("reconciled")
        )
        dialog.memo_edit.setText("Imported")
        dialog.memo_mode.setCurrentIndex(dialog.memo_mode.findData("append"))

        values = dialog.values()

        self.assertEqual(values.name, "Coffee")
        self.assertEqual(values.payee, "Café")
        self.assertTrue(values.payee_overwrite)
        self.assertEqual(values.category_id, self.category)
        self.assertTrue(values.category_set)
        self.assertFalse(values.category_overwrite)
        self.assertEqual(values.payment, "Cash")
        self.assertEqual(values.tags, "food coffee")
        self.assertEqual(values.status, "reconciled")
        self.assertEqual(values.memo, "Imported")
        self.assertEqual(values.memo_mode, "append")
        self.assertTrue(values.has_values())

    def test_editor_populates_an_existing_template(self) -> None:
        dialog = TemplateDialog(
            self.store,
            Template(
                id=7,
                name="Coffee",
                sort_order=3,
                payee="Café",
                payee_overwrite=True,
                category_id=self.category,
                category_set=True,
                category_overwrite=False,
                payment="Cash",
                tags="food",
                memo="Imported",
                memo_mode="append",
                status="flagged",
            ),
        )
        self.addCleanup(dialog.deleteLater)

        values = dialog.values()

        self.assertEqual(values.id, 7)
        self.assertEqual(values.sort_order, 3)
        self.assertEqual(values.name, "Coffee")
        self.assertEqual(values.category_id, self.category)
        self.assertEqual(values.memo_mode, "append")
        self.assertEqual(values.status, "flagged")

    def test_typed_uncategorized_clears_the_category(self) -> None:
        dialog = TemplateDialog(self.store)
        self.addCleanup(dialog.deleteLater)

        dialog.category_combo.setEditText("Uncategorized")
        values = dialog.values()

        self.assertTrue(values.category_set)
        self.assertIsNone(values.category_id)

    def test_manager_lists_searches_and_deletes_templates(self) -> None:
        coffee = self.store.add_template(
            Template(
                name="Coffee",
                payee="Café",
                tags="food",
                status="cleared",
            )
        )
        rent = self.store.add_template(
            Template(name="Rent", payment="Bank transfer")
        )
        dialog = TemplatesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.pick_mode)
        self.assertEqual(dialog.listing.count(), 2)
        self.assertIn("Coffee", dialog.listing.item(0).text())
        self.assertIn("Payee → Café", dialog.listing.item(0).text())
        self.assertIn("Status → Cleared", dialog.listing.item(0).text())

        dialog.search_edit.setText("bank transfer")
        self.assertEqual(dialog.listing.count(), 1)
        self.assertIn("Rent", dialog.listing.item(0).text())

        dialog.search_edit.setText("cleared")
        self.assertEqual(dialog.listing.count(), 1)
        self.assertIn("Coffee", dialog.listing.item(0).text())

        dialog.search_edit.clear()
        dialog.listing.setCurrentRow(0)
        with mock.patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            dialog.delete_template()

        self.assertTrue(dialog.changed)
        self.assertIsNone(self.store.template(coffee))
        self.assertIsNotNone(self.store.template(rent))

    def test_manager_duplicates_a_template(self) -> None:
        original_id = self.store.add_template(
            Template(
                name="Coffee",
                payee="Café",
                payee_overwrite=True,
                tags="food",
                memo="Morning",
                memo_mode="append",
                status="reconciled",
            )
        )
        dialog = TemplatesDialog(self.store)
        self.addCleanup(dialog.deleteLater)
        dialog.listing.setCurrentRow(0)
        dialog.duplicate_template()

        templates = self.store.templates()
        self.assertEqual(
            [template.name for template in templates],
            ["Coffee", "Coffee (copy)"],
        )
        copy = templates[1]
        self.assertNotEqual(copy.id, original_id)
        self.assertEqual(copy.payee, "Café")
        self.assertTrue(copy.payee_overwrite)
        self.assertEqual(copy.tags, "food")
        self.assertEqual(copy.memo, "Morning")
        self.assertEqual(copy.memo_mode, "append")
        self.assertEqual(copy.status, "reconciled")
        self.assertEqual(dialog._current_id(), copy.id)
        self.assertTrue(dialog.changed)

        dialog.duplicate_template()
        self.assertEqual(
            [template.name for template in self.store.templates()],
            ["Coffee", "Coffee (copy)", "Coffee (copy 2)"],
        )

    def test_picker_applies_the_selected_saved_template(self) -> None:
        self.store.add_template(
            Template(name="Coffee", payee="Café", tags="food")
        )
        dialog = TemplatesDialog(self.store, count=3)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(dialog.pick_mode)
        self.assertEqual(
            dialog.windowTitle(), "Apply Template to 3 transaction(s)"
        )
        self.assertFalse(dialog.apply_button.isEnabled())

        dialog.listing.setCurrentRow(0)
        self.assertTrue(dialog.apply_button.isEnabled())
        dialog._apply()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        selected = dialog.template_values()
        assert selected is not None
        self.assertEqual(selected.name, "Coffee")
        self.assertEqual(selected.payee, "Café")
        self.assertEqual(selected.tags, "food")
