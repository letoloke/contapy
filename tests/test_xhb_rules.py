"""Tests for importing HomeBank automatic-assignment rules."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contapy.db import DataStore
from contapy.models import TransactionDraft
from contapy.xhb_rules import import_xhb_rules

XHB = """<?xml version="1.0"?>
<homebank v="1.5" d="050806">
<cat key="1" name="Bills"/>
<cat key="2" parent="1" flags="1" name="Electricity"/>
<cat key="3" name="Salary" flags="2"/>
<cat key="4" name="Coffee"/>
<pay key="1" name="Netflix"/>
<pay key="2" name="Acme"/>
<pay key="3" name="TelMex"/>
<pay key="4" name="Corner Store"/>
<asg key="1" flags="6" pos="1" name="NETFLIX" payee="1" category="2" amount="0"/>
<asg key="2" flags="1027" pos="2" name="TELMEX" payee="3" category="1" amount="0"/>
<asg key="3" flags="260" pos="3" name="^PAYROLL" category="3" amount="0"/>
<asg key="4" flags="130" pos="4" field="1" name="Acme" payee="2" amount="-99.5"/>
<asg key="5" flags="31" pos="5" name="STORE" payee="4" category="4"
     paymode="6" tags="food" notes="Weekly shop" amount="0"/>
<asg key="6" flags="32" pos="6" name="(prefilled)" payee="1"/>
<asg key="7" flags="6" pos="7" name="MISSING" payee="99" category="404"/>
<asg key="8" flags="6" pos="8" name="" category="2" amount="0"/>
</homebank>
"""


class XhbRulesImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = DataStore(Path(self.tmp.name) / "rules.db", seed=False)
        self.addCleanup(self.store.close)
        self.account = self.store.add_account("Checking", "Bank", 1_000)
        self.path = Path(self.tmp.name) / "wallet.xhb"
        self.path.write_text(XHB, encoding="utf-8")

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

    def test_imports_conditions_assignments_and_categories(self) -> None:
        result = import_xhb_rules(self.store, self.path)
        self.assertEqual(result.imported, 5)
        self.assertEqual(result.categories_created, 4)
        self.assertEqual(result.skipped, 3)
        self.assertEqual(len(self.store.rules()), 5)

        rules = self.store.rules()
        netflix, telmex, payroll, acme, store_rule = rules

        # field defaults to memo; DOPAY + DOCAT create non-overwrite assignments.
        self.assertEqual(netflix.search, "NETFLIX")
        self.assertTrue(netflix.match_memo)
        self.assertFalse(netflix.match_payee)
        self.assertEqual(netflix.assign_payee, "Netflix")
        self.assertFalse(netflix.payee_overwrite)
        category = self.store.category(netflix.category_id)
        self.assertEqual(category.full_name, "Bills : Electricity")
        self.assertFalse(netflix.category_overwrite)

        # OVWCAT replaces the category; EXACT makes matching case-sensitive.
        self.assertTrue(telmex.case_sensitive)
        self.assertTrue(telmex.category_overwrite)
        self.assertFalse(telmex.payee_overwrite)
        self.assertEqual(self.store.category(telmex.category_id).full_name, "Bills")

        # REGEX + DOCAT, and an income parent category created from its flags.
        self.assertTrue(payroll.regex)
        self.assertEqual(payroll.search, "^PAYROLL")
        salary = self.store.category(payroll.category_id)
        self.assertEqual(salary.name, "Salary")
        self.assertEqual(salary.kind, "income")

        # field=1 matches the payee, and AMOUNT requires the exact signed amount.
        self.assertTrue(acme.match_payee)
        self.assertFalse(acme.match_memo)
        self.assertTrue(acme.amount_enabled)
        self.assertEqual(acme.amount_op, "=")
        self.assertAlmostEqual(acme.amount, -99.5)
        self.assertTrue(acme.amount_and)

        # DOMOD/DOTAG map payment modes and space-separated tag names; notes
        # become an overwriting Notes assignment.
        self.assertEqual(store_rule.assign_payment, "Debit card")
        self.assertEqual(store_rule.assign_tags, "food")
        self.assertEqual(store_rule.assign_memo, "Weekly shop")
        self.assertTrue(store_rule.memo_overwrite)
        self.assertFalse(store_rule.tags_overwrite)

    def test_imported_rules_apply_to_new_transactions(self) -> None:
        import_xhb_rules(self.store, self.path)

        assigned = self.store.apply_rules(self.draft(memo="Netflix subscription"))
        self.assertEqual(assigned.payee, "Netflix")
        self.assertEqual(
            self.store.category(assigned.category_id).full_name,
            "Bills : Electricity",
        )

        income = self.store.apply_rules(self.draft(memo="PAYROLL NOVEMBER"))
        self.assertEqual(self.store.category(income.category_id).name, "Salary")

        # Case-sensitive rule ignores lowercase memo text.
        lowercase = self.store.apply_rules(self.draft(memo="store"))
        self.assertEqual(lowercase.payee, "")
        exact = self.store.apply_rules(self.draft(memo="STORE"))
        self.assertEqual(exact.payee, "Corner Store")
        self.assertEqual(exact.payment, "Debit card")
        self.assertEqual(exact.tags, "food")
        self.assertEqual(exact.memo, "Weekly shop")

        # Payee-field rule also needs the matching amount.
        too_large = self.store.apply_rules(self.draft(payee="Acme", amount=-120))
        self.assertEqual(too_large.category_id, None)
        matched = self.store.apply_rules(self.draft(payee="Acme", amount=-99.5))
        self.assertEqual(matched.payee, "Acme")

    def test_reimport_skips_duplicates_and_reports_problems(self) -> None:
        first = import_xhb_rules(self.store, self.path)
        self.assertIn("payee #99", "\n".join(first.warnings))
        self.assertIn("category #404", "\n".join(first.warnings))
        self.assertIn("prefilled", "\n".join(first.warnings))

        second = import_xhb_rules(self.store, self.path)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.duplicates, 5)
        self.assertEqual(second.categories_created, 0)
        self.assertEqual(len(self.store.rules()), 5)
        self.assertIn("already exist", second.summary())

    def test_rejects_files_that_are_not_homebank_wallets(self) -> None:
        other = Path(self.tmp.name) / "other.xml"
        other.write_text("<not-homebank/>", encoding="utf-8")
        with self.assertRaises(ValueError):
            import_xhb_rules(self.store, other)


if __name__ == "__main__":
    unittest.main()
