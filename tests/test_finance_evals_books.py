"""Scenario fidelity tests: generated ledgers are independent of the skill outputs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals/finance"))
import books as B  # noqa: E402
from churches import ALL  # noqa: E402


def row_values(report, label):
    for row in report["reportData"]["data"]["rows"]:
        cells = {cell["name"]: cell["value"] for cell in row["cells"]}
        if cells.get("ACCOUNT_NAME") == label:
            return cells
    raise AssertionError(f"missing report row {label}")


class FinanceEvalBooksTests(unittest.TestCase):
    def test_equity_movement_matches_each_month_even_at_fund_closes(self):
        for cid, module in ALL.items():
            with self.subTest(church=cid):
                books = B.Books(module.CHURCH)
                months, balances = books.balances(books.last)
                equity = [a["name"] for a in books.bs_accounts if a["kind"] == "equity"]
                equity += ["Retained Earnings", "Net Income"]
                for index in range(1, len(months)):
                    change = sum(balances[name][index] - balances[name][index - 1] for name in equity)
                    self.assertAlmostEqual(change, books.month_result(*months[index]), places=2,
                                           msg=f"{cid}: equity does not reconcile for {months[index]}")

    def test_opening_and_change_rows_recombine_into_one_account(self):
        for cid, module in ALL.items():
            with self.subTest(church=cid):
                books = B.Books(module.CHURCH)
                _, balances = books.balances(books.last)
                rows = books.balance_sheet(books.last)["reportData"]["rows"]
                rows_by_name = {row["cells"][0]["value"]: [c["value"] for c in row["cells"][1:]] for row in rows}
                for account in books.bs_accounts:
                    name = account["name"]
                    if not B.CODE.match(name):
                        continue
                    combined = [a + b for a, b in zip(rows_by_name[name], rows_by_name[B.strip_code(name)])]
                    for actual, wanted in zip(combined, balances[name]):
                        self.assertAlmostEqual(actual, wanted, places=2)

    def test_misleading_summary_creates_loss_but_rows_and_ledger_show_surplus(self):
        books = B.Books(ALL["redwood_crossing"].CHURCH)
        start, end = (2025, 1), (2025, 12)
        report = books.pl(start, end)
        net = row_values(report, "Net Income")["DETAIL_NATURAL_HOME_AMOUNT__TOTAL"]
        expenses = row_values(report, "Expenses")["DETAIL_NATURAL_HOME_AMOUNT__TOTAL"]
        self.assertGreater(net, 0)
        self.assertEqual(net, books.period_result(start, end))
        self.assertEqual(report["totalExpenses"], 0)
        self.assertEqual(report["netIncome"], 0)
        self.assertEqual(sum(m["totalExpenses"] for m in report["monthlyBreakdown"]), 2 * expenses)
        self.assertLess(sum(m["netIncome"] for m in report["monthlyBreakdown"]), 0)

    def test_late_posting_changes_history_consistently_without_rewriting_original(self):
        books = B.Books(ALL["redwood_crossing"].CHURCH)
        earlier = books.connector_pl((2025, 1), (2025, 12), pull=1)
        later = books.connector_pl((2025, 1), (2025, 12), pull=2)
        key = "DETAIL_NATURAL_HOME_AMOUNT__TOTAL"
        self.assertEqual(row_values(later, "Net Income")[key] - row_values(earlier, "Net Income")[key], -2400)
        self.assertEqual(earlier, books.connector_pl((2025, 1), (2025, 12), pull=1))
        self.assertEqual(later, books.connector_pl((2025, 1), (2025, 12), pull=3))
        before_months, before = books.balances(books.last)
        after_months, after = books.snapshot(2).balances(books.last)
        self.assertEqual(before_months, after_months)
        index = before_months.index((2025, 12))
        self.assertEqual(before["1010 Checking"][:index], after["1010 Checking"][:index])
        self.assertAlmostEqual(after["1010 Checking"][-1] - before["1010 Checking"][-1], -2400)
        self.assertEqual(books.snapshot(2).opening_retained, books.opening_retained)
        with self.assertRaises(ValueError):
            books.snapshot(0)

    def test_summer_case_has_matching_seasonality_and_observable_posting_gaps(self):
        books = B.Books(ALL["juniper_vale"].CHURCH)
        self.assertLess(books.period_result((2025, 1), (2025, 8)), 0)
        self.assertLess(books.period_result((2026, 1), (2026, 8)), 0)
        self.assertGreater(books.period_result((2025, 1), (2025, 12)), 0)
        totals = books.period_totals((2026, 7), (2026, 8))
        self.assertEqual(totals["4020 Online Gifts"], 0)
        self.assertEqual(totals["4300 Hall Rent"], 0)
        self.assertGreater(books.period_totals((2025, 12), (2025, 12))["4020 Online Gifts"], 0)
        _, balances = books.balances(books.last)
        self.assertGreater(balances["Gatherpay Clearing"][-1], 0)

    def test_prepaid_rent_is_income_without_new_cash(self):
        books = B.Books(ALL["juniper_vale"].CHURCH)
        _, balances = books.balances(books.last)
        earned = books.period_totals((2026, 8), (2026, 8))["4400 Earned Prepaid Rent"]
        liability_change = balances["2300 Prepaid Rental Revenue"][-1] - balances["2300 Prepaid Rental Revenue"][-2]
        all_bank_change = sum(balances[a["name"]][-1] - balances[a["name"]][-2]
                              for a in books.bs_accounts if a["kind"] == "bank")
        self.assertGreater(earned, 0)
        self.assertEqual(liability_change, -earned)
        self.assertAlmostEqual(books.month_result(2026, 8) - all_bank_change, earned, places=2)

    def test_cutoff_is_exactly_one_hundred_without_a_fake_warning(self):
        books = B.Books(ALL["harbor_light"].CHURCH)
        whole = books.pl((2025, 9), (2026, 8))
        cut = books.connector_pl((2025, 9), (2026, 8))
        rows = whole["reportData"]["data"]["rows"]
        self.assertGreater(len(rows), B.CONNECTOR_ROW_LIMIT)
        self.assertEqual(cut["reportData"]["data"]["rows"], rows[:B.CONNECTOR_ROW_LIMIT])
        self.assertNotIn("warning", cut)
        with self.assertRaises(AssertionError):
            row_values(cut, "Net Income")

    def test_heading_postings_remain_separate_from_child_totals(self):
        books = B.Books(ALL["millbrook"].CHURCH)
        report = books.pl((2026, 1), (2026, 8))
        heading = row_values(report, "4000 PLEDGES AND OFFERINGS")
        totals = books.period_totals((2026, 1), (2026, 8))
        self.assertEqual(heading["DETAIL_NATURAL_HOME_AMOUNT__TOTAL_WITHOUT_SUBGROUPS"],
                         round(totals["4000 PLEDGES AND OFFERINGS"], 2))
        children = [a["name"] for a in books.pl_accounts if "4000 PLEDGES AND OFFERINGS" in a.get("under", [])]
        self.assertEqual(heading["DETAIL_NATURAL_HOME_AMOUNT__TOTAL"],
                         round(totals["4000 PLEDGES AND OFFERINGS"] + sum(totals[name] for name in children), 2))


if __name__ == "__main__":
    unittest.main()
