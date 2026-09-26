"""Finance onboarding: four stages on a new synthetic church, with their gates."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ONBOARDING = ROOT / "skills/finance-onboarding/scripts/finance_onboarding.py"
REPORT = ROOT / "skills/finance-report/scripts/finance_report.py"
_spec = importlib.util.spec_from_file_location("finance_fixture", ROOT / "tests/fixtures/finance/make_fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


class FinanceOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = fixture.main(Path(self.temp.name) / "riverbend")
        (self.church / "finance/board/config.json").unlink()
        self.board = self.church / "finance/board"

    def call(self, script: Path, operation: str, *args: str) -> tuple[dict, int, str]:
        process = subprocess.run([sys.executable, str(script), operation, "--church-folder", str(self.church), *args],
                                 capture_output=True, text=True, cwd=self.church)
        try:
            return json.loads(process.stdout), process.returncode, process.stderr
        except ValueError:
            return {}, process.returncode, process.stderr + process.stdout

    def ob(self, *args):
        return self.call(ONBOARDING, *args)

    def report(self, *args):
        return self.call(REPORT, *args)

    def build(self, *extra):
        pulls = self.board / "2026-08/pulls"
        return self.report("build", "--month", "2026-08", "--prepared", "2026-09-10",
                           "--balance-sheet", str(pulls / "balance-sheet.json"),
                           "--pl-ytd", str(pulls / "pl-ytd.json"), "--pl-prior", str(pulls / "pl-prior.json"), *extra)

    def test_four_stages_with_gates_waivers_and_recurring_flags(self):
        oriented, code, _ = self.ob("orient")
        self.assertEqual((oriented["stage"], oriented["locked"], oriented["started_fresh"]), (1, False, True))
        closed, code, _ = self.ob("stage", "--done", "1")
        self.assertEqual((closed["status"], code), ("blocked", 2))

        # Stage 1: findings from the books
        pulls = self.church / "setup-pulls"
        look, code, err = self.ob("look", "--balance-sheet", str(self.board / "2026-08/pulls/balance-sheet.json"),
                                  "--pl-12m", str(pulls / "pl-12m.json"))
        self.assertEqual(code, 0, err)
        summary = " ".join(look["summary"])
        self.assertIn("Stripe $1,250", summary)
        self.assertIn("Giving is", summary)
        self.assertTrue(any("reconciled" in q for q in look["questions_for_treasurer"]))
        (self.church / "finance/finance-overview.md").write_text("# Finance overview\n")
        self.assertEqual(self.ob("stage", "--done", "1")[1], 0)

        # Stage 2: setup and a sample edition
        self.assertEqual(self.ob("stage", "--done", "2")[1], 2)
        self.report("setup", "draft", "--balance-sheet", str(self.board / "2026-08/pulls/balance-sheet.json"),
                    "--pl-12m", str(pulls / "pl-12m.json"), "--pl-year", str(pulls / "pl-2025.json"))
        self.report("setup", "budget", "--year", "2026", "--csv", str(pulls / "budget-vs-actuals-2026.csv"))
        self.report("setup", "one-time", "--year", "2025", "--amount", "25000", "--label", "estate gift", "--done")
        self.assertEqual(self.report("setup", "apply", "--approved-by", "Pat Example")[1], 0)
        self.assertEqual(self.build("--sample")[1], 0)
        self.assertEqual(self.ob("stage", "--done", "2")[1], 0)

        # Stage 3: open items block; a waiver needs a reason; the budget settled itself in setup
        self.assertEqual(self.ob("stage", "--done", "3")[1], 2)
        _, code, err = self.ob("readiness", "--item", "reconciliation", "--status", "waived")
        self.assertNotEqual(code, 0)
        self.assertIn("needs a reason", err)
        for item in ("unrecorded_income", "month_lock", "restricted_funds"):
            self.ob("readiness", "--item", item, "--status", "met")
        self.ob("readiness", "--item", "reconciliation", "--status", "waived", "--reason", "reconciled quarterly for now")
        self.ob("readiness", "--item", "payment_services", "--status", "waived", "--reason", "Stripe recorded at quarter end")
        self.assertEqual(self.ob("stage", "--done", "3")[1], 0)

        # Every report flags what is not met; a waived data item recurs as open
        self.assertEqual(self.build()[1], 0)
        rendered, code, err = self.report("render", str(self.board / "2026-08/report.json"))
        self.assertEqual(code, 0, err)
        report = json.loads((self.board / "2026-08/report.json").read_text())
        states = {r["id"]: r["status"] for r in report["readiness"]}
        self.assertEqual(states["reconciliation"], "waived")
        self.assertEqual(states["payment_services"], "open")
        html = next((self.board / "2026-08").glob("*.html")).read_text()
        text = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", " ", html, flags=re.S)).split())
        self.assertIn("Books readiness", text)
        self.assertIn("$1,250 in Stripe", text)
        self.assertIn("reconciled quarterly for now", text)

        # Stage 4: calendar and a final edition lock the monthly report
        self.assertEqual(self.ob("stage", "--done", "4")[1], 2)
        self.ob("calendar", "--books-closed-by", "the 15th", "--report-by", "the 20th",
                "--meeting", "second Tuesday", "--approver", "Pat Example")
        report["meta"]["status"] = "final"
        (self.board / "2026-08/report.json").write_text(json.dumps(report))
        self.assertEqual(self.ob("stage", "--done", "4")[1], 0)
        self.assertTrue(self.ob("orient")[0]["locked"])


if __name__ == "__main__":
    unittest.main()
