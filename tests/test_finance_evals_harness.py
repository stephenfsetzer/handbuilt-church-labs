"""Offline finance model-harness tests: containment and honest failure states."""
from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals/finance"))
import books as B  # noqa: E402
import quickbooks_stub as stub  # noqa: E402
import skill_eval as harness  # noqa: E402
from churches import ALL  # noqa: E402


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="finance-harness-test-")
        self.addCleanup(self.temp.cleanup)
        # Resolve as the harness entry points do: on macOS the temp folder is
        # reached through the /var -> /private/var symlink.
        self.base = Path(self.temp.name).resolve()
        self.root = harness.church_folder("cedar_hollow", self.base / "cedar_hollow")
        self.plugin = self.base / "plugin"
        harness.stage_plugin(self.plugin)
        self.server = stub.Workspace(self.root, self.plugin)

    def command(self, *args):
        return shlex.join([sys.executable, str(self.root / "handbuilt.py"), *args])

    def test_staged_plugin_excludes_truth_and_eval_harness(self):
        self.assertFalse((self.plugin / "evals").exists())
        self.assertFalse((self.plugin / "tests").exists())
        self.assertFalse((self.plugin / ".git").exists())
        self.assertTrue((self.plugin / "skills/finance-onboarding/SKILL.md").is_file())
        self.assertTrue((self.plugin / "requirements.lock").is_file())

    def test_files_cannot_escape_to_host_or_plugin_writes(self):
        outside = self.base / "private.json"
        outside.write_text("host data", encoding="utf-8")
        (self.root / "finance").mkdir(exist_ok=True)
        (self.root / "finance/link.json").symlink_to(outside)
        for filename in [str(outside), "../private.json", "finance/link.json"]:
            with self.subTest(filename=filename):
                with self.assertRaises(ValueError):
                    self.server.call("read_file", {"path": filename})
                with self.assertRaises(ValueError):
                    self.server.call("write_file", {"path": filename, "text": "changed"})
        for filename in ["handbuilt.py", ".handbuilt/installation.json", str(self.plugin / "tools/church_workflow.py")]:
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.server.call("write_file", {"path": filename, "text": "changed"})
        self.assertEqual(outside.read_text(encoding="utf-8"), "host data")

    def test_exact_commands_reject_shell_abbreviations_and_outside_paths(self):
        commands = [
            self.command("finance-onboarding", "orient", "--church", str(self.base)),
            self.command("finance-onboarding", "look", "--balance", str(self.base / "truth.json")),
            self.command("finance-report", "render", "--suffix", "review", str(self.base / "truth.json")),
            self.command("finance-report", "build", "--month", "../../outside"),
            self.command("finance-report", "setup", "budget", "--cs", str(self.base / "truth.csv")),
            self.command("finance-onboarding", "orient") + " ; cat /etc/passwd",
            shlex.join([sys.executable, "-c", "print('arbitrary code')"]),
        ]
        with patch.object(stub.subprocess, "run") as process:
            for command in commands:
                with self.subTest(command=command), self.assertRaises((ValueError, OSError)):
                    self.server.command(command)
            process.assert_not_called()

    @unittest.skipIf(os.name == "nt", "the finance eval harness drives a POSIX shell; it runs on a Mac or Linux")
    def test_config_cannot_redirect_output_and_report_cannot_load_host_history(self):
        target = self.root / "finance/board"
        target.mkdir(parents=True)
        config = target / "config.json"
        config.write_text(json.dumps({"report_folder": str(self.base)}), encoding="utf-8")
        with patch.object(stub.subprocess, "run") as process:
            with self.assertRaisesRegex(ValueError, "report_folder"):
                self.server.command(self.command("finance-report", "status"))
            config.write_text(json.dumps({"report_folder": "finance/board"}), encoding="utf-8")
            report = target / "report.json"
            report.write_text(json.dumps({"meta": {"month": "2026-08", "previous_report": str(self.base / "truth.json")}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                self.server.command(self.command("finance-report", "render", str(report)))
            process.assert_not_called()

    @unittest.skipIf(os.name == "nt", "the finance eval harness drives a POSIX shell; it runs on a Mac or Linux")
    def test_real_adapter_and_launcher_roundtrip_with_only_local_tools(self):
        # Run with the verified managed runtime required by the repository's
        # test recipe. The launcher checks it read-only; this test never installs.
        start = self.server.command(shlex.join([sys.executable, str(self.plugin / "tools/church_workflow.py"),
                                                "--church-folder", str(self.root), "start", "finance-onboarding"]))
        self.assertEqual(start["exit_code"], 0, start)
        books = B.Books(ALL["cedar_hollow"].CHURCH)
        pulls = self.root / "finance/board/setup-pulls"
        for name, value in [("balance-sheet.json", books.balance_sheet(books.last)),
                            ("pl-12m.json", books.pl((2025, 9), books.last))]:
            self.server.call("write_file", {"path": str(pulls / name), "text": json.dumps(value)})
        launcher = json.loads(start["stdout"])["launcher"]
        looked = self.server.command(shlex.join([*launcher, "finance-onboarding", "look", "--balance-sheet", str(pulls / "balance-sheet.json"),
                                                 "--pl-12m", str(pulls / "pl-12m.json")]))
        self.assertEqual(looked["exit_code"], 0, looked)
        self.assertTrue((self.root / "finance/onboarding/findings.json").is_file())

    def test_monthly_prior_settings_exist_for_every_case_including_blocked_sources(self):
        for cid in ALL:
            with self.subTest(cid=cid):
                root = self.base / f"monthly-{cid}"
                root.mkdir()
                harness.prepare_monthly(cid, root)
                config = json.loads((root / "finance/board/config.json").read_text(encoding="utf-8"))
                self.assertEqual(config["report_folder"], "finance/board")
                self.assertEqual(config["bank_accounts"], ALL[cid].TRUTH["everyday_bank"])
                self.assertTrue(json.loads((root / "finance/onboarding-state.json").read_text(encoding="utf-8"))["locked"])


class ConnectorTests(unittest.TestCase):
    def test_profile_condition_does_not_reveal_rubric_or_offer_write(self):
        books = B.Books(ALL["maple_ridge"].CHURCH)
        reply = stub.handle(books, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "profit_loss_quickbooks_account", "arguments": {"periodStart": "2026-01-01", "periodEnd": "2026-08-31"}}})
        self.assertTrue(reply["result"]["isError"])
        text = reply["result"]["content"][0]["text"]
        self.assertIn("profile_info_required", text)
        self.assertNotIn("ask the pastor", text.lower())
        self.assertEqual(len(stub.TOOLS), 3)

    def test_invalid_rpc_arguments_return_errors_and_next_read_survives(self):
        books = B.Books(ALL["cedar_hollow"].CHURCH)
        for args in [[], {"end_date": 7}, {"end_date": "not-a-date"}, {"end_date": "2026-08-31", "write": "yes"}]:
            with self.subTest(args=args):
                reply = stub.handle(books, {"id": 1, "method": "tools/call", "params": {
                    "name": "qbo_accounting_get_balance_sheet", "arguments": args}})
                self.assertTrue(reply["result"]["isError"])
        self.assertFalse(stub.handle(books, {"id": 2, "method": "tools/call", "params": {
            "name": "company_info", "arguments": {}}})["result"]["isError"])

    def test_stdio_survives_invalid_json(self):
        process = subprocess.run([sys.executable, str(ROOT / "evals/finance/quickbooks_stub.py"), "cedar_hollow"],
                                 input='not-json\n{"id":2,"method":"ping"}\n', capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        rows = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(rows[0]["error"]["code"], -32700)
        self.assertEqual(rows[1]["result"], {})


class RunnerAndGradeTests(unittest.TestCase):
    def test_no_builtin_tools_or_host_settings_or_live_mcp(self):
        command = harness.claude_command("request", "sonnet", 1, {"mcpServers": {}})
        self.assertEqual(command[command.index("--tools") + 1], "")
        self.assertEqual(command[command.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", command)
        self.assertNotIn("--permission-mode", command)
        with patch.dict(os.environ, {"OTHER_SERVICE_TOKEN": "never-copy", "HTTPS_PROXY": "proxy", "NODE_EXTRA_CA_CERTS": "trust"}):
            env = harness.isolated_env(Path("/tmp/test-finance-config"))
        self.assertNotIn("OTHER_SERVICE_TOKEN", env)
        self.assertEqual(env["HTTPS_PROXY"], "proxy")
        self.assertEqual(env["NODE_EXTRA_CA_CERTS"], "trust")

    def test_fake_cli_exit_error_and_invalid_json_never_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / "fake_cli.py"
            fake.write_text("import json,sys\nprint(json.dumps({'result':'looks fine','is_error':False}))\nsys.exit(7)\n", encoding="utf-8")
            failed = harness.invoke([sys.executable, str(fake)], cwd=root, env=os.environ.copy(), timeout=5)
            self.assertEqual(failed["returncode"], 7)
            self.assertTrue(failed["error"])
            fake.write_text("print('not-json')\n", encoding="utf-8")
            self.assertTrue(harness.invoke([sys.executable, str(fake)], cwd=root, env=os.environ.copy(), timeout=5)["error"])

    @unittest.skipIf(os.name == "nt", "the finance eval harness drives a POSIX shell; it runs on a Mac or Linux")
    def test_fake_cli_run_records_resolved_model_but_missing_work_still_fails_grade(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            fake = base / "fake_claude.py"
            fake.write_text("""import json, os, pathlib, sys
args = sys.argv[1:]
assert args[args.index('--tools') + 1] == ''
assert '--strict-mcp-config' in args
assert args[args.index('--setting-sources') + 1] == ''
assert set(json.loads(args[args.index('--mcp-config') + 1])['mcpServers']) == {'Workspace', 'QuickBooks'}
plugin = pathlib.Path(args[args.index('--plugin-dir') + 1])
assert not (plugin / 'evals').exists()
assert 'OTHER_SERVICE_TOKEN' not in os.environ
print(json.dumps({'result': 'No work was produced.', 'subtype': 'success', 'modelUsage': {'fake-exact-model-id': {}}}))
""", encoding="utf-8")
            # A shell wrapper, not a shebang naming the interpreter: a shebang cannot
            # hold an interpreter path with a space (the managed runtime lives under
            # "Application Support"), and when exec fails the PATH search moves on
            # to the next folder. PATH holds only the fake, so no real claude runs.
            executable = base / "claude"
            executable.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(fake))} "$@"\n', encoding="utf-8")
            executable.chmod(0o700)
            with patch.dict(os.environ, {"PATH": str(base),
                                         "ANTHROPIC_API_KEY": "synthetic-test-key", "OTHER_SERVICE_TOKEN": "must-not-copy"}):
                result = harness.run("cedar_hollow", "sonnet", base / "results")
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["model_ids"], ["fake-exact-model-id"])
            self.assertFalse(harness.grade(base / "results/cedar_hollow", None)["passed"])

    def test_missing_key_saved_as_failed_run_and_existing_folder_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            result = harness.run("cedar_hollow", "sonnet", root)
            self.assertEqual(result["status"], "failed")
            self.assertIn("ANTHROPIC_API_KEY", result["error"])
            self.assertTrue((root / "cedar_hollow-run.json").exists())
            with self.assertRaises(ValueError):
                harness.run("cedar_hollow", "sonnet", root)

    def test_reject_outputs_inside_repository(self):
        with self.assertRaises(ValueError):
            harness.outside_repo(ROOT / "evals/results")

    def test_strict_judge_requires_complete_boolean_evidence(self):
        items = [{"id": "a", "kind": "tell"}, {"id": "b", "kind": "avoid"}]
        verdict = {"items": [{"id": "a", "pass": True, "quote": "Known."}, {"id": "b", "pass": True, "quote": ""}],
                   "clarity": 4, "clarity_reason": "Readable."}
        self.assertIsNone(harness.validate_verdict(verdict, items, "Known."))
        variants = []
        for key, value in [("pass", "true"), ("quote", "invented"), ("quote", "")]:
            bad = copy.deepcopy(verdict)
            bad["items"][0][key] = value
            variants.append(bad)
        bad = copy.deepcopy(verdict)
        bad["items"].append(bad["items"][0])
        variants.extend([bad, {**verdict, "items": verdict["items"][:1]}, {**verdict, "clarity": True}])
        for bad in variants:
            with self.subTest(bad=bad):
                self.assertIsNotNone(harness.validate_verdict(bad, items, "Known."))

    def test_empty_artifacts_and_no_judge_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "cedar_hollow"
            folder.mkdir()
            result = harness.grade(folder, None)
            self.assertFalse(result["passed"])
            self.assertNotEqual(result["status"], "passed")
            self.assertTrue(result["errors"])

    def test_currency_suffix_does_not_consume_next_word(self):
        self.assertEqual(harness.figures_in("$500 monthly; $250 more; $3k; $2M"), [500, 250, 3000, 2000000])

    def test_large_connector_responses_arrive_whole_in_both_auth_modes(self):
        # Claude Code saves an MCP result above MAX_MCP_OUTPUT_TOKENS to its own
        # tool-results file, which the contained Workspace tool cannot read.
        for variables in [{"ANTHROPIC_API_KEY": "synthetic-test-key"}, {harness.SIGNED_IN: "1", "PATH": "/usr/bin"}]:
            with self.subTest(variables=sorted(variables)), patch.dict(os.environ, variables, clear=True):
                env = harness.isolated_env(Path("/tmp/test-finance-config"))
                self.assertGreaterEqual(int(env["MAX_MCP_OUTPUT_TOKENS"]), 100000)

    def test_prepared_monthly_groups_match_account_codes(self):
        sys.path.insert(0, str(ROOT / "skills/finance-report/scripts"))
        import build_report_data as builder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness.prepare_monthly("cedar_hollow", root)
            config = json.loads((root / "finance/board/config.json").read_text(encoding="utf-8"))
        items = [{"section": a["section"], "chain": [*a.get("under", []), a["name"]], "value": 1.0}
                 for a in ALL["cedar_hollow"].CHURCH["pl"]]
        for side, sections in [("income_groups", builder.INCOME), ("spending_groups", builder.EXPENSE)]:
            with self.subTest(side=side):
                first = config[side][0]
                self.assertGreater(builder.group_items(items, config[side], sections)[first["name"]], 0, first)

    def test_judge_prompt_states_eval_date_and_visual_check(self):
        workspace = [{"tool": "inspect_pdf", "arguments": {"path": "finance/board/2026-08/report.pdf"},
                      "error": False, "response": {"pages": 2}}]
        prompt = harness.judge_prompt([{"id": "a", "kind": "tell", "text": "Tell."}], "Prepared 2026-09-10.",
                                      "cedar_hollow", [], workspace, [])
        self.assertIn(f"Today is {harness.TODAY}", prompt)
        self.assertIn("returned 2 page images", prompt)


class KnownSourceBlockTests(unittest.TestCase):
    """A safe refusal from a cut-off pull is a known block, before look or build runs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="finance-block-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.books = B.Books(ALL["harbor_light"].CHURCH)

    def reads(self, start="2025-09-01"):
        calls = [{"tool": "company_info", "arguments": {}, "error": False, "response": self.books.company_info()}]
        for name, args in [("qbo_accounting_get_balance_sheet", {"end_date": "2026-08-31"}),
                           ("profit_loss_quickbooks_account", {"periodStart": start, "periodEnd": "2026-08-31"})]:
            calls.append({"tool": name, "arguments": args, "error": False, "response": stub.call(self.books, name, args)})
        return calls

    def case(self, skill):
        folder = self.base / skill / "harbor_light"
        folder.mkdir(parents=True)
        (folder / "finance/onboarding").mkdir(parents=True)
        (folder / "finance/finance-overview.md").write_text("The profit and loss was cut off, so its figures cannot be used yet.\n", encoding="utf-8")
        (folder / "finance/onboarding/questions.json").write_text(json.dumps(
            [{"for": "Treasurer", "question": "Can you export the profit and loss?", "why": "The pull was cut off."}]), encoding="utf-8")
        (folder.parent / "harbor_light-run.json").write_text(json.dumps({
            "church": "harbor_light", "skill": skill, "status": "completed", "error": None, "returncode": 0,
            "quickbooks_calls": self.reads(), "workspace_calls": []}), encoding="utf-8")
        return folder

    def test_refusal_after_cut_off_pull_is_a_known_block_for_both_skills(self):
        qcalls = self.reads()
        self.assertEqual(len(qcalls[-1]["response"]["reportData"]["data"]["rows"]), B.CONNECTOR_ROW_LIMIT)
        for skill in harness.SKILLS:
            with self.subTest(skill=skill):
                folder = self.base / f"plain-{skill}"
                folder.mkdir()
                self.assertTrue(harness.known_source_block("harbor_light", skill, folder, [], qcalls))

    def test_refusal_is_not_a_block_once_findings_or_a_report_exist_or_without_a_cut_off(self):
        qcalls = self.reads()
        folder = self.base / "with-findings"
        (folder / "finance/onboarding").mkdir(parents=True)
        (folder / "finance/onboarding/findings.json").write_text(json.dumps({"findings": [{"id": "x"}]}), encoding="utf-8")
        self.assertFalse(harness.known_source_block("harbor_light", "finance-onboarding", folder, [], qcalls))
        (folder / "finance/board/2026-08").mkdir(parents=True)
        (folder / "finance/board/2026-08/report.json").write_text(json.dumps({"meta": {"status": "draft"}}), encoding="utf-8")
        self.assertFalse(harness.known_source_block("harbor_light", "finance-report", folder, [], qcalls))
        empty = self.base / "short-pull"
        empty.mkdir()
        short = [call for call in qcalls if call["tool"] != "profit_loss_quickbooks_account"]
        self.assertFalse(harness.known_source_block("harbor_light", "finance-onboarding", empty, [], short))
        cedar = B.Books(ALL["cedar_hollow"].CHURCH)
        args = {"periodStart": "2025-09-01", "periodEnd": "2026-08-31"}
        normal = [{"tool": "profit_loss_quickbooks_account", "arguments": args, "error": False,
                   "response": stub.call(cedar, "profit_loss_quickbooks_account", args)}]
        self.assertFalse(harness.known_source_block("cedar_hollow", "finance-onboarding", empty, [], normal))

    def test_refusal_is_graded_with_the_blocked_rubric(self):
        for skill in harness.SKILLS:
            with self.subTest(skill=skill):
                result = harness.grade(self.case(skill), None)
                self.assertEqual(result["outcome"], "source_blocked")
                self.assertIn("block-tell", [item["id"] for item in result["rubric"]])
                self.assertFalse([error for error in result["errors"] if "missing successful" in error
                                  and "start" not in error], result["errors"])

    def test_invalid_judge_verdict_is_retried_once_with_the_reason(self):
        folder = self.case("finance-onboarding")
        quote = "The profit and loss was cut off, so its figures cannot be used yet."
        good = {"items": [{"id": ident, "pass": True, "quote": quote} for ident in
                          ("block-tell", "block-ask", "block-avoid", "source-claims", "human-decisions")],
                "clarity": 5, "clarity_reason": "Clear.", "judge_cost_usd": 0.5}
        bad = copy.deepcopy(good)
        bad["items"][0]["quote"] = "A sentence the pastor never saw."
        prompts = []

        def fake_judge(prompt, model):
            prompts.append(prompt)
            return copy.deepcopy(bad if len(prompts) == 1 else good)

        with patch.object(harness, "judge", side_effect=fake_judge):
            result = harness.grade(folder, "judge-model")
        self.assertEqual(len(prompts), 2)
        self.assertIn("judge quote is absent from submitted writing: block-tell", prompts[1])
        self.assertIsNone(result["judge_error"])
        self.assertEqual(result["judge_attempts"], 2)
        self.assertEqual(result["clarity"], 5)

    def test_judge_retries_only_once(self):
        folder = self.case("finance-onboarding")
        with patch.object(harness, "judge", return_value={"error": "invalid judge JSON: nope"}) as judged:
            result = harness.grade(folder, "judge-model")
        self.assertEqual(judged.call_count, 2)
        self.assertEqual(result["status"], "failed")
        self.assertIn("invalid judge JSON", result["judge_error"])


class RevisionTests(unittest.TestCase):
    """Redwood Crossing's late repair posting appears on a later read covering its month."""

    def setUp(self):
        self.church = ALL["redwood_crossing"].CHURCH
        revision = self.church["connector"]["revisions"][0]
        self.account, self.month, self.amount = revision["account"], revision["month"], revision["amount"]

    @staticmethod
    def repairs(report, account):
        for row in report["reportData"]["data"]["rows"]:
            cells = {cell["name"]: cell["value"] for cell in row["cells"]}
            if cells["ACCOUNT_NAME"] == account:
                return cells["DETAIL_NATURAL_HOME_AMOUNT__TOTAL"]
        raise AssertionError("account missing")

    def test_later_covering_read_serves_the_revision_even_when_not_identical(self):
        books = B.Books(self.church)
        original = books.pl((2025, 9), (2026, 8))
        pl = "profit_loss_quickbooks_account"
        # A period that does not cover the revised month is unchanged and does not count.
        stub.call(books, pl, {"periodStart": "2026-01-01", "periodEnd": "2026-08-31"})
        first = stub.call(books, pl, {"periodStart": "2025-09-01", "periodEnd": "2026-08-31"})
        self.assertEqual(self.repairs(first, self.account), self.repairs(original, self.account))
        later = stub.call(books, pl, {"periodStart": "2025-12-01", "periodEnd": "2026-08-31", "split_by": "month"})
        whole = books.pl((2025, 12), (2026, 8))
        self.assertAlmostEqual(self.repairs(later, self.account), self.repairs(whole, self.account) + self.amount, places=2)

    def test_balance_sheet_read_counts_as_covering_the_month(self):
        books = B.Books(self.church)
        stub.call(books, "qbo_accounting_get_balance_sheet", {"end_date": "2026-08-31"})
        later = stub.call(books, "profit_loss_quickbooks_account", {"periodStart": "2025-09-01", "periodEnd": "2026-08-31"})
        original = books.pl((2025, 9), (2026, 8))
        self.assertAlmostEqual(self.repairs(later, self.account), self.repairs(original, self.account) + self.amount, places=2)


if __name__ == "__main__":
    unittest.main()


class StubKeepsUpWithTheScripts(unittest.TestCase):
    """The stand-in shell allows a fixed list of options. A new script option missing from it
    makes every eval run fail for the eval's reason, not the plugin's."""

    def test_every_workflow_option_is_allowed_by_the_stub(self):
        import re
        REPO = Path(__file__).resolve().parents[1]
        stub = (REPO / "evals" / "finance" / "quickbooks_stub.py").read_text(encoding="utf-8")
        scripts = {
            "look": REPO / "skills/finance-onboarding/scripts/finance_onboarding.py",
            "build": REPO / "skills/finance-report/scripts/build_report_data.py",
            "draft": REPO / "skills/finance-report/scripts/finance_setup.py",
        }
        for name, script in scripts.items():
            options = set(re.findall(r'add_argument\("(--[a-z0-9-]+)"', script.read_text(encoding="utf-8")))
            missing = sorted(o for o in options if f'"{o}"' not in stub and o not in {"--church-folder", "--format", "--out", "--help"})
            self.assertEqual(missing, [], f"{name}: options the stub does not allow")


class PreparedSettingsFollowTheChurchYear(unittest.TestCase):
    def test_a_july_church_saves_last_year_july_to_june(self):
        import json
        import sys
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals" / "finance"))
        import books as B
        import skill_eval as harness
        from churches import ALL
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "church"
            harness.church_folder("lantern_hill", root)
            harness.prepare_monthly("lantern_hill", root)
            saved = json.loads((root / "finance/board/config.json").read_text(encoding="utf-8"))["long_view"]["full_years"]
        books = B.Books(ALL["lantern_hill"].CHURCH)
        last = saved[-1]
        self.assertEqual(last["reported"], round(books.period_result((last["year"], 7), (last["year"] + 1, 6))))

    def test_the_judge_knows_the_earlier_approvals_given_in_the_task(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals" / "finance"))
        import skill_eval as harness
        prompt = harness.judge_prompt([], "x", "alder_meadow", [], [], [])
        self.assertIn("going without a budget", prompt)


class SavedLargeReplies(unittest.TestCase):
    def test_the_workspace_reads_a_reply_claude_code_saved_to_a_file(self):
        import sys
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals" / "finance"))
        import quickbooks_stub as stub
        with tempfile.TemporaryDirectory() as tmp:
            space = stub.Workspace(Path(tmp), Path(tmp))
            saved = Path.home() / ".claude" / "projects" / "x" / "tool-results" / "reply.txt"
            self.assertEqual(space.path(str(saved)), saved.resolve())
            with self.assertRaises(ValueError):
                space.path(str(saved), write=True)
            with self.assertRaises(ValueError):
                space.path(str(Path.home() / ".claude" / "settings.json"))


class CopyingASavedReply(unittest.TestCase):
    def test_copy_saves_the_reply_text_not_the_wrapper(self):
        import json
        import sys
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals" / "finance"))
        import quickbooks_stub as stub
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "church"
            (root / "finance").mkdir(parents=True)
            saved = Path(tmp) / "reply.json"
            saved.write_text(json.dumps([{"type": "text", "text": '{"reportTitle": "Balance Sheet"}'}]), encoding="utf-8")
            space = stub.Workspace(root, root)
            space.path = lambda value, write=False, _orig=space.path: Path(value) if value == str(saved) else _orig(value, write=write)
            space.call("copy_file", {"source": str(saved), "destination": "finance/bs.json"})
            self.assertEqual((root / "finance/bs.json").read_text(encoding="utf-8"), json.dumps([{"type": "text", "text": '{"reportTitle": "Balance Sheet"}'}]))
            tool_results = Path(tmp) / "tool-results"
            tool_results.mkdir()
            moved = tool_results / "reply.json"
            moved.write_text(saved.read_text(encoding="utf-8"), encoding="utf-8")
            space.path = lambda value, write=False, _orig=stub.Workspace(root, root).path: moved if value == str(moved) else _orig(value, write=write)
            space.call("copy_file", {"source": str(moved), "destination": "finance/bs2.json"})
            self.assertEqual((root / "finance/bs2.json").read_text(encoding="utf-8"), '{"reportTitle": "Balance Sheet"}')
