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

    def test_files_cannot_escape_to_host_or_plugin_writes(self):
        outside = self.base / "private.json"
        outside.write_text("host data")
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
        self.assertEqual(outside.read_text(), "host data")

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

    def test_config_cannot_redirect_output_and_report_cannot_load_host_history(self):
        target = self.root / "finance/board"
        target.mkdir(parents=True)
        config = target / "config.json"
        config.write_text(json.dumps({"report_folder": str(self.base)}))
        with patch.object(stub.subprocess, "run") as process:
            with self.assertRaisesRegex(ValueError, "report_folder"):
                self.server.command(self.command("finance-report", "status"))
            config.write_text(json.dumps({"report_folder": "finance/board"}))
            report = target / "report.json"
            report.write_text(json.dumps({"meta": {"month": "2026-08", "previous_report": str(self.base / "truth.json")}}))
            with self.assertRaises(ValueError):
                self.server.command(self.command("finance-report", "render", str(report)))
            process.assert_not_called()

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
                config = json.loads((root / "finance/board/config.json").read_text())
                self.assertEqual(config["report_folder"], "finance/board")
                self.assertEqual(config["bank_accounts"], ALL[cid].TRUTH["everyday_bank"])
                self.assertTrue(json.loads((root / "finance/onboarding-state.json").read_text())["locked"])


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
                                 input='not-json\n{"id":2,"method":"ping"}\n', capture_output=True, text=True, check=True)
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
            fake.write_text("import json,sys\nprint(json.dumps({'result':'looks fine','is_error':False}))\nsys.exit(7)\n")
            failed = harness.invoke([sys.executable, str(fake)], cwd=root, env=os.environ.copy(), timeout=5)
            self.assertEqual(failed["returncode"], 7)
            self.assertTrue(failed["error"])
            fake.write_text("print('not-json')\n")
            self.assertTrue(harness.invoke([sys.executable, str(fake)], cwd=root, env=os.environ.copy(), timeout=5)["error"])

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
""")
            # A shell wrapper, not a shebang naming the interpreter: a shebang cannot
            # hold an interpreter path with a space (the managed runtime lives under
            # "Application Support"), and when exec fails the PATH search moves on
            # to the next folder. PATH holds only the fake, so no real claude runs.
            executable = base / "claude"
            executable.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(fake))} "$@"\n')
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


if __name__ == "__main__":
    unittest.main()
