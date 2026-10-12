"""Monthly eval harness contracts; full scenarios run in test_finance_evals."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals/finance"))
import books as B
from churches import ALL
import monthly


class FinanceMonthlyEvalTests(unittest.TestCase):
    def test_monthly_cases_have_actionable_checks_and_explicit_skill_only_gaps(self):
        ids = []
        for cid, truth in monthly.TRUTH.items():
            self.assertIn(cid, ALL)
            for spec in truth["checks"]:
                self.assertTrue(spec["why"])
                ids.append(spec["id"])
                if spec.get("gap"):
                    self.assertIn("skill", spec["gap"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("monthly_final_build_immutable", ids)
        self.assertIn("monthly_final_render_immutable", ids)
        self.assertIn("monthly_history", ids)
        self.assertIn("monthly_unposted_income", ids)

    def test_changed_pull_scenario_changes_the_ledger_not_the_saved_answer(self):
        source = ALL["redwood_crossing"].CHURCH
        books = B.Books(source)
        amount = monthly.TRUTH["redwood_crossing"]["history_adjustment"]
        revised = monthly.revised_books(source, amount)
        prior = monthly.previous_month(source["last_month"])
        before = monthly.ledger_truth(books, prior)
        after = monthly.ledger_truth(revised, prior)
        self.assertEqual(after["result"], before["result"] - amount)
        # Posting to an earlier month changes year to date, not this month's flows.
        self.assertEqual(after["income"], before["income"])
        self.assertEqual(after["spending"], before["spending"])
        self.assertEqual(monthly.ledger_truth(B.Books(source), prior), before)
        self.assertEqual(books.opening_retained, revised.opening_retained)
        _, baseline_balances = books.balances(books.last)
        _, revised_balances = revised.balances(revised.last)
        checking = next(a["name"] for a in books.bs_accounts if a.get("plug"))
        self.assertAlmostEqual(revised_balances[checking][-1], baseline_balances[checking][-1] - amount)
        self.assertEqual({name: values[0] for name, values in baseline_balances.items()},
                         {name: values[0] for name, values in revised_balances.items()})
        self.assertNotEqual(books.balance_sheet(B.parse(prior)), revised.balance_sheet(B.parse(prior)))
        self.assertNotEqual(books.pl((B.parse(prior)[0], 1), B.parse(prior)),
                            revised.pl((B.parse(prior)[0], 1), B.parse(prior)))

    def test_missing_income_scenario_preserves_all_previous_books(self):
        source = ALL["juniper_vale"].CHURCH
        original, unposted = B.Books(source), monthly.unposted_books(source)
        month = source["last_month"]
        previous = monthly.previous_month(month)
        self.assertEqual(monthly.ledger_truth(original, previous), monthly.ledger_truth(unposted, previous))
        self.assertGreater(monthly.ledger_truth(original, month)["income"], 0)
        self.assertEqual(monthly.ledger_truth(unposted, month)["income"], 0)
        self.assertEqual(original.opening_retained, unposted.opening_retained)
        _, baseline_balances = original.balances(original.last)
        _, unposted_balances = unposted.balances(unposted.last)
        checking = next(a["name"] for a in original.bs_accounts if a.get("plug"))
        current_income = monthly.ledger_truth(original, month)["income"]
        self.assertAlmostEqual(unposted_balances[checking][-1], baseline_balances[checking][-1] - current_income)
        self.assertEqual(original.balance_sheet(B.parse(previous)), unposted.balance_sheet(B.parse(previous)))
        self.assertEqual(monthly.ledger_truth(original, month)["spending"],
                         monthly.ledger_truth(unposted, month)["spending"])

    def test_setup_failure_cannot_count_as_an_expected_workflow_gap(self):
        with mock.patch.object(monthly, "MonthlyRun", side_effect=RuntimeError("test setup failed")):
            result = monthly.score_monthly("redwood_crossing")
        self.assertEqual(len(result["results"]), 1)
        check = result["results"][0]
        self.assertFalse(check["passed"])
        self.assertIsNone(check["gap"])
        self.assertIn("test setup failed", check["seen"])

    def test_month_boundaries_work_across_new_year(self):
        self.assertEqual(monthly.previous_month("2026-01"), "2025-12")
        self.assertEqual(monthly.previous_month("2026-08"), "2026-07")


if __name__ == "__main__":
    unittest.main()
