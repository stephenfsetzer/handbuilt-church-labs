"""Finance workflow fixes for problems the finance evals found, on invented churches only.

Lantern Hill (a July-to-June year), Millbrook (online gifts waiting in clearing), Harbor Light
(a pull cut off at the connector's limit) and the Riverbend fixture are all fictional.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "skills/finance-report/scripts/finance_report.py"
ONBOARDING = ROOT / "skills/finance-onboarding/scripts/finance_onboarding.py"
sys.path.insert(0, str(ROOT / "evals/finance"))
sys.path.insert(0, str(ROOT / "skills/finance-report/scripts"))
import score  # noqa: E402
import build_report_data  # noqa: E402
from churches import ALL  # noqa: E402

_spec = importlib.util.spec_from_file_location("finance_fixture", ROOT / "tests/fixtures/finance/make_fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def call(script, church, *args):
    done = subprocess.run([sys.executable, str(script), args[0], "--church-folder", str(church), *args[1:]],
                          capture_output=True, text=True, cwd=church)
    try:
        return json.loads(done.stdout), done.returncode, done.stderr
    except ValueError:
        return {}, done.returncode, done.stderr + done.stdout


class EvalChurch(unittest.TestCase):
    """An eval church laid out with its pulls and saved settings, as score.py makes it."""

    cid = None

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / self.cid
        self.run_ = score.Run(ALL[self.cid], self.root)
        self.pulls = self.run_.pulls

    def settings(self):
        self.run_.build(pl_through=False)  # saves the settings the way the score does
        return self.root / "finance/board/config.json"

    def build(self, *extra, pl_ytd="pl-ytd.json"):
        p = self.pulls
        prior = ["--pl-prior", str(p["pl-prior.json"])] if "pl-prior.json" in p else []
        return call(REPORT, self.root, "build", "--month", ALL[self.cid].CHURCH["last_month"],
                    "--prepared", "2026-09-10", "--balance-sheet", str(p["balance-sheet.json"]),
                    "--pl-ytd", str(p[pl_ytd]), *prior, *extra)


class ChurchYearTests(EvalChurch):
    """Bug 1: a church whose year runs July to June gets a July-to-June report."""

    cid = "lantern_hill"

    def test_the_year_so_far_runs_from_july_everywhere_the_report_states_a_year(self):
        config = json.loads(self.settings().read_text())
        self.assertEqual(config["fiscal_year_start"], 7)
        out, code, err = self.build()
        self.assertEqual(code, 0, err)
        report = json.loads((self.root / "finance/board/2026-08/report.json").read_text())
        self.assertEqual(report["meta"]["period_label"], "July to August 2026")
        self.assertEqual(report["meta"]["months"], 2)
        self.assertEqual(report["plan"]["actual"], -14087)
        running = report["plan"]["running"]
        self.assertEqual(running["this_year"][-1], -14087)
        self.assertEqual(len(running["this_year"]), 2)
        self.assertEqual(running["last_year"][-1], 8793)
        self.assertEqual((running["last_year_label"], running["this_year_label"]), ("2025-26", "2026-27"))
        self.assertIn("$14,087 short for the year so far (July to August 2026)", report["short_answer"])
        self.assertIn("last year ended $8,793 ahead", report["short_answer"])
        self.assertEqual(out["year"]["starts"], "July")
        rendered, code, err = call(REPORT, self.root, "render", str(self.root / "finance/board/2026-08/report.json"))
        self.assertEqual(code, 0, err)
        html = next((self.root / "finance/board/2026-08").glob("*.html")).read_text()
        self.assertIn("Year so far, July to August", html)

    def test_a_pull_from_january_is_refused_for_a_july_year(self):
        self.settings()
        books = score.B.Books(ALL[self.cid].CHURCH)
        january = self.root / "pulls/pl-january.json"
        january.write_text(json.dumps(books.pl((2026, 1), (2026, 8))))
        self.pulls["pl-january.json"] = january
        _, code, err = self.build(pl_ytd="pl-january.json")
        self.assertNotEqual(code, 0)
        self.assertIn("it must start July 1, 2026", err)

    def test_setup_will_not_save_without_the_month_the_year_starts(self):
        p = self.pulls
        (self.root / "finance/board/config.json").unlink(missing_ok=True)
        _, code, err = call(REPORT, self.root, "setup", "draft", "--balance-sheet", str(p["balance-sheet.json"]),
                            "--pl-12m", str(p["pl-12m.json"]))
        self.assertEqual(code, 0, err)
        call(REPORT, self.root, "setup", "budget", "--year", "2026", "--none")
        call(REPORT, self.root, "setup", "one-time", "--none")
        _, code, err = call(REPORT, self.root, "setup", "apply", "--approved-by", "Pat Example")
        self.assertNotEqual(code, 0)
        self.assertIn("the month the church's year starts is not known", err)

    def test_a_whole_year_pull_must_follow_the_churchs_year(self):
        books = score.B.Books(ALL[self.cid].CHURCH)
        calendar_year = self.root / "pulls/pl-calendar-2025.json"
        calendar_year.write_text(json.dumps(books.pl((2025, 1), (2025, 12))))
        p = self.pulls
        _, code, err = call(REPORT, self.root, "setup", "draft", "--balance-sheet", str(p["balance-sheet.json"]),
                            "--pl-12m", str(p["pl-12m.json"]), "--company-info", str(p["company-info.json"]),
                            "--pl-year", str(calendar_year))
        self.assertNotEqual(code, 0)
        self.assertIn("twelve months from July 1", err)


class SavedSettingsWithoutTheYearTests(unittest.TestCase):
    """Churches already on the monthly report have settings saved before the year start was kept."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.church = fixture.main(Path(temp.name) / "riverbend")
        self.board = self.church / "finance/board"
        self.config = self.board / "config.json"
        self.pulls = self.board / "2026-08/pulls"

    def build(self, *extra):
        p = self.pulls
        return call(REPORT, self.church, "build", "--month", "2026-08", "--prepared", "2026-09-10",
                    "--balance-sheet", str(p / "balance-sheet.json"), "--pl-ytd", str(p / "pl-ytd.json"),
                    "--pl-prior", str(p / "pl-prior.json"), *extra)

    def drop_the_setting(self):
        settings = json.loads(self.config.read_text())
        settings.pop("fiscal_year_start")
        self.config.write_text(json.dumps(settings, indent=2))

    def test_an_existing_config_builds_once_company_info_is_supplied_and_keeps_it(self):
        self.assertEqual(self.build()[1], 0)
        with_setting = (self.board / "2026-08/report.json").read_text()
        self.drop_the_setting()
        out, code, err = self.build("--company-info", str(self.pulls / "company-info.json"))
        self.assertEqual(code, 0, err)
        self.assertTrue(out["year"]["saved_to_settings"])
        self.assertEqual(json.loads(self.config.read_text())["fiscal_year_start"], 1)
        self.assertEqual((self.board / "2026-08/report.json").read_text(), with_setting)
        # Next month needs no company info: the setting is saved.
        out, code, err = self.build()
        self.assertEqual(code, 0, err)
        self.assertFalse(out["year"]["saved_to_settings"])

    def test_without_the_setting_or_company_info_the_build_stops_and_never_assumes_january(self):
        self.drop_the_setting()
        _, code, err = self.build()
        self.assertNotEqual(code, 0)
        self.assertIn("never assumes the year starts in January", err)
        self.assertIn("--company-info", err)
        status, _, _ = call(REPORT, self.church, "status", "--month", "2026-08")
        self.assertTrue(status["ready"])  # the saved company info pull is enough

    def test_settings_and_company_info_that_disagree_stop_the_build(self):
        info = self.pulls / "company-info.json"
        info.write_text(json.dumps({**fixture.COMPANY_INFO, "fiscalYearStartMonth": "July"}))
        _, code, err = self.build("--company-info", str(info))
        self.assertNotEqual(code, 0)
        self.assertIn("QuickBooks company info says July", err)

    def test_quickbooks_own_company_info_is_read(self):
        info = self.pulls / "company-info.json"
        info.write_text(json.dumps({"CompanyInfo": {"CompanyName": "Riverbend", "FiscalYearStartMonth": "January"}}))
        self.assertEqual(build_report_data.read_fiscal_start(info), 1)


class HeadlineTests(SavedSettingsWithoutTheYearTests):
    """Bug 2: 'Mostly ...' names the largest group, and a group that matches nothing is raised."""

    def configure(self, side, groups):
        settings = json.loads(self.config.read_text())
        settings[side] = groups
        self.config.write_text(json.dumps(settings, indent=2))

    def test_the_headline_names_the_largest_group_not_the_first(self):
        settings = json.loads(self.config.read_text())
        groups = settings["spending_groups"]
        self.configure("spending_groups", [groups[2], groups[0], groups[1], groups[3]])  # mission support first
        out, code, err = self.build()
        self.assertEqual(code, 0, err)
        report = json.loads((self.board / "2026-08/report.json").read_text())
        parts = report["spending"]["parts"]
        largest = max(parts, key=lambda p: p["amount"])["name"].lower()
        self.assertTrue(report["spending"]["headline"].endswith(largest))
        self.assertNotEqual(report["spending"]["headline"], "Mostly mission support")

    def test_the_catch_all_group_is_not_the_headline_and_the_share_matches_it(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "finance-report" / "scripts"))
        import build_report_data as B
        parts = [{"name": "Priest in Charge", "amount": 29}, {"name": "Other spending", "amount": 71}]
        self.assertEqual(B.headline(parts, {"Other spending"}), "Largest: priest in charge")
        self.assertEqual(B.headline([{"name": "Pledges", "amount": 78}, {"name": "Other income", "amount": 22}], {"Other income"}),
                         "Mostly pledges")
        self.assertEqual(B.lead_part(parts, {"Other spending"})["name"], "Priest in Charge")
        self.assertEqual(B.headline([{"name": "Other spending", "amount": 71}], {"Other spending"}), "Mostly other spending")

    def test_the_printed_share_belongs_to_the_named_group(self):
        settings = json.loads(self.config.read_text())
        groups = settings["spending_groups"]
        self.configure("spending_groups", [groups[2], groups[0], groups[1], groups[3]])
        out, code, err = self.build()
        self.assertEqual(code, 0, err)
        report = json.loads((self.board / "2026-08/report.json").read_text())
        lead = next(p for p in report["spending"]["parts"] if p["name"] == report["spending"]["lead"])
        self.assertTrue(report["spending"]["headline"].endswith(lead["name"].lower()))

    def test_a_group_entry_that_is_not_an_account_stops_the_build(self):
        settings = json.loads(self.config.read_text())
        groups = settings["income_groups"]
        groups[0]["accounts"] = ["Member giving"]
        self.configure("income_groups", groups)
        _, code, err = self.build()
        self.assertNotEqual(code, 0)
        self.assertIn("'Member giving', which is not an account number", err)

    def test_a_group_whose_account_number_matches_nothing_goes_to_a_person(self):
        settings = json.loads(self.config.read_text())
        groups = settings["income_groups"]
        groups[1]["accounts"] = ["4999"]
        self.configure("income_groups", groups)
        out, code, err = self.build()
        self.assertEqual(code, 0, err)
        self.assertTrue(any("Preschool rent" in line and "4999" in line for line in out["needs_a_person"]))
        report = json.loads((self.board / "2026-08/report.json").read_text())
        self.assertNotEqual(report["income"]["headline"], "Mostly preschool rent")


class RecordingLagAndBalancesTests(EvalChurch):
    """Bugs 3 and 5: Millbrook's online gifts stop while clearing balances rise, and its liabilities
    are below zero."""

    cid = "millbrook"

    def finding(self, fid):
        return next((f for f in self.run_.findings if f["id"] == fid), None)

    def test_missing_recent_postings_read_as_a_recording_lag_not_a_fall_in_giving(self):
        lag = self.finding("recent_postings")
        self.assertIsNotNone(lag)
        for words in ("Online Gifts", "July and August 2026", "Gatherpay Clearing", "Undeposited Funds",
                      "recording lag", "A decline in giving is not established"):
            self.assertIn(words, lag["finding"])
        self.assertEqual(lag["detail"]["stopped"], ["Online Gifts"])

    def test_without_the_recent_pull_look_says_nothing_about_it(self):
        p = self.pulls
        _, code, err = call(ONBOARDING, self.root, "look", "--balance-sheet", str(p["balance-sheet.json"]),
                            "--pl-12m", str(p["pl-12m.json"]))
        self.assertEqual(code, 0, err)
        findings = json.loads((self.root / "finance/onboarding/findings.json").read_text())["findings"]
        self.assertFalse(any(f["id"] == "recent_postings" for f in findings))

    def test_negative_liabilities_carry_their_balance_and_first_month_below_zero(self):
        found = self.finding("negative_liabilities")
        detail = {d["account"]: (d["balance"], d["below_zero_since"]) for d in found["detail"]}
        self.assertEqual(detail["Deferred Rental Revenue"], (-2400.0, "2025-01"))
        self.assertEqual(detail["Payroll Liabilities"], (-1900.0, "2025-03"))
        self.assertIn("Deferred Rental Revenue -$2,400 (below zero since January 2025)", found["finding"])
        self.settings()
        out, code, err = self.build()
        self.assertEqual(code, 0, err)
        built = {d["account"]: d["below_zero_since_words"] for d in out["liabilities_below_zero"]}
        self.assertEqual(built, {"Payroll Liabilities": "March 2025", "Deferred Rental Revenue": "January 2025"})


class SavedPullIntegrityTests(unittest.TestCase):
    """Bug 4: a saved pull with a dropped cell is refused, not read with figures in the wrong months."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)
        books = score.B.Books(ALL["redwood_crossing"].CHURCH)
        self.sheet, self.pl = books.balance_sheet(books.last), books.pl((2026, 1), books.last)

    def refused(self, loader, data):
        path = self.folder / "pull.json"
        path.write_text(json.dumps(data))
        with self.assertRaises(SystemExit) as caught:
            loader(path)
        return str(caught.exception)

    def test_a_balance_sheet_row_missing_a_cell_is_refused(self):
        row = next(r for r in self.sheet["reportData"]["rows"] if r["cells"][0]["value"] == "1020 Savings")
        del row["cells"][5]
        error = self.refused(build_report_data.load_balance_sheet, self.sheet)
        self.assertIn("1020 Savings", error)
        self.assertIn("cells but the pull has", error)

    def test_a_profit_and_loss_row_without_its_total_is_refused(self):
        row = next(r for r in self.pl["reportData"]["data"]["rows"] if "ITEM" in r["metadata"]["type"])
        row["cells"] = row["cells"][:1]
        self.assertIn("cells but the pull has", self.refused(build_report_data.load_pl, self.pl))


class CutOffPullTests(EvalChurch):
    """Bug 7: a cut-off pull is saved and run; the script records its refusal with section totals only."""

    cid = "harbor_light"

    def test_look_records_the_refusal_and_drafts_nothing(self):
        p = self.pulls
        findings = self.root / "finance/onboarding/findings.json"
        findings.unlink(missing_ok=True)
        _, code, err = call(ONBOARDING, self.root, "look", "--balance-sheet", str(p["balance-sheet.json"]),
                            "--pl-12m", str(p["pl-12m-connector.json"]))
        self.assertNotEqual(code, 0)
        self.assertIn("cut off", err)
        self.assertFalse(findings.exists())
        record = json.loads((self.root / "finance/onboarding/look-blocked.json").read_text())
        self.assertEqual((record["status"], record["code"], record["pull"]),
                         ("blocked", "pull_cut_off", "pl-12m-connector.json"))
        self.assertIn("Income", record["section_totals"])
        self.assertIn("no groups, accounts or findings", record["section_totals_note"])



class CutOffBuildTests(EvalChurch):
    """Bug 7 for the monthly build: lines that do not add up to their section total."""

    cid = "redwood_crossing"

    def test_build_records_the_refusal_in_the_month_folder(self):
        self.settings()
        data = json.loads(self.pulls["pl-ytd.json"].read_text())
        rows = data["reportData"]["data"]["rows"]
        rows.remove(next(r for r in rows if "ITEM" in r["metadata"]["type"]))  # a line the pull lost
        cut = self.root / "pulls/pl-ytd-cut.json"
        cut.write_text(json.dumps(data))
        self.pulls["pl-ytd-cut.json"] = cut
        _, code, err = self.build(pl_ytd="pl-ytd-cut.json")
        self.assertNotEqual(code, 0)
        self.assertIn("cut off", err)
        record = json.loads((self.root / "finance/board/2026-08/blocked.json").read_text())
        self.assertEqual(record["code"], "pull_cut_off")
        self.assertFalse((self.root / "finance/board/2026-08/report.json").exists())
        self.assertEqual(self.build()[1], 0)
        self.assertFalse((self.root / "finance/board/2026-08/blocked.json").exists())


if __name__ == "__main__":
    unittest.main()
