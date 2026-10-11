"""Finance evals, scripts only: the finance scripts against six messy synthetic churches.

Each church in evals/finance/churches has books built to be hard to read in one way a real
church's books are, and a list of checks for what a careful bookkeeper would see. A check
with no gap note must pass. A check with a gap note is a known weakness and must still fail;
when a fix makes it pass, this test fails until the gap note is removed, so the check then
guards the fix.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals/finance"))
import score  # noqa: E402
from churches import ALL  # noqa: E402


class FinanceEvalTests(unittest.TestCase):
    def test_each_church(self):
        for cid in ALL:
            with self.subTest(church=cid):
                for r in score.score_church(cid)["results"]:
                    with self.subTest(check=r["check"]):
                        if r["gap"]:
                            self.assertFalse(r["passed"], f"{cid}/{r['check']} now passes; remove its gap note "
                                                          f"({r['gap']}). Seen: {r['seen']}")
                        else:
                            self.assertTrue(r["passed"], f"{cid}/{r['check']}: {r['why']} Seen: {r['seen']}")

    def test_books_balance(self):
        """Every eval church's balance sheet balances and its equity moves with the result."""
        import books as B
        for cid, module in ALL.items():
            with self.subTest(church=cid):
                b = B.Books(module.CHURCH)
                cols, bal = b.balances(b.last)
                kinds = {a["name"]: a["kind"] for a in module.CHURCH["balance"]}
                for i in range(len(cols)):
                    assets = sum(bal[n][i] for n, k in kinds.items() if k in ("bank", "other_asset", "investment"))
                    claims = sum(bal[n][i] for n, k in kinds.items() if k in ("liability", "equity"))
                    claims += bal["Retained Earnings"][i] + bal["Net Income"][i]
                    self.assertAlmostEqual(assets, claims, places=2)

    def test_stand_in_connector_reads_only_and_cuts_off_like_the_real_one(self):
        import quickbooks_stub as stub
        import books as B
        books = B.Books(ALL["harbor_light"].CHURCH)
        listed = stub.handle(books, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in listed},
                         {"company_info", "qbo_accounting_get_balance_sheet", "profit_loss_quickbooks_account"})
        pl = stub.handle(books, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "profit_loss_quickbooks_account",
            "arguments": {"periodStart": "2025-09-01", "periodEnd": "2026-08-31"}}})["result"]
        self.assertEqual(len(json.loads(pl["content"][0]["text"])["reportData"]["data"]["rows"]), 100)
        write = stub.handle(books, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                    "params": {"name": "qbo_sales_create_invoice", "arguments": {}}})["result"]
        self.assertTrue(write["isError"])

    def test_grader_finds_figures_the_books_cannot_support(self):
        import skill_eval
        truth = score.truth_figures(ALL["cedar_hollow"])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "cedar_hollow"
            (folder / "finance").mkdir(parents=True)
            (folder / "finance/finance-overview.md").write_text(
                f"Everyday cash is ${truth['cash']:,}, about ${round(truth['cash'], -3):,}. "
                "The meal fund is owed $31,337.\n")
            graded = skill_eval.grade(folder, judge_model=None)
        self.assertEqual(graded["unsupported_figures"], [31337])
        self.assertTrue(all(i["text"] and "{" not in i["text"] for i in graded["rubric"]))

    def test_every_church_has_a_rubric(self):
        for cid, module in ALL.items():
            with self.subTest(church=cid):
                self.assertTrue(module.TRUTH["skill"].get("tell"))
                self.assertTrue(module.TRUTH["skill"].get("avoid"))


if __name__ == "__main__":
    unittest.main()
