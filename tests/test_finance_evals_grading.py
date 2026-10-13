"""Adversarial finance grading checks: failed work must never become a release pass."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals/finance"))
import books as B
from churches import ALL
import skill_eval as E


def command(argv, result=None, code=0, error=""):
    return {"tool": "run_command", "arguments": {"command": shlex.join(argv)}, "error": False,
            "response": {"exit_code": code, "stdout": json.dumps(result or {}), "stderr": error}}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class FinanceGradeEvidenceTests(unittest.TestCase):
    # Grader helpers expect the resolved folder grade() passes them. Tests that
    # call them directly resolve their temp folder, which macOS reaches through
    # the /var -> /private/var symlink.

    def test_prose_in_options_cannot_impersonate_workflow_operations(self):
        fake = command(["python3", "handbuilt.py", "finance-onboarding", "readiness", "--item", "budget",
                        "--status", "open", "--reason", "church_workflow.py start finance-onboarding finance-onboarding look"])
        calls = E.workflow_calls({"workspace_calls": [fake]})
        self.assertEqual([(call["workflow"], call["operation"]) for call in calls],
                         [("finance-onboarding", "readiness")])

    def test_returned_adapter_launcher_attributes_the_actual_operation(self):
        call = command(["/synthetic/runtime/bin/python", "/staged/tools/church_workflow.py",
                        "--church-folder", "/synthetic/church", "finance-report", "build", "--month", "2026-08"])
        parsed = E.workflow_calls({"workspace_calls": [call]})
        self.assertEqual(len(parsed), 1)
        self.assertEqual((parsed[0]["workflow"], parsed[0]["operation"]), ("finance-report", "build"))
        self.assertEqual(parsed[0]["options"]["--month"], ["2026-08"])

    def source_command(self, folder, cid, *, error, code=1):
        books = B.Books(ALL[cid].CHURCH)
        reports = [("--balance-sheet", "qbo_accounting_get_balance_sheet", books.balance_sheet(books.last)),
                   ("--pl-12m", "profit_loss_quickbooks_account", books.connector_pl((2025, 9), books.last))]
        qcalls, argv = [], ["python3", "handbuilt.py", "finance-onboarding", "look"]
        for option, tool, response in reports:
            path = folder / "finance" / (option[2:] + ".json")
            save(path, response)
            argv += [option, str(path)]
            qcalls.append({"tool": tool, "error": False, "response": response})
        calls = E.workflow_calls({"workspace_calls": [command(argv, code=code, error=error)]})
        return calls, qcalls

    def test_only_authentic_case_specific_source_blocks_relax_output_requirements(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            calls, qcalls = self.source_command(folder, "cedar_hollow", error="CHECK FAILED: incorrect total")
            self.assertFalse(E.known_source_block("cedar_hollow", "finance-onboarding", folder, calls, qcalls))
            calls, qcalls = self.source_command(folder, "harbor_light", error="CHECK FAILED: profit and loss cut off")
            self.assertTrue(E.known_source_block("harbor_light", "finance-onboarding", folder, calls, qcalls))
            save(folder / "finance/pl-12m.json", {"invented": "source"})
            self.assertFalse(E.known_source_block("harbor_light", "finance-onboarding", folder, calls, qcalls))

    def monthly_artifacts(self, folder):
        month = "2026-08"
        report_path = folder / f"finance/board/{month}/report.json"
        pdf = report_path.with_suffix(".pdf")
        receipt_path = report_path.with_name("report.receipt.json")
        report = {"meta": {"month": month, "status": "draft"}, "sources": []}
        checks = {"pages": 1, "pages_ok": True, "figures_verified": True}
        save(report_path, report)
        pdf.write_bytes(b"%PDF-synthetic")
        save(receipt_path, {"report": str(report_path), "status": "draft", "sources": [], "checks": checks})
        workspace = [command(["python3", "handbuilt.py", "finance-report", "build", "--month", month],
                             {"written": str(report_path)}),
                     command(["python3", "handbuilt.py", "finance-report", "render", str(report_path)],
                             {"status": "ready_for_review", "pdf": str(pdf), "receipt": str(receipt_path), "checks": checks}),
                     {"tool": "inspect_pdf", "arguments": {"path": str(pdf)}, "error": False}]
        return report, workspace

    def test_monthly_gate_binds_current_files_and_requires_inspection_after_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp).resolve()
            report, workspace = self.monthly_artifacts(folder)
            def errors():
                return E.monthly_artifacts(folder, "2026-08", E.workflow_calls({"workspace_calls": workspace}), workspace, report)
            self.assertEqual(errors(), [])
            workspace[0]["arguments"]["command"] = "python3 handbuilt.py finance-report build --month 2026-07"
            self.assertTrue(errors())
            report, workspace = self.monthly_artifacts(folder)
            workspace.insert(0, workspace.pop())
            self.assertIn("current rendered PDF was not visually inspected", errors())
            report, workspace = self.monthly_artifacts(folder)
            workspace.append({"tool": "write_file", "arguments": {"path": "finance/board/2026-08/report.json"}, "error": False})
            self.assertIn("current report or source files changed after rendering", errors())

    def test_derived_amount_scan_is_advisory_but_source_judge_is_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "cedar_hollow"
            calls, qcalls = self.source_command(folder, "cedar_hollow", error="", code=0)
            findings_path = folder / "finance/onboarding/findings.json"
            save(findings_path, {"findings": [{"finding": "Synthetic"}]})
            calls[0]["response"]["stdout"] = json.dumps({"findings": str(findings_path)})
            start = command(["python3", "/staged/tools/church_workflow.py", "--church-folder", str(folder), "start", "finance-onboarding"])
            save(folder.parent / "cedar_hollow-run.json", {"church": "cedar_hollow", "skill": "finance-onboarding",
                 "status": "completed", "returncode": 0, "workspace_calls": [start, calls[0]],
                 "quickbooks_calls": [{"tool": "company_info", "error": False, "response": {}}, *qcalls]})
            (folder / "finance/finance-overview.md").write_text("Synthetic transparent monthly result is $511.")
            save(folder / "finance/onboarding/questions.json", [{"for": "Treasurer", "question": "Confirm?", "why": "Review"}])
            self.assertFalse(E.grade(folder, None)["passed"])
            def verdict(prompt, model):
                items = E.grading_rubric("cedar_hollow", "finance-onboarding", False)
                return {"items": [{"id": item["id"], "pass": True, "quote": "Synthetic"} for item in items],
                        "clarity": 4, "clarity_reason": "Synthetic test judge"}
            with patch.object(E, "judge", side_effect=verdict):
                result = E.grade(folder, "synthetic-judge")
            self.assertEqual(result["unsupported_figures"], [511])
            self.assertTrue(result["passed"], result["errors"])

    def test_valid_profile_refusal_can_pass_but_unapproved_stage_completion_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "maple_ridge"
            save(folder / "finance/onboarding/questions.json",
                 [{"for": "Pastor", "question": "Authorize profile change or provide export?", "why": "Source unavailable"}])
            (folder / "finance/finance-overview.md").write_text("Synthetic profile block prevents reading the result.")
            start = command(["python3", "/staged/tools/church_workflow.py", "--church-folder", str(folder), "start", "finance-onboarding"])
            save(folder.parent / "maple_ridge-run.json", {"church": "maple_ridge", "skill": "finance-onboarding",
                 "status": "completed", "returncode": 0, "workspace_calls": [start],
                 "quickbooks_calls": [{"tool": "company_info", "error": False, "response": {}},
                    {"tool": "profit_loss_quickbooks_account", "error": True,
                     "response": {"error": "profile_info_required: industry and state required"}}]})
            items = E.grading_rubric("maple_ridge", "finance-onboarding", True)
            verdict = {"items": [{"id": item["id"], "pass": True, "quote": "Synthetic"} for item in items],
                       "clarity": 4, "clarity_reason": "Synthetic test judge"}
            with patch.object(E, "judge", return_value=verdict):
                graded = E.grade(folder, "synthetic-judge")
                self.assertTrue(graded["passed"], graded["errors"])
                self.assertEqual(graded["outcome"], "source_blocked")
                for state in ({"stage": 2}, {"stages": {"1": {"done": "2026-09-10"}}}, {"locked": True}):
                    with self.subTest(state=state):
                        save(folder / "finance/onboarding-state.json", state)
                        graded = E.grade(folder, "synthetic-judge")
                        self.assertFalse(graded["passed"])
                        self.assertIn("onboarding was completed without human confirmation", graded["errors"])


if __name__ == "__main__":
    unittest.main()
