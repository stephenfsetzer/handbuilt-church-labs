"""Finance report workflow: accuracy, trust, setup, and the shape's variants.

Every case uses the synthetic church in tests/fixtures/finance (fictional
Riverbend Lutheran Church, QuickBooks responses in the connector's shapes).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from unittest import mock

from tools import church_workflow as bridge
from tests.helpers import make_church

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "skills/finance-report/scripts/finance_report.py"
_spec = importlib.util.spec_from_file_location("finance_fixture", ROOT / "tests/fixtures/finance/make_fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def run(church: Path, operation: str, *args: str) -> tuple[dict, int, str]:
    process = subprocess.run([sys.executable, str(ENTRY), operation, "--church-folder", str(church), *args],
                             capture_output=True, text=True, cwd=church)
    try:
        return json.loads(process.stdout), process.returncode, process.stderr
    except ValueError:
        return {}, process.returncode, process.stderr + process.stdout


def page_text(church: Path, month: str) -> str:
    html = next((church / "finance/board" / month).glob("*.html")).read_text()
    text = re.sub(r"<style>.*?</style>", " ", html, flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


class FinanceReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.church = fixture.main(Path(self.temp.name) / "riverbend")
        self.board = self.church / "finance/board"

    def build(self, month: str, *extra: str) -> tuple[dict, int, str]:
        pulls = self.board / month / "pulls"
        return run(self.church, "build", "--month", month, "--prepared", "2026-09-10",
                   "--balance-sheet", str(pulls / "balance-sheet.json"), "--pl-ytd", str(pulls / "pl-ytd.json"),
                   "--pl-prior", str(pulls / "pl-prior.json"), *extra)

    def render(self, month: str) -> tuple[dict, int, str]:
        return run(self.church, "render", str(self.board / month / "report.json"))

    def two_editions(self):
        self.assertEqual(self.build("2026-07")[1], 0)
        path = self.board / "2026-07/report.json"
        report = json.loads(path.read_text())
        report["watch"] = [{"id": "building", "title": "Building costs over plan", "status": "New",
                            "metric_key": "building_over_plan", "metric": report["metrics"]["building_over_plan"],
                            "better": "down", "latest": "Watching.", "next": "Council to review repairs.",
                            "latest_template": "{building_over_plan} {building_over_plan_word} plan through {month_name}."}]
        path.write_text(json.dumps(report))
        self.assertEqual(self.render("2026-07")[1], 0)
        self.assertEqual(self.build("2026-08")[1], 0)

    # --- the monthly report ---------------------------------------------------

    def test_status_reports_missing_settings_and_brand_is_not_blocking(self):
        config = self.board / "config.json"
        saved = config.read_text()
        config.unlink()
        result, code, _ = run(self.church, "status")
        self.assertEqual(result["status"], "blocked")
        config.write_text(saved)
        result, code, _ = run(self.church, "status", "--month", "2026-07")
        self.assertEqual((result["status"], code), ("ready", 0))

    def test_two_editions_render_two_pages_in_the_neutral_theme(self):
        self.two_editions()
        result, code, err = self.render("2026-08")
        self.assertEqual(code, 0, err)
        self.assertEqual(result["checks"]["pages"], 2)
        receipt = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(receipt["shape_version"], "1.0")
        self.assertTrue(any("fallback" in line for line in receipt["brand_resolution"]))
        self.assertTrue(all("bundled" in line for line in receipt["fonts"]), receipt["fonts"])
        text = page_text(self.church, "2026-08")
        self.assertIn("Seven questions", text)
        self.assertIn("Church Council", text)
        self.assertIn("Riverbend Lutheran Church", text)
        self.assertNotIn("Vestry", text)
        self.assertIn("Up since December 2024", text)
        self.assertIn("2025 ended $25,200 ahead", text)
        self.assertRegex(text, r"Building costs over plan (Better|Worse)")

    def test_a_total_that_disagrees_with_quickbooks_stops_the_build(self):
        pulls = self.board / "2026-08/pulls/pl-ytd.json"
        data = json.loads(pulls.read_text())
        for row in data["reportData"]["data"]["rows"]:
            if row["cells"][0]["value"] == "6520 Repairs":
                row["cells"][1]["value"] += 500
        pulls.write_text(json.dumps(data))
        _, code, err = self.build("2026-08")
        self.assertNotEqual(code, 0)
        self.assertIn("CHECK FAILED", err)

    def test_prior_month_pull_must_cover_the_right_period(self):
        pulls = self.board / "2026-08/pulls"
        _, code, err = run(self.church, "build", "--month", "2026-08", "--prepared", "2026-09-10",
                           "--balance-sheet", str(pulls / "balance-sheet.json"),
                           "--pl-ytd", str(pulls / "pl-ytd.json"), "--pl-prior", str(pulls / "pl-ytd.json"))
        self.assertNotEqual(code, 0)
        self.assertIn("must run January 1 to the end of 2026-07", err)

    def test_partial_prior_rows_cannot_inflate_the_current_month(self):
        pulls = self.board / "2026-08/pulls/pl-prior.json"
        original = json.loads(pulls.read_text())
        data = json.loads(json.dumps(original))
        data["reportData"]["data"]["rows"] = [r for r in data["reportData"]["data"]["rows"] if r["cells"][0]["value"] != "6520 Repairs"]
        pulls.write_text(json.dumps(data))
        _, code, err = self.build("2026-08")
        self.assertNotEqual(code, 0)
        self.assertIn("prior spending groups", err)
        for row in original["reportData"]["data"]["rows"]:
            if row["cells"][0]["value"] in ("6520 Repairs", "Expenses"):
                row["cells"][1]["value"] += 500
        pulls.write_text(json.dumps(original))
        _, code, err = self.build("2026-08")
        self.assertNotEqual(code, 0)
        self.assertIn("prior profit and loss net", err)

    def test_last_years_line_must_match_last_years_recorded_result(self):
        config = self.board / "config.json"
        settings = json.loads(config.read_text())
        settings["long_view"]["full_years"] = [{"year": 2025, "result": 1, "reported": 1}]
        config.write_text(json.dumps(settings))
        _, code, err = self.build("2026-08")
        self.assertNotEqual(code, 0)
        self.assertIn("books for 2025 have changed", err)

    def test_changed_earlier_months_and_new_catch_all_accounts_are_raised(self):
        self.two_editions()
        july = self.board / "2026-07/report.json"
        report = json.loads(july.read_text())
        report["plan"]["actual"] += 1500
        report["catch_all_accounts"] = [a for a in report["catch_all_accounts"] if not a.startswith("7510")]
        july.write_text(json.dumps(report))
        result, code, _ = self.build("2026-08")
        self.assertEqual(code, 0)
        needs = " ".join(result["needs_a_person"])
        self.assertIn("changed since last month", needs)
        self.assertIn("7510 Office Supplies", needs)
        self.render("2026-08")
        self.assertIn("Earlier months changed", page_text(self.church, "2026-08"))

    def test_an_unmatched_figure_warns_on_a_draft_and_blocks_a_final_report(self):
        self.two_editions()
        path = self.board / "2026-08/report.json"
        report = json.loads(path.read_text())
        report["short_answer"] += " We also received a gift of $12,345."
        path.write_text(json.dumps(report))
        result, code, _ = self.render("2026-08")
        self.assertEqual(code, 0)
        self.assertIn("$12,345", " ".join(result["warnings"]))
        report["meta"]["status"] = "final"
        path.write_text(json.dumps(report))
        _, code, err = self.render("2026-08")
        self.assertNotEqual(code, 0)
        self.assertIn("match nothing in the data", err)

    def test_a_report_missing_a_required_part_is_refused(self):
        self.two_editions()
        path = self.board / "2026-08/report.json"
        report = json.loads(path.read_text())
        del report["obligations"]
        path.write_text(json.dumps(report))
        _, code, err = self.render("2026-08")
        self.assertNotEqual(code, 0)
        self.assertIn("missing 'obligations'", err)

    # --- first-time setup and the shape's variants ------------------------------------

    def setup_church(self, budget: list[str]):
        (self.board / "config.json").unlink()
        pulls = self.church / "setup-pulls"
        draft, code, err = run(self.church, "setup", "draft",
                               "--balance-sheet", str(self.board / "2026-08/pulls/balance-sheet.json"),
                               "--pl-12m", str(pulls / "pl-12m.json"), "--pl-year", str(pulls / "pl-2025.json"))
        self.assertEqual(code, 0, err)
        run(self.church, "setup", "budget", "--year", "2026", *budget)
        return draft

    def test_setup_drafts_settings_from_the_books_and_guards_the_save(self):
        draft = self.setup_church(["--csv", str(self.church / "setup-pulls/budget-vs-actuals-2026.csv")])
        self.assertEqual(draft["bank_accounts"], ["Checking - First Bank 1111", "Savings - First Bank 2222"])
        self.assertEqual(draft["endowment_accounts"], ["ELCA Endowment Fund"])
        self.assertEqual(draft["set_aside"], {"CASH": "heading", "Stripe": "payment service",
                                              "Old Checking 9999": "unused", "ELCA Endowment Fund": "investments"})
        self.assertEqual([c["name"] for c in draft["one_time_candidates"]], ["4910 Estate Gift"])
        result, code, err = run(self.church, "setup", "apply", "--approved-by", "Pat Example")
        self.assertNotEqual(code, 0)
        self.assertIn("one-time items not reviewed", err)
        run(self.church, "setup", "one-time", "--year", "2025", "--amount", "25000", "--label", "estate gift", "--done")
        self.assertEqual(run(self.church, "setup", "apply", "--approved-by", "Pat Example")[1], 0)
        self.assertEqual(self.build("2026-08", "--sample")[1], 0)
        result, code, err = self.render("2026-08")
        self.assertEqual((code, result["checks"]["pages"]), (0, 2), err)
        text = page_text(self.church, "2026-08")
        self.assertIn("over plan", text)
        self.assertIn("estate gift", text)

    def test_a_church_without_a_budget_is_told_so_plainly(self):
        self.setup_church(["--none"])
        run(self.church, "setup", "one-time", "--none")
        self.assertEqual(run(self.church, "setup", "apply", "--approved-by", "Pat Example")[1], 0)
        self.assertEqual(self.build("2026-08")[1], 0)
        result, code, err = self.render("2026-08")
        self.assertEqual((code, result["checks"]["pages"]), (0, 2), err)
        self.assertIn("There is no budget to compare with", page_text(self.church, "2026-08"))

    def test_short_history_keeps_page_one_and_drops_the_longer_view(self):
        church = fixture.main(Path(self.temp.name) / "young", short=True)
        pulls = church / "finance/board/2026-08/pulls"
        result, code, err = run(church, "build", "--month", "2026-08", "--prepared", "2026-09-10",
                                "--balance-sheet", str(pulls / "balance-sheet.json"),
                                "--pl-ytd", str(pulls / "pl-ytd.json"), "--pl-prior", str(pulls / "pl-prior.json"))
        self.assertEqual(code, 0, err)
        report = json.loads((church / "finance/board/2026-08/report.json").read_text())
        self.assertTrue(report["short_history"])
        self.assertIsNone(report["plan"]["running"]["last_year"])
        result, code, err = run(church, "render", str(church / "finance/board/2026-08/report.json"))
        self.assertEqual(code, 0, err)
        text = page_text(church, "2026-08")
        self.assertIn("Four questions", text)
        self.assertIn("This is the first year the books can compare", text)
        self.assertNotIn("Question 5", text)
        self.assertIn("Watch list", text)

    def test_nonpositive_spending_builds_and_renders_with_reconciled_sources(self):
        original = fixture.month_values
        for mode in ("zero", "empty", "credits", "reversal"):
            with self.subTest(mode=mode):
                def amounts(year, month):
                    income, expense = original(year, month)
                    if year != 2026:
                        return income, expense
                    if mode == "reversal":
                        if month < 8:
                            return income, expense
                        earlier = [original(year, m) for m in range(1, 8)]
                        return ({k: -sum(pair[0][k] for pair in earlier) for k in income},
                                {k: -sum(pair[1][k] for pair in earlier) for k in expense})
                    if mode in ("zero", "empty"):
                        return {k: 0 for k in income}, {k: 0 for k in expense}
                    return income, {k: -v for k, v in expense.items()}
                with mock.patch.object(fixture, "month_values", amounts), mock.patch.object(fixture, "HEADING_OWN", ("7500 OFFICE", 0)):
                    church = fixture.main(Path(self.temp.name) / mode)
                board = church / "finance/board"
                config_path = board / "config.json"
                config = json.loads(config_path.read_text())
                # Removing the fixture's monthly heading expense also changes 2025.
                config["long_view"]["full_years"][0]["reported"] += 5400
                config["long_view"]["full_years"][0]["result"] += 5400
                config_path.write_text(json.dumps(config))
                pulls = board / "2026-08/pulls"
                if mode in ("empty", "reversal"):
                    files = (pulls / "pl-ytd.json", pulls / "pl-prior.json") if mode == "empty" else (pulls / "pl-ytd.json",)
                    for file in files:
                        data = json.loads(file.read_text())
                        data["reportData"]["data"]["rows"] = [r for r in data["reportData"]["data"]["rows"] if "." not in r["metadata"]["id"]]
                        file.write_text(json.dumps(data))
                result, code, err = run(church, "build", "--month", "2026-08", "--prepared", "2026-09-10",
                    "--balance-sheet", str(pulls / "balance-sheet.json"), "--pl-ytd", str(pulls / "pl-ytd.json"),
                    "--pl-prior", str(pulls / "pl-prior.json"))
                self.assertEqual(code, 0, err)
                report = json.loads((board / "2026-08/report.json").read_text())
                self.assertLessEqual(report["cash"]["monthly_spending"], 0)
                self.assertIn("Cash coverage cannot be estimated", report["short_answer"])
                result, code, err = run(church, "render", str(board / "2026-08/report.json"))
                self.assertEqual(code, 0, err)
                self.assertEqual(result["checks"]["pages"], 2)
                self.assertTrue(result["checks"]["figures_verified"])
                text = page_text(church, "2026-08")
                self.assertIn("Coverage unavailable", text)
                self.assertNotIn("Two months of spending", text)
                self.assertNotIn("months of spending.", report["short_answer"])
                if mode == "credits":
                    self.assertIn("percentages would be misleading", text)
                    self.assertIn("−$", text)
                    self.assertNotIn("including", report["short_answer"])
                    self.assertEqual(report["this_month"]["top_out"]["label"], "Pastor Compensation")
                    self.assertLess(report["this_month"]["top_out"]["amount"], 0)
                elif mode == "reversal":
                    self.assertIn("Net total is zero", text)
                    self.assertLess(report["this_month"]["top_out"]["amount"], 0)
                    self.assertEqual(report["this_month"]["top_out"]["label"], "Pastor Compensation")
                else:
                    self.assertIn("Net total is zero", text)
                    self.assertNotIn("good month", report["short_answer"])
                    self.assertEqual(report["this_month"]["top_out"], {"label": "No net change", "amount": 0})

    def test_zero_and_negative_bank_cash_keep_their_meaning_in_built_reports(self):
        for bank in (0, -300):
            with self.subTest(bank=bank):
                bs = self.board / "2026-08/pulls/balance-sheet.json"
                data = json.loads(bs.read_text())
                for row in data["reportData"]["rows"]:
                    name = row["cells"][0]["value"]
                    if name in ("Checking - First Bank 1111", "Savings - First Bank 2222", "1010 Checking - First Bank 1111", "1020 Savings - First Bank 2222"):
                        for cell in row["cells"][1:]:
                            cell["value"] = bank if name == "1010 Checking - First Bank 1111" else 0
                bs.write_text(json.dumps(data))
                result, code, err = self.build("2026-08")
                self.assertEqual(code, 0, err)
                report = json.loads((self.board / "2026-08/report.json").read_text())
                self.assertEqual(report["cash"]["bank"], bank)
                self.assertNotIn("We can pay our bills", report["short_answer"])
                self.assertIn("below zero" if bank < 0 else "no bank cash", report["short_answer"])
                result, code, err = self.render("2026-08")
                self.assertEqual(code, 0, err)
                self.assertEqual(result["checks"]["pages"], 2)
                text = page_text(self.church, "2026-08")
                self.assertIn("Bank cash −$300" if bank < 0 else "Bank cash $0", text)
                self.assertNotIn("Only just", text)
                self.assertNotIn("-3.0 months", text)

    # --- the launcher ---------------------------------------------------------------

    def test_launcher_runs_the_finance_report_for_a_connected_church(self):
        church = make_church(Path(self.temp.name))
        shutil.copytree(self.board, church / "finance/board")
        doctor = {"status": "ready", "runtime": {"python": sys.executable}}
        self.assertIn("finance-report", bridge.WORKFLOWS)
        self.assertIn("finance-report", bridge.PDF_WORKFLOWS)
        with mock.patch.object(bridge, "_doctor", return_value=doctor):
            result, code = bridge.execute(church, "finance-report", "status", ["--month", "2026-08"])
            self.assertEqual((result["status"], code), ("blocked", 2))
            self.assertIn("governing body", [c["check"] for c in result["checks"] if c["ok"] is False])
            yaml = church / "church.yaml"
            yaml.write_text(yaml.read_text() + "leadership:\n  governing_body:\n    label: Vestry\n")
            result, code = bridge.execute(church, "finance-report", "status", ["--month", "2026-08"])
        self.assertEqual((result["status"], code), ("ready", 0))
        self.assertTrue(Path(result["handbuilt_run"]).is_file())
        with self.assertRaises(ValueError):
            bridge.execute(church, "finance-report", "status", ["--church-folder=/tmp/another"])


class FinanceChartLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("report_renderer", ENTRY.with_name("report_renderer.py"))
        cls.renderer = importlib.util.module_from_spec(spec)
        with mock.patch.object(sys, "path", [str(ENTRY.parent), *sys.path]):
            spec.loader.exec_module(cls.renderer)
        theme, _ = cls.renderer.resolve_theme({}, {})
        cls.draw = cls.renderer.Draw(theme)

    def test_running_label_stays_inside_chart_without_moving_data(self):
        for month in (1, 3, 8, 12):
            for value, pending in ((50, 0), (-5000, 0), (-5000, 6000), (1234567, 0)):
                with self.subTest(month=month, value=value, pending=pending):
                    run = {"this_year": [value] * month, "this_year_label": "2026",
                           "plan": [0] * 12, "last_year": [100] * 12, "last_year_label": "2025"}
                    root = ET.fromstring(self.renderer.chart_running(self.draw, run, pending))
                    box = root.find("{*}rect")
                    label = next(t for t in root.findall("{*}text") if (t.text or "").startswith("2026:"))
                    left, width = float(box.attrib["x"]), float(box.attrib["width"])
                    self.assertGreaterEqual(left, 0)
                    self.assertLessEqual(left + width, self.renderer.HALF)
                    self.assertGreater(float(label.attrib["x"]), left)
                    self.assertLess(float(label.attrib["x"]), left + width)
                    circles = root.findall("{*}circle")
                    self.assertEqual(len(circles), 2 if pending else 1)
                    expected_x = 4 + (self.renderer.HALF - 4 - 58) * (month - 1) / 11
                    for circle in circles:
                        self.assertAlmostEqual(float(circle.attrib["cx"]), expected_x, places=1)
                    self.assertIn("+" if value >= 0 else "−", label.text)
                    point_y = float(circles[0].attrib["cy"])
                    box_top = float(box.attrib["y"])
                    self.assertTrue(box_top > point_y + 4 or box_top + 15 < point_y - 4)
                    end_labels = [t for t in root.findall("{*}text") if t.text in ("plan", "2025", "break even")]
                    baselines = sorted(float(t.attrib["y"]) for t in end_labels)
                    self.assertTrue(all(b - a >= 11.9 for a, b in zip(baselines, baselines[1:])))
                    self.assertGreaterEqual(baselines[0], 10)
                    self.assertLessEqual(baselines[-1], 123.5)

    def test_cash_marker_and_label_fit_at_both_edges_and_beyond_scale(self):
        for previous, expected in ((0, "last month"), (1, "last month"), (300, "last month"),
                                   (600, "last month"), (1000, "last month (>6 months)"),
                                   (-100, "last month (<0 months)")):
            with self.subTest(previous=previous):
                root = ET.fromstring(self.renderer.chart_cash(self.draw, {"bank": 300, "monthly_spending": 100}, previous))
                marker = root.find("{*}line")
                self.assertGreaterEqual(float(marker.attrib["x1"]), 1)
                self.assertLessEqual(float(marker.attrib["x1"]), self.renderer.HALF - 1)
                label = next(t for t in root.findall("{*}text") if (t.text or "").startswith("last month"))
                self.assertEqual(label.text, expected)
                half_width = len(label.text) * 2.7
                self.assertGreaterEqual(float(label.attrib["x"]) - half_width, 1.9)
                self.assertLessEqual(float(label.attrib["x"]) + half_width, self.renderer.HALF - 1.9)
        root = ET.fromstring(self.renderer.chart_cash(self.draw, {"bank": 300, "monthly_spending": 100}))
        self.assertIsNone(root.find("{*}line"))

    def test_cash_caption_preserves_small_monthly_spending(self):
        for spending, caption in ((50, "$50"), (499.6, "$500"), (12345, "$12,345")):
            with self.subTest(spending=spending):
                root = ET.fromstring(self.renderer.chart_cash(self.draw, {"bank": 300, "monthly_spending": spending}))
                self.assertIn(f"about {caption}.", " ".join(root.itertext()))

    def test_cash_history_handles_negative_zero_and_single_point_series(self):
        for values in ([0, 0, 0], [-300, -1000, -500], [-100, 0, 300], [0], [100, 200]):
            for monthly in (0, -50, 10000):
                with self.subTest(values=values, monthly=monthly):
                    history = [[f"2026-{i + 1:02d}", v] for i, v in enumerate(values)]
                    root = ET.fromstring(self.renderer.chart_cash_line(self.draw, history, monthly))
                    for circle in root.findall("{*}circle"):
                        self.assertGreaterEqual(float(circle.attrib["cy"]), 16)
                        self.assertLessEqual(float(circle.attrib["cy"]), 104)
                    for line in root.findall("{*}line"):
                        self.assertGreaterEqual(float(line.attrib["y1"]), 0)
                        self.assertLessEqual(float(line.attrib["y1"]), 126)
                    if all(v < 0 for v in values):
                        self.assertTrue(all((t.text or "").startswith("−$") for t in root.findall("{*}text") if "$" in (t.text or "")))
                    references = [line for line in root.findall("{*}line") if "stroke-dasharray" in line.attrib]
                    self.assertEqual(len(references), 1 if monthly > 0 else 0)

    def test_nonproportional_groups_keep_signed_amounts_without_percentages(self):
        for amounts in ([], [0, 0], [-100, 100], [-100, -200], [-100, 300]):
            with self.subTest(amounts=amounts):
                parts = [{"name": f"Group {i}", "amount": v, "this_month": v, "note": ""} for i, v in enumerate(amounts)]
                svg, total = self.renderer.chart_share(self.draw, parts)
                legend = self.renderer.share_legend(self.draw.t, parts, total, "August")
                self.assertNotIn("%", svg + legend)
                self.assertEqual(total, sum(amounts))
                self.assertNotIn("<rect", svg)
                if any(v < 0 for v in amounts):
                    self.assertIn("−$100", legend)


if __name__ == "__main__":
    unittest.main()
